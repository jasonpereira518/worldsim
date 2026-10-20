"""Earthquake: intensity attenuation → fatalities (PAGER-style), injuries, displacement, outages, losses, recovery.

Data used: population by location, GDP per capita (vulnerability and exposed capital). Hazard and vulnerability
parameters are priors. Known limit: population outside listed cities sits at the country label point, so exposure
far from cities is approximate until gridded population (WorldPop/GHSL) is ingested.
"""
from __future__ import annotations

import math

import numpy as np

from ..world import haversine_km
from .base import STATUS, TRAITS, Context, Module, Prior, Trajectory, monotone

PAGER = 'Jaiswal & Wald (2010), USGS PAGER empirical fatality model: rate = Φ(ln(MMI/θ)/β); θ approximated from GDP per capita here'
BATH = 'Båth (1965): largest aftershock ≈ mainshock magnitude − 1.2'
_erf = np.vectorize(math.erf)


def phi(x) -> np.ndarray:
    return 0.5 * (1 + _erf(np.asarray(x, dtype=float) / math.sqrt(2)))


def vulnerability(gdp_pc: np.ndarray) -> np.ndarray:
    """0 (rich, engineered stock) to 1 (poor, non-engineered stock), from GDP per capita on a log scale."""
    g = np.where(np.isfinite(gdp_pc), gdp_pc, 5000.0)
    return np.clip((math.log10(60000) - np.log10(np.maximum(g, 300))) / (math.log10(60000) - math.log10(1000)), 0, 1)


RING = np.repeat(np.sqrt((np.arange(4) + 0.5) / 4), 3)  # area-weighted ring radii (share of disc radius)
COS = np.tile(np.cos(np.array([0.0, math.pi / 2, math.pi])), 4)  # bearings toward, across and away from the epicenter


def exposure(ctx: Context, density: float) -> dict:
    """Exposure points: each city as a disc of radius sqrt(pop/(π·density)); each country's remaining population
    split across its admin-1 units in proportion to land area (assumption: uniform rural density), mapped back to
    the country's "rest of" location."""
    from ..world import admin1
    key = ('_eq_exposure', density)
    cached = getattr(ctx, '_eq_cache', {})
    if key in cached:
        return cached[key]
    lat, lon, pop, loc, c, rad = [], [], [], [], [], []
    units: dict[str, list] = {}
    for iso3, name, la, lo, area in admin1(ctx.world.path):
        units.setdefault(iso3, []).append((la, lo, area))
    for i in range(ctx.L):
        if ctx.loc_urban[i]:
            lat.append(ctx.loc_lat[i]); lon.append(ctx.loc_lon[i]); pop.append(ctx.loc_pop[i]); loc.append(i); c.append(ctx.loc_c[i])
            rad.append(math.sqrt(ctx.loc_pop[i] / (math.pi * density)))
            continue
        us = [u for u in units.get(ctx.iso3[ctx.loc_c[i]], []) if u[2] > 0]
        total = sum(u[2] for u in us)
        if not us or total <= 0:
            lat.append(ctx.loc_lat[i]); lon.append(ctx.loc_lon[i]); pop.append(ctx.loc_pop[i]); loc.append(i); c.append(ctx.loc_c[i]); rad.append(0.0)
            continue
        for la, lo, area in us:
            lat.append(la); lon.append(lo); pop.append(ctx.loc_pop[i] * area / total); loc.append(i); c.append(ctx.loc_c[i])
            rad.append(math.sqrt(area / math.pi) * 0.7)  # spread across the province
    out = {'lat': np.array(lat), 'lon': np.array(lon), 'pop': np.array(pop), 'loc': np.array(loc), 'c': np.array(c), 'radius': np.array(rad)}
    cached[key] = out
    ctx._eq_cache = cached
    return out


def intensity(magnitude: float, R_km: np.ndarray, attenuation: float) -> np.ndarray:
    """Simplified isoseismal relation MMI = 1 + 1.5·M − c·log10(R), clipped to [1, 12]."""
    return np.clip(1 + 1.5 * magnitude - attenuation * np.log10(np.maximum(R_km, 1)), 1, 12)


class Earthquake(Module):
    name = 'disaster'
    key_metric = 'deaths'
    key_unit = 'reported deaths'
    persona_metric = ('shaking intensity', 'MMI')
    layers = [('intensity_mmi', 'Peak shaking (MMI)', 'MMI'), ('deaths_per_100k', 'Deaths per 100k', 'per 100k'),
              ('displaced', 'People displaced now', 'people'), ('outage_pct', 'Power and water outage', '% of population')]
    outcome_spec = [('deaths', 'Deaths', 'people'), ('injured', 'Injured', 'people'), ('displaced_peak', 'Displaced at peak', 'people'),
                    ('exposed_mmi7', 'People exposed to damaging shaking (MMI ≥ 7)', 'people'), ('loss_busd', 'Direct economic loss', 'USD billion'),
                    ('loss_pct_gdp', 'Direct loss, share of national GDP', '%'), ('restore_days', 'Days to restore 90% of utilities', 'days'),
                    ('shelter_gap_peak', 'Peak people without shelter', 'people')]
    mechanisms = ['ground shaking', 'building vulnerability', 'casualties and displacement', 'utility outage', 'relief and recovery']
    explain_keys = [('gdp_per_capita_usd', 'GDP per capita $'), ('urban_pct', 'urban %'), ('hospital_beds_per1000', 'hospital beds per 1,000')]
    calibration_note = ('Backtested on six earthquakes (Izmit 1999, Kahramanmaraş 2023, Gorkha 2015, Haiti 2010, Kumamoto 2016, Wenchuan 2008): '
                        'central-run deaths within a factor of 4 of the record for five; Gorkha is overpredicted about 30× (Kathmandu shook less than '
                        'its rupture distance implies). Geometric-mean bias about 1.25×. Expect order-of-magnitude, not exact, tolls. tests/test_backtests.py')

    def priors(self, ctx: Context) -> list[Prior]:
        mag = next((a.value for a in ctx.spec.assumptions if a.id == 'magnitude'), None)
        return [
            Prior('magnitude', 'Moment magnitude' if mag else 'Moment magnitude (not stated; prior)', float(mag or 7.0), float(mag or 6.3), float(mag or 7.8),
                  'Mw', 'user' if mag else 'model', 'high' if mag else 'low'),
            Prior('depth_km', 'Hypocenter depth', 15.0, 8.0, 30.0, 'km', 'model', 'low'),
            Prior('attenuation', 'Intensity decay c with log10 distance (MMI = 1 + 1.5·M − c·log10 R)', 3.0, 2.6, 3.4, '', 'model', 'low',
                  'simplified isoseismal relation, not a regional GMPE'),
            Prior('theta_rich', 'PAGER-style θ for the most resilient building stock (calibrated on six historical events)', 14.4, 13.6, 15.2, 'MMI', 'model', 'low', PAGER),
            Prior('theta_drop', 'Reduction of θ for the most vulnerable stock', 3.5, 2.5, 4.5, 'MMI', 'model', 'low', PAGER),
            Prior('beta', 'PAGER-style β (spread of the fatality curve)', 0.18, 0.14, 0.24, '', 'model', 'low', PAGER),
            Prior('urban_density', 'Urban population density used to size city discs', 6000.0, 3000.0, 12000.0, 'people/km²', 'model', 'low'),
            Prior('rupture_credit', 'Share of half the rupture length credited toward each site (rupture direction unknown)', 0.5, 0.2, 0.8, 'share', 'model', 'low',
                  'Wells & Coppersmith (1994): log10 L = −3.22 + 0.69·Mw'),
            Prior('injury_ratio', 'Injuries per death', 3.5, 2.0, 6.0, '', 'model', 'low'),
            Prior('displacement', 'Displaced share of residents in destroyed housing', 0.6, 0.3, 1.0, 'share', 'model', 'low'),
            Prior('restore_days', 'Utility restoration time constant (resilient grid)', 7.0, 3.0, 15.0, 'days', 'model', 'low'),
            Prior('return_days', 'Time constant for displaced people returning home', 60.0, 30.0, 180.0, 'days', 'model', 'low'),
            Prior('aid_days', 'Time constant for relief shelter capacity', 7.0, 3.0, 21.0, 'days', 'model', 'low'),
            Prior('capital_ratio', 'Building capital per unit of local GDP', 3.0, 2.0, 4.0, '×', 'model', 'low'),
            Prior('report_days', 'Time constant for the reported death toll to converge', 2.0, 1.0, 4.0, 'days', 'model', 'medium'),
        ]

    def simulate(self, ctx: Context, p: dict, rng: np.random.Generator, detail: bool) -> Trajectory:
        T, C = ctx.steps, ctx.C
        o = ctx.spec.origin
        lat0, lon0 = (o.lat, o.lon) if o else (float(ctx.loc_lat[0]), float(ctx.loc_lon[0]))
        d = haversine_km(lat0, lon0, ctx.loc_lat, ctx.loc_lon)
        ex = exposure(ctx, p['urban_density'])  # cities as discs + rural population spread over provinces by area
        de = haversine_km(lat0, lon0, ex['lat'], ex['lon'])
        # finite rupture: Wells & Coppersmith (1994) surface rupture length; direction unknown, so partial credit f
        rupture = 10 ** (-3.22 + 0.69 * p['magnitude'])
        de = np.maximum(de - p['rupture_credit'] * rupture / 2, 0)
        dist = np.sqrt(de[:, None] ** 2 + (ex['radius'][:, None] * RING[None]) ** 2
                       + 2 * de[:, None] * ex['radius'][:, None] * RING[None] * COS[None])
        R = np.sqrt(dist ** 2 + p['depth_km'] ** 2)
        mmi_r = intensity(p['magnitude'], R, p['attenuation'])  # (exposure points, rings)
        as_day = int(rng.integers(1, 10))  # one large aftershock (Båth's law) on an early day
        as_mag = p['magnitude'] - 1.2 + rng.normal(0, 0.2)
        mmi_as_r = np.maximum(intensity(as_mag, R, p['attenuation']), mmi_r)
        vul_e = vulnerability(ctx.gdp_pc)[ex['c']]
        theta = (p['theta_rich'] - p['theta_drop'] * vul_e)[:, None]

        def fatality(m):
            return phi(np.log(np.maximum(m, 1) / theta) / p['beta']).mean(1)

        noise = rng.lognormal(0, 0.15, ctx.L)[ex['loc']]
        rate0 = np.clip(fatality(mmi_r) * noise, 0, 0.5)
        rate_as = np.maximum(fatality(mmi_as_r) - fatality(mmi_r), 0) * 0.3
        agg = lambda v: np.bincount(ex['loc'], weights=v, minlength=ctx.L)
        w = ex['pop']
        deaths_loc = agg(w * rate0)
        deaths_as = agg(w * rate_as)
        damage_e = np.clip((phi(mmi_r - 8.0) * (0.5 + vul_e[:, None])).mean(1), 0, 1)
        displaced_max = agg(w * damage_e) * p['displacement']
        share5 = agg(w * (mmi_r >= 5).mean(1)) / np.maximum(ctx.loc_pop, 1)
        share7 = agg(w * (mmi_r >= 7).mean(1)) / np.maximum(ctx.loc_pop, 1)
        share7_as = agg(w * (mmi_as_r >= 7).mean(1)) / np.maximum(ctx.loc_pop, 1)
        mmi0 = agg(w * mmi_r.mean(1)) / np.maximum(agg(w), 1)  # population-weighted mean intensity per location
        mmi_as = agg(w * mmi_as_r.mean(1)) / np.maximum(agg(w), 1)
        vul = vulnerability(ctx.gdp_pc)[ctx.loc_c]
        outage0 = np.clip(agg(w * phi(mmi_r - 6.5).mean(1)) / np.maximum(ctx.loc_pop, 1) * (0.6 + 0.6 * vul), 0, 1)
        exposed7 = float((w * (mmi_r >= 7).mean(1)).sum())
        damage0 = displaced_max / np.maximum(ctx.loc_pop * p['displacement'], 1)
        tau_out = p['restore_days'] * (1 + 2 * vul)
        g = np.where(np.isfinite(ctx.gdp_pc), ctx.gdp_pc, 5000.0)[ctx.loc_c]
        loss = float((ctx.loc_pop * g * p['capital_ratio'] * damage0 * 0.3).sum())  # damage0: damaged share of each location
        oi = ctx.origin_loc if ctx.origin_loc is not None else 0
        o_c = ctx.loc_c[oi]
        gdp_origin = float(ctx.c_pop[o_c] * g[oi])
        total_deaths = float(deaths_loc.sum() + deaths_as.sum())
        aid_mult = 2.0 if any(iv.kind == 'aid' for iv in ctx.spec.interventions) else 1.0
        key = np.zeros(T + 1)
        metrics, layers, flows, events = [], [], [], []
        p_status = np.zeros((T + 1, ctx.P), np.int8) if detail else None
        p_metric = np.zeros((T + 1, ctx.P), np.float32) if detail else None
        i_status = np.zeros((T + 1, ctx.I), np.int8) if detail else None
        i_metric = np.zeros((T + 1, ctx.I), np.float32) if detail else None
        status = np.zeros(ctx.P, np.int8)
        me = ctx.p_traits[:, TRAITS.index('media_exposure')]
        shelter_gap_peak, disp_peak, restore_day = 0.0, 0.0, float('nan')
        out_total0 = max(float((outage0 * ctx.loc_pop).sum()), 1.0)
        tolls_logged: set[int] = set()
        for t in range(T + 1):
            day = t * ctx.dt
            mmi = np.maximum(mmi0, mmi_as) if day >= as_day else mmi0
            if day == 0:
                reported = deaths_loc.sum() * 0.05
            else:
                reported = deaths_loc.sum() * (1 - math.exp(-day / p['report_days']))
                if day >= as_day:
                    reported += deaths_as.sum() * (1 - math.exp(-(day - as_day + 1) / p['report_days']))
            frac = min(1.0, max(day, 1) / 3) if day < 3 else math.exp(-(day - 3) / p['return_days'])
            disp = displaced_max * frac
            shelter = displaced_max.sum() * (1 - math.exp(-day * aid_mult / p['aid_days']))
            gap = max(0.0, float(disp.sum() - shelter))
            shelter_gap_peak = max(shelter_gap_peak, gap)
            disp_peak = max(disp_peak, float(disp.sum()))
            out_now = outage0 * np.exp(-day / tau_out)
            out_pop = float((out_now * ctx.loc_pop).sum())
            if math.isnan(restore_day) and day > 0 and out_pop <= 0.1 * out_total0:
                restore_day = float(day)
            key[t] = reported
            metrics.append({'deaths_reported': round(float(reported)), 'displaced_now': round(float(disp.sum())), 'without_shelter': round(gap),
                            'without_power_water': round(out_pop)})
            if not detail:
                continue
            if t == 0:
                near = [ctx.loc_name[i] for i in np.argsort(d)[:3]]
                events.append({'t': 0, 'title': f'M{p["magnitude"]:.1f} earthquake near {o.name if o else near[0]}',
                               'cause': f'depth {p["depth_km"]:.0f} km; peak shaking MMI {mmi0.max():.1f}', 'places': near, 'severity': 3})
                hit = np.flatnonzero(mmi0 >= 8)
                if len(hit):
                    events.append({'t': 0, 'title': f'Severe shaking (MMI ≥ 8) in {len(hit)} places',
                                   'cause': f'{ctx.loc_pop[hit].sum() / 1e6:.1f}M people within {d[hit].max():.0f} km', 'places': [ctx.loc_name[i] for i in hit[:5]], 'severity': 3})
            if day == 1:
                events.append({'t': t, 'title': 'International relief mobilizes', 'cause': f'shelter capacity time constant {p["aid_days"] / aid_mult:.0f} days', 'places': [], 'severity': 2})
            if day == as_day:
                events.append({'t': t, 'title': f'M{as_mag:.1f} aftershock', 'cause': BATH, 'places': [], 'severity': 2})
            if day == 3:
                events.append({'t': t, 'title': f'Displacement peaks at {disp.sum() / 1e3:,.0f}k people', 'cause': f'damaged housing; shelter for {shelter / 1e3:,.0f}k so far',
                               'places': [ctx.loc_name[i] for i in np.argsort(-displaced_max)[:3]], 'severity': 3})
            for thr in (100, 1000, 10000, 50000):
                if reported >= thr and thr not in tolls_logged:
                    tolls_logged.add(thr)
                    events.append({'t': t, 'title': f'Death toll passes {thr:,}', 'cause': f'reports converging on {total_deaths:,.0f}', 'places': [], 'severity': 3 if thr >= 1000 else 2})
            if restore_day == day:
                events.append({'t': t, 'title': '90% of power and water restored', 'cause': f'restoration time constant {p["restore_days"]:.0f}-{p["restore_days"] * 3:.0f} days by vulnerability',
                               'places': [], 'severity': 2})
            m = mmi[ctx.p_loc]
            s5, s7 = share5[ctx.p_loc], np.maximum(share7, share7_as if day >= as_day else 0)[ctx.p_loc]
            returned = 1 - disp / np.maximum(displaced_max, 1)
            same_c = ctx.p_c == o_c
            new = np.zeros(ctx.P, np.int8)
            aware = (m >= 3) | ((day >= 1) & ((me >= 0.6) | same_c)) | (day >= 3)
            new[aware] = STATUS['aware']
            new[s5 >= 0.2] = STATUS['reacting']   # a fifth of the segment's location felt strong shaking
            new[s7 >= 0.2] = STATUS['affected']   # a fifth experienced damaging shaking
            status = monotone(new, status)
            status[(status == STATUS['affected']) & (returned[ctx.p_loc] >= 0.7) & (day > 3)] = STATUS['recovered']
            p_status[t] = status
            p_metric[t] = np.round(m, 1)
            for j, inst in enumerate(ctx.institutions):
                s = STATUS['affected'] if (inst.role in ('civil_protection', 'government', 'relief') and day >= 1) else STATUS['reacting']
                if inst.role == 'media':
                    s = STATUS['affected'] if reported >= 1000 else STATUS['reacting']
                i_status[t, j] = max(s, i_status[t - 1, j] if t else 0)
                i_metric[t, j] = reported
            mmi_c = np.zeros(C)
            np.maximum.at(mmi_c, ctx.loc_c, mmi)
            deaths_c = np.bincount(ctx.loc_c, weights=deaths_loc + (deaths_as if day >= as_day else 0), minlength=C) * (reported / max(total_deaths, 1))
            disp_c = np.bincount(ctx.loc_c, weights=disp, minlength=C)
            out_c = np.bincount(ctx.loc_c, weights=out_now * ctx.loc_pop, minlength=C) / np.maximum(ctx.c_pop, 1) * 100
            layers.append({'intensity_mmi': {ctx.iso3[c]: round(float(mmi_c[c]), 1) for c in np.flatnonzero(mmi_c >= 3)},
                           'deaths_per_100k': {ctx.iso3[c]: round(float(deaths_c[c] / ctx.c_pop[c] * 1e5), 2) for c in np.flatnonzero(deaths_c >= 1)},
                           'displaced': {ctx.iso3[c]: round(float(disp_c[c])) for c in np.flatnonzero(disp_c >= 100)},
                           'outage_pct': {ctx.iso3[c]: round(float(out_c[c]), 2) for c in np.flatnonzero(out_c >= 0.01)}})
            fl = []
            if 1 <= day <= 10:
                safe = np.flatnonzero((mmi0 < 6) & (ctx.loc_pop > 2e5) & (d < 1500))
                for s_ in np.argsort(-displaced_max)[:6]:
                    if displaced_max[s_] < 1000 or not len(safe):
                        continue
                    tgt = safe[np.argmin(haversine_km(ctx.loc_lat[s_], ctx.loc_lon[s_], ctx.loc_lat[safe], ctx.loc_lon[safe]))]
                    fl.append({'from': [float(ctx.loc_lon[s_]), float(ctx.loc_lat[s_])], 'to': [float(ctx.loc_lon[tgt]), float(ctx.loc_lat[tgt])],
                               'weight': float(min(1, displaced_max[s_] / 2e5)), 'kind': 'movement'})
            flows.append(fl)
        out = {'deaths': total_deaths, 'injured': total_deaths * p['injury_ratio'], 'displaced_peak': disp_peak, 'exposed_mmi7': exposed7,
               'loss_busd': loss / 1e9, 'loss_pct_gdp': loss / max(gdp_origin, 1) * 100, 'restore_days': restore_day, 'shelter_gap_peak': shelter_gap_peak}
        traj = Trajectory(key=key, metrics=metrics, outcomes=out)
        if detail:
            traj.p_status, traj.p_metric, traj.i_status, traj.i_metric = p_status, p_metric, i_status, i_metric
            traj.layers, traj.flows, traj.events = layers, flows, events
            tot = deaths_loc + deaths_as
            hit = [i for i in np.argsort(-tot)[:10] if tot[i] >= 1]
            traj.breakdown['hardest_hit_places'] = [{'place': ctx.loc_name[i], 'country': ctx.c_name[ctx.loc_c[i]], 'distance_km': round(float(d[i])),
                                                     'mmi': round(float(mmi0[i]), 1), 'deaths': round(float(tot[i])), 'displaced_peak': round(float(displaced_max[i]))} for i in hit]
            traj.breakdown['winners'] = [{'name': 'Construction and reconstruction firms', 'why': f'${loss / 1e9:.1f}B of damaged capital to rebuild', 'detail': 'capital ratio prior'}]
            traj.breakdown['losers'] = [{'name': f'Residents of {ctx.loc_name[i]}', 'why': f'MMI {mmi0[i]:.1f}, {tot[i]:,.0f} deaths', 'detail': f'{d[i]:.0f} km from the epicenter'} for i in hit[:3]] + \
                                       [{'name': 'Insurers and the national budget', 'why': f'direct loss {loss / max(gdp_origin, 1) * 100:.1f}% of GDP',
                                         'detail': 'GDP per capita (World Bank) × capital ratio prior'}]
            traj.causal = {'nodes': [{'id': 'quake', 'label': f'M{p["magnitude"]:.1f} at {p["depth_km"]:.0f} km'},
                                     {'id': 'shaking', 'label': f'{exposed7 / 1e6:.1f}M people at MMI ≥ 7'},
                                     {'id': 'stock', 'label': 'Building vulnerability (GDP per capita)'},
                                     {'id': 'deaths', 'label': f'{total_deaths:,.0f} deaths'}, {'id': 'housing', 'label': f'{disp_peak / 1e3:,.0f}k displaced'},
                                     {'id': 'utilities', 'label': 'Power and water outage'},
                                     {'id': 'aid', 'label': f'Relief shelter (time constant {p["aid_days"] / aid_mult:.0f} days)'},
                                     {'id': 'loss', 'label': f'${loss / 1e9:.1f}B direct loss'}],
                           'edges': [{'from': 'quake', 'to': 'shaking'}, {'from': 'shaking', 'to': 'deaths'}, {'from': 'stock', 'to': 'deaths'},
                                     {'from': 'shaking', 'to': 'housing'}, {'from': 'shaking', 'to': 'utilities'}, {'from': 'housing', 'to': 'aid', 'label': 'needs'},
                                     {'from': 'shaking', 'to': 'loss'}]}
        return traj

    def inst_metric(self, role: str) -> tuple[str, str]:
        return ('deaths reported', 'people')

    def inst_text(self, role: str, v: float) -> str:
        return f'{v:,.0f} deaths reported'

    def counterfactuals(self, ctx: Context) -> list[dict]:
        base = {p.key: p for p in self.priors(ctx)}
        return [{'action': 'Retrofit to resilient-stock standards (θ +1 MMI)', 'trigger': 'seismic code enforcement before the event',
                 'params': {'theta_rich': base['theta_rich'].value + 1.0}},
                {'action': 'Pre-positioned relief (shelter time constant 3 days)', 'trigger': 'stockpiles and agreements in place', 'params': {'aid_days': 3.0}}]
