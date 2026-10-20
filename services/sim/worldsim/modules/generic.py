"""Generic fallback for events without a domain module: stock-and-flow diffusion of impact from the origin
through ground (distance kernel) and network (hub) channels, with an attention cycle and recovery.
Parameters come from the analog class of the event type. Always flagged low confidence."""
from __future__ import annotations

import numpy as np

from ..analogs import analogs_for
from ..world import haversine_km
from .base import STATUS, TRAITS, Context, Module, Prior, Trajectory, monotone

# event type → (reach_km, spread rate per day, hub coupling, recovery days, peak impact share) — analog-class priors
MATERIAL = 0.2  # impact index (0-1) above which residents count as materially affected
SPILL = 0.25    # hub spillover strength relative to the origin (network channel, distance-independent)
CLASS = {'conflict': (800, 0.15, 0.3, 120, 0.6), 'finance': (1200, 0.25, 1.0, 90, 0.3), 'election': (1000, 0.3, 0.3, 45, 0.3),
         'climate': (1500, 0.05, 0.2, 150, 0.5), 'social': (400, 0.3, 0.3, 30, 0.3), 'corporate': (500, 0.2, 0.6, 60, 0.2),
         'disaster': (500, 0.4, 0.1, 90, 0.7), 'supply_chain': (1500, 0.15, 1.0, 60, 0.3), 'generic': (1000, 0.15, 0.5, 60, 0.3)}


class Generic(Module):
    name = 'generic'
    key_metric = 'affected_pop'
    key_unit = 'people materially affected (cumulative)'
    persona_metric = ('impact index', 'index 0-100')
    layers = [('impact_index', 'Impact index', '0-100'), ('affected_pct', 'Population materially affected', '%')]
    outcome_spec = [('affected_pop', 'People materially affected', 'people'), ('countries', 'Countries with material impact', 'countries'),
                    ('peak_day', 'Day of peak impact', 'day'), ('aware_pop', 'People aware of the event', 'people')]
    mechanisms = ['direct impact near the origin', 'network spillovers through hubs', 'attention cycle', 'recovery']
    confidence = 'low'
    calibration_note = 'Generic fallback: mechanisms and parameters come from the event class, not a calibrated domain model. Low confidence by construction.'

    def priors(self, ctx: Context) -> list[Prior]:
        reach, rate, hub, rec, peak = CLASS.get(ctx.spec.event_type, CLASS['generic'])
        an = ', '.join(a['name'] for a in analogs_for(ctx.spec)) or 'no close analog in the library'
        src = f'event-class prior; closest analogs: {an}'
        return [Prior('reach_km', 'Distance over which direct impact decays', reach, reach * 0.5, reach * 2, 'km', 'model', 'low', src),
                Prior('spread_rate', 'Daily spread rate of impact', rate, rate * 0.5, rate * 1.8, '/day', 'model', 'low', src),
                Prior('hub_coupling', 'Strength of spillovers through major hubs', hub, hub * 0.4, min(hub * 2, 2), '', 'model', 'low', src),
                Prior('recovery_days', 'Recovery time constant', rec, rec * 0.5, rec * 2, 'days', 'model', 'low', src),
                Prior('peak_share', 'Share of exposed population materially affected at the epicenter', peak, peak * 0.5, min(peak * 1.5, 1), 'share', 'model', 'low', src)]

    def simulate(self, ctx: Context, p: dict, rng: np.random.Generator, detail: bool) -> Trajectory:
        T, L, C = ctx.steps, ctx.L, ctx.C
        o = ctx.origin_loc if ctx.origin_loc is not None else int(np.argmax(ctx.loc_pop))
        d = ctx.d_origin if ctx.origin_loc is not None else haversine_km(ctx.loc_lat[o], ctx.loc_lon[o], ctx.loc_lat, ctx.loc_lon)
        cap = np.exp(-(d / p['reach_km']) ** 2)
        hubs = np.argsort(-ctx.loc_pop)[:40]
        hub_mask = np.zeros(L, bool)
        hub_mask[hubs] = True
        e = np.zeros(L)
        e[o] = 1.0
        ever = np.zeros(L)
        key = np.zeros(T + 1)
        metrics, layers, flows, events = [], [], [], []
        p_status = np.zeros((T + 1, ctx.P), np.int8) if detail else None
        p_metric = np.zeros((T + 1, ctx.P), np.float32) if detail else None
        i_status = np.zeros((T + 1, ctx.I), np.int8) if detail else None
        i_metric = np.zeros((T + 1, ctx.I), np.float32) if detail else None
        status = np.zeros(ctx.P, np.int8)
        me = ctx.p_traits[:, TRAITS.index('media_exposure')]
        trust = ctx.p_traits[:, TRAITS.index('institutional_trust')]
        reached = np.zeros(C, bool)
        series = []
        noise = rng.lognormal(0, 0.2, L)
        for t in range(T + 1):
            day = t * ctx.dt
            if t > 0:
                ground = np.exp(-(d / (p['reach_km'] * min(1.0, day / 14))) ** 2) if day < 14 else cap
                spill = np.where(hub_mask, SPILL * p['hub_coupling'] * e[o], 0.0)  # hubs feel a fraction of the origin's impact
                target = np.clip(np.maximum(ground * e[o], spill) * noise, 0, 1)
                e = e + p['spread_rate'] * ctx.dt * (target - e)
                e *= np.exp(-ctx.dt / p['recovery_days']) if day > 14 else 1.0
                e[o] = max(e[o], np.exp(-max(day - 14, 0) / p['recovery_days']))
            affected = ctx.loc_pop * np.where(e >= MATERIAL, np.clip(e, 0, 1), 0.0) * p['peak_share']
            ever = np.maximum(ever, affected)
            series.append(affected.sum())
            aff_c = np.bincount(ctx.loc_c, weights=ever, minlength=C)
            newly = (~reached) & (aff_c / np.maximum(ctx.c_pop, 1) >= 0.001)
            reached |= newly
            key[t] = ever.sum()
            aware_share = np.clip(e.max() * (0.3 + me), 0, 1)
            metrics.append({'affected_pop': float(ever.sum()), 'affected_now': float(affected.sum()), 'countries': int(reached.sum())})
            if not detail:
                continue
            if t == 0:
                events.append({'t': 0, 'title': 'Event begins (generic fallback model)', 'cause': p_src(self, ctx), 'places': [ctx.loc_name[o]], 'severity': 3})
            for c in np.flatnonzero(newly)[:3]:
                if reached.sum() <= 10:
                    events.append({'t': t, 'title': f'Material impact reaches {ctx.c_name[c]}', 'cause': 'spillover via proximity or hubs', 'places': [ctx.c_name[c]], 'severity': 2})
            if t > 1 and series[-2] > series[-1] and len(series) > 2 and series[-3] <= series[-2]:
                events.append({'t': t, 'title': 'Impact peaks', 'cause': f'recovery time constant {p["recovery_days"]:.0f} days', 'places': [], 'severity': 3})
            idx = np.clip(e * 100, 0, 100)
            m = idx[ctx.p_loc]
            new = np.zeros(ctx.P, np.int8)
            new[(m > 1) | (me * e.max() > 0.3)] = STATUS['aware']
            new[m >= 10] = STATUS['reacting']
            new[m >= MATERIAL * 100] = STATUS['affected']
            new[(m >= 10) & (trust < 0.35) & (ctx.spec.event_type in ('election', 'social', 'policy', 'conflict'))] = STATUS['opposed']
            peak_passed = np.array([max(series) > series[-1] * 1.5]) if series else np.array([False])
            status = monotone(new, status)
            status[(status == STATUS['affected']) & (m < 15) & peak_passed[0]] = STATUS['recovered']
            p_status[t] = status
            p_metric[t] = np.round(m, 1)
            for j, inst in enumerate(ctx.institutions):
                s = STATUS['affected'] if e[inst.loc] >= 0.35 or (inst.role in ('government', 'media') and t >= 1) else STATUS['reacting'] if e.max() > 0.1 else STATUS['aware']
                i_status[t, j] = max(s, i_status[t - 1, j] if t else 0)
                i_metric[t, j] = float(idx[inst.loc])
            ic = np.zeros(C)
            np.maximum.at(ic, ctx.loc_c, idx)
            layers.append({'impact_index': {ctx.iso3[c]: round(float(ic[c]), 1) for c in np.flatnonzero(ic >= 1)},
                           'affected_pct': {ctx.iso3[c]: round(float(aff_c[c] / ctx.c_pop[c] * 100), 2) for c in np.flatnonzero(aff_c / np.maximum(ctx.c_pop, 1) >= 1e-4)}})
            fl = []
            for h in hubs[:12]:
                if e[h] > 0.05 and h != o:
                    fl.append({'from': [float(ctx.loc_lon[o]), float(ctx.loc_lat[o])], 'to': [float(ctx.loc_lon[h]), float(ctx.loc_lat[h])], 'weight': float(e[h]), 'kind': 'spread'})
            flows.append(fl)
        out = {'affected_pop': float(ever.sum()), 'countries': float(reached.sum()), 'peak_day': float(np.argmax(series) * ctx.dt),
               'aware_pop': float((ctx.p_pop * np.clip(0.3 + me, 0, 1)).sum())}
        traj = Trajectory(key=key, metrics=metrics, outcomes=out)
        if detail:
            traj.p_status, traj.p_metric, traj.i_status, traj.i_metric = p_status, p_metric, i_status, i_metric
            traj.layers, traj.flows, traj.events = layers, flows, events
            aff_c = np.bincount(ctx.loc_c, weights=ever, minlength=C)
            top = [c for c in np.argsort(-aff_c)[:10] if aff_c[c] > 0]
            traj.breakdown['most_affected'] = [{'country': ctx.c_name[c], 'affected_m': round(aff_c[c] / 1e6, 2), 'share_pct': round(aff_c[c] / ctx.c_pop[c] * 100, 1)} for c in top]
            traj.breakdown['winners'] = []
            traj.breakdown['losers'] = [{'name': ctx.c_name[c], 'why': f'{aff_c[c] / ctx.c_pop[c] * 100:.0f}% of people materially affected', 'detail': 'generic fallback'} for c in top[:3]]
            traj.causal = {'nodes': [{'id': 'event', 'label': 'Event at the origin'}, {'id': 'ground', 'label': f'Direct impact within ~{p["reach_km"]:,.0f} km'},
                                     {'id': 'hubs', 'label': 'Spillovers through major hubs'}, {'id': 'attention', 'label': 'Attention and reaction'},
                                     {'id': 'recovery', 'label': f'Recovery (~{p["recovery_days"]:.0f} days)'}],
                           'edges': [{'from': 'event', 'to': 'ground'}, {'from': 'event', 'to': 'hubs'}, {'from': 'ground', 'to': 'attention'},
                                     {'from': 'hubs', 'to': 'attention'}, {'from': 'attention', 'to': 'recovery'}]}
        return traj

    def inst_metric(self, role: str) -> tuple[str, str]:
        return ('impact index at its location', 'index 0-100')

    def inst_text(self, role: str, v: float) -> str:
        return f'impact index {v:.0f}'


def p_src(mod, ctx) -> str:
    an = analogs_for(ctx.spec)
    return 'closest analogs: ' + (', '.join(a['name'] for a in an) if an else 'none in the library') + '; low confidence'
