"""Product / technology launch: Bass diffusion per persona segment, gated by awareness, availability and
affordability, constrained by supply, with a competitor price response and supplier revenue effects.

Data used: GDP per capita and Gini (income distribution → affordability), internet use (addressable share),
World Bank income group (rollout waves), company store (HQ, revenue denominators). Everything else is a prior.
"""
from __future__ import annotations

import datetime as dt

import numpy as np

from .. import T0
from ..geo import EU27
from ..personas import share_above
from .base import STATUS, TRAITS, Context, Module, Prior, Trajectory, behavior, monotone

BASS_SRC = 'Sultan, Farley & Lehmann (1990), meta-analysis of 213 Bass applications: mean p ≈ 0.03, q ≈ 0.38 per year'
ADOPTED_SHARE = 0.03  # status 'adopted' once 3% of the segment's market potential has bought (model threshold)
BUYER = np.array([0.0, 1.0, 1.0, 1.0, 0.4])  # children, workers ×3, seniors (model: share of segment that buys for itself)


def launch_date(ctx: Context) -> str:
    return ctx.spec.start_date


class Launch(Module):
    name = 'launch'
    key_metric = 'units_m'
    key_unit = 'million units shipped'
    persona_metric = ('adoption', '% of segment')
    layers = [('adoption_per_1k', 'Adopters per 1,000 people', 'per 1,000'), ('units_k', 'Units shipped', 'thousand units'),
              ('available', 'On sale', '0/1')]
    outcome_spec = [('units_m', 'Units shipped', 'million units'), ('revenue_busd', 'Revenue', 'USD billion'),
                    ('adopters_per_1k_world', 'Adopters per 1,000 people (world)', 'per 1,000'), ('countries_on_sale', 'Countries on sale', 'countries'),
                    ('peak_backlog_weeks', 'Peak backlog', 'weeks of production'), ('competitor_cut_week', 'Competitor price cut', 'week after start'),
                    ('assembler_revenue_busd', 'Assembler revenue from the device', 'USD billion'),
                    ('foundry_revenue_busd', 'Foundry revenue from the device', 'USD billion'), ('addressable_m', 'Addressable buyers', 'million people')]
    mechanisms = ['media awareness', 'availability waves and regulatory delay', 'income-based affordability', 'Bass contagion',
                  'supply capacity and backlog', 'competitor price response', 'supplier revenue']

    behavior_dims = {'adoption_willingness': 'willingness to buy a new device category once aware'}

    def priors(self, ctx: Context) -> list[Prior]:
        price = next((a.value for a in ctx.spec.assumptions if a.id == 'price_usd'), None)
        return [
            Prior('price_usd', 'Launch price' if price else 'Launch price (not stated in the prompt; premium-device prior)', float(price or 999),
                  float(price or 499), float(price or 1499), 'USD', 'user' if price else 'model', 'high' if price else 'low'),
            Prior('bass_p', 'Bass innovation coefficient p (per year)', 0.03, 0.01, 0.05, '/yr', 'model', 'medium', BASS_SRC),
            Prior('bass_q', 'Bass imitation coefficient q (per year); below the 0.38 mean for a new device category', 0.30, 0.15, 0.50, '/yr', 'model', 'medium', BASS_SRC),
            Prior('market_ceiling', 'Long-run share of the addressable market that ever buys', 0.25, 0.10, 0.40, 'share', 'model', 'low'),
            Prior('spend_share', 'Highest share of annual income a buyer spends on the device', 0.02, 0.01, 0.04, 'share of income', 'model', 'low'),
            Prior('ecosystem_share', 'Share of internet users inside the maker\'s ecosystem (install-base data not yet ingested)', 0.30, 0.20, 0.40, 'share', 'model', 'low'),
            Prior('awareness_rate', 'Weekly media reach of launch coverage', 0.6, 0.3, 0.9, '/week', 'model', 'low'),
            Prior('capacity_initial_k', 'Initial weekly production capacity', 100, 50, 200, 'thousand/week', 'model', 'low'),
            Prior('capacity_max_k', 'Peak weekly production capacity', 400, 200, 800, 'thousand/week', 'model', 'low'),
            Prior('ramp_weeks', 'Weeks to reach peak capacity', 16, 8, 24, 'weeks', 'model', 'low'),
            Prior('wave2_weeks', 'Delay for upper-middle-income markets', 8, 4, 16, 'weeks', 'model', 'low'),
            Prior('wave3_weeks', 'Delay for lower-income markets', 24, 12, 40, 'weeks', 'model', 'low'),
            Prior('china_delay_weeks', 'Extra regulatory delay in China', 8, 0, 20, 'weeks', 'model', 'low'),
            Prior('eu_delay_weeks', 'Extra regulatory delay in the EU', 4, 0, 12, 'weeks', 'model', 'low'),
            Prior('competitor_trigger_m', 'Cumulative units that trigger a competitor price cut', 2, 1, 4, 'million units', 'model', 'low'),
            Prior('competitor_cut', 'Size of the competitor price cut', 0.25, 0.15, 0.35, 'share', 'model', 'low'),
            Prior('competitor_effect', 'Drop in adoption hazard for price-sensitive buyers after the cut', 0.30, 0.10, 0.50, 'share', 'model', 'low'),
            Prior('bom_assembly', 'Final-assembly share of the device price (to the assembler)', 0.04, 0.02, 0.06, 'share', 'model', 'low'),
            Prior('bom_chips', 'Foundry chip share of the device price', 0.10, 0.06, 0.15, 'share', 'model', 'low'),
        ]

    # --- static per-scenario arrays -------------------------------------------------------------------------
    def _static(self, ctx: Context, p: dict):
        w = ctx.world
        internet = ctx.ind('internet_users_pct') / 100
        internet_missing = ~np.isfinite(internet)
        internet = np.where(internet_missing, 0.5, internet)
        gdp = ctx.gdp_pc
        afford = np.zeros(ctx.P)
        threshold = p['price_usd'] / p['spend_share']
        for k, pr in enumerate(ctx.pop.people):
            g = gdp[ctx.p_c[k]]
            if not np.isfinite(g) or pr.sigma is None:
                continue
            p1, p2 = pr.income_p if pr.segment.startswith('workers') else (0.0, 1.0)
            afford[k] = share_above(g, pr.sigma, threshold, p1, p2)
        addressable = ctx.p_pop * BUYER[ctx.p_seg] * internet[ctx.p_c] * p['ecosystem_share'] * afford
        # availability week by country
        groups = [w.countries[c].income_group if c in w.countries else None for c in ctx.iso3]
        avail = np.array([0.0 if g == 'High income' else p['wave2_weeks'] if g == 'Upper middle income' else p['wave3_weeks'] for g in groups])
        for c in EU27:
            if c in ctx.c_idx:
                avail[ctx.c_idx[c]] += p['eu_delay_weeks']
        if 'CHN' in ctx.c_idx:
            avail[ctx.c_idx['CHN']] = max(avail[ctx.c_idx['CHN']], p['wave2_weeks']) + p['china_delay_weeks']
        return addressable, afford, avail, internet_missing, groups

    def simulate(self, ctx: Context, p: dict, rng: np.random.Generator, detail: bool) -> Trajectory:
        T, dt_w = ctx.steps, ctx.dt / 7
        addressable, afford, avail_w, internet_missing, groups = self._static(ctx, p)
        m = addressable * p['market_ceiling']
        launch_t = int(round(self.lead_weeks(ctx) / dt_w))
        preorder_t = max(0, launch_t - 2)
        avail_t = launch_t + np.round(avail_w / dt_w).astype(int)
        open_t = np.where(avail_t == launch_t, preorder_t, avail_t)
        me = ctx.p_traits[:, TRAITS.index('media_exposure')]
        ps = ctx.p_traits[:, TRAITS.index('price_sensitivity')]
        A = np.zeros(ctx.P)
        N = np.zeros(ctx.P)        # delivered units (adopters)
        B = np.zeros(ctx.P)        # backlog (ordered, not delivered)
        cut_t = None
        noise_q = p['bass_q'] * rng.lognormal(0, 0.1, ctx.C)  # country-level contagion noise
        adopt_m = behavior(ctx, p, 'adoption_willingness')[ctx.p_c]  # crowd stances; 1 without
        m_c = np.bincount(ctx.p_c, weights=m, minlength=ctx.C)
        key = np.zeros(T + 1)
        metrics, layers, flows, events = [], [], [], []
        p_status = np.zeros((T + 1, ctx.P), np.int8) if detail else None
        p_metric = np.zeros((T + 1, ctx.P), np.float32) if detail else None
        i_status = np.zeros((T + 1, ctx.I), np.int8) if detail else None
        i_metric = np.zeros((T + 1, ctx.I), np.float32) if detail else None
        status = np.zeros(ctx.P, np.int8)
        backlog_weeks_peak = 0.0
        milestones = set()
        shipped_by_c = np.zeros(ctx.C)
        prev_avail_n = 0
        for t in range(T + 1):
            week = t * dt_w
            # awareness grows from announcement (t=0)
            reach = 1 - np.exp(-p['awareness_rate'] * (0.3 + me) * dt_w)
            if t > 0:
                A = A + (1 - A) * reach
            open_c = t >= open_t  # orders accepted (pre-orders in wave 1)
            selling = (t >= avail_t)
            orders = np.zeros(ctx.P)
            if t > 0:
                F_c = np.bincount(ctx.p_c, weights=N + B, minlength=ctx.C) / np.maximum(m_c, 1)
                h = np.minimum((1 - np.exp(-(p['bass_p'] + noise_q[ctx.p_c] * F_c[ctx.p_c]) * (dt_w / 52))) * adopt_m, 1.0)
                if cut_t is not None:
                    h = np.where(ps > 0.5, h * (1 - p['competitor_effect']), h)
                orders = np.maximum(m - N - B, 0) * h * A * open_c[ctx.p_c]
            # supply
            weeks_since = max(0.0, week - launch_t * dt_w)
            ramp = min(1.0, weeks_since / p['ramp_weeks'])
            cap = (p['capacity_initial_k'] + (p['capacity_max_k'] - p['capacity_initial_k']) * ramp) * 1000 * dt_w if t >= launch_t else 0.0
            B = B + orders
            deliverable = B * selling[ctx.p_c]
            total_deliverable = deliverable.sum()
            ship_frac = min(1.0, cap / total_deliverable) if total_deliverable > 0 else 0.0
            shipped = deliverable * ship_frac
            B -= shipped
            N += shipped
            shipped_c = np.bincount(ctx.p_c, weights=shipped, minlength=ctx.C)
            shipped_by_c += shipped_c
            units = N.sum()
            backlog = B.sum()
            backlog_weeks = backlog / (cap / dt_w) if cap > 0 else 0.0
            backlog_weeks_peak = max(backlog_weeks_peak, backlog_weeks)
            if cut_t is None and units >= p['competitor_trigger_m'] * 1e6:
                cut_t = t
                events.append({'t': t, 'title': f'Competitor cuts its headset price {p["competitor_cut"] * 100:.0f}%',
                               'cause': f'{units / 1e6:.1f}M units shipped crossed the {p["competitor_trigger_m"]:.1f}M trigger', 'places': [], 'severity': 3})
            key[t] = units / 1e6
            n_avail = int(selling.sum())
            metrics.append({'units_m': round(units / 1e6, 3), 'backlog_m': round(backlog / 1e6, 3), 'revenue_busd': round(units * p['price_usd'] / 1e9, 3),
                            'aware_pop': float((A * ctx.p_pop).sum()), 'countries_on_sale': n_avail,
                            'adopters_per_1k_world': round(units / ctx.p_pop.sum() * 1000, 4), 'capacity_k_week': round(cap / dt_w / 1000, 1)})
            if detail:
                # events
                if t == preorder_t and preorder_t < launch_t:
                    events.append({'t': t, 'title': 'Pre-orders open', 'cause': 'two weeks before launch in wave-1 markets', 'places': [], 'severity': 2})
                if t == launch_t:
                    events.append({'t': t, 'title': f'Launch: on sale in {n_avail} countries', 'cause': 'wave 1: World Bank high-income markets outside the EU',
                                   'places': [], 'severity': 3})
                if n_avail > prev_avail_n and t > launch_t:
                    newly_c = np.flatnonzero((avail_t == t) & (ctx.c_pop > 1e5))
                    newly = [ctx.c_name[c] for c in newly_c[np.argsort(-ctx.c_pop[newly_c])]][:6]
                    if newly:
                        events.append({'t': t, 'title': f'On sale in {", ".join(newly)}{f" and {len(newly_c) - 6} more" if len(newly_c) > 6 else ""}',
                                       'cause': 'rollout wave or regulatory clearance', 'places': newly, 'severity': 2 if 'China' in newly or len(newly) > 3 else 1})
                prev_avail_n = n_avail
                for thr in (1, 5, 10, 25):
                    if units >= thr * 1e6 and thr not in milestones:
                        milestones.add(thr)
                        events.append({'t': t, 'title': f'{thr}M units shipped', 'cause': f'capacity {cap / dt_w / 1000:.0f}k/week, backlog {backlog / 1e6:.2f}M',
                                       'places': [], 'severity': 3 if thr in (1, 10) else 2})
                if backlog_weeks >= 4 and 'backlog' not in milestones:
                    milestones.add('backlog')
                    events.append({'t': t, 'title': f'Backlog reaches {backlog_weeks:.0f} weeks of production', 'cause': f'orders outpace capacity ({cap / dt_w / 1000:.0f}k/week)',
                                   'places': [], 'severity': 2})
                # persona states
                share = N / np.maximum(ctx.p_pop, 1)
                new = np.zeros(ctx.P, np.int8)
                new[A >= 0.3] = STATUS['aware']
                considering = (A >= 0.3) & open_c[ctx.p_c] & (m > 0)
                new[considering] = STATUS['reacting']
                priced_out = (A >= 0.3) & (afford < 0.02) & (ps >= 0.6) & (BUYER[ctx.p_seg] > 0)
                new[priced_out] = STATUS['opposed']
                took_off = (N / np.maximum(m, 1) >= ADOPTED_SHARE) & (m > 0)  # takeoff among the segment's likely buyers
                new[took_off] = STATUS['adopted']
                keep = (status == STATUS['adopted'])
                status = np.where(keep, status, np.where(status == STATUS['opposed'], np.where(took_off, STATUS['adopted'], status), monotone(new, status))).astype(np.int8)
                p_status[t] = status
                p_metric[t] = np.round(share * 100, 3)
                # institutions
                for j, inst in enumerate(ctx.institutions):
                    s = STATUS['aware']
                    if t >= preorder_t:
                        s = STATUS['reacting']
                    if inst.role == 'maker' and units >= 1e6:
                        s = STATUS['affected']
                    if inst.role == 'competitor' and cut_t is not None:
                        s = STATUS['affected']
                    if inst.role in ('assembler', 'foundry') and t >= launch_t and ramp >= 0.5:
                        s = STATUS['affected']
                    if inst.role == 'retailer' and t >= launch_t:
                        s = STATUS['affected']
                    if inst.role == 'regulator' and t >= launch_t:
                        s = STATUS['affected']
                    i_status[t, j] = max(s, i_status[t - 1, j] if t else 0)
                    i_metric[t, j] = {'maker': units / 1e6, 'competitor': units / 1e6, 'assembler': ramp * 100, 'foundry': ramp * 100}.get(inst.role, units / 1e6)
                # layers & flows
                adopters_c = np.bincount(ctx.p_c, weights=N, minlength=ctx.C)
                per1k = adopters_c / np.maximum(ctx.c_pop, 1) * 1000
                layers.append({'adoption_per_1k': {ctx.iso3[c]: round(float(per1k[c]), 3) for c in np.flatnonzero(per1k > 0.0005)},
                               'units_k': {ctx.iso3[c]: round(float(adopters_c[c] / 1000), 1) for c in np.flatnonzero(adopters_c > 50)},
                               'available': {ctx.iso3[c]: 1.0 for c in np.flatnonzero(selling)}})
                fl = []
                src = self.factory(ctx)
                if src is not None and shipped.sum() > 0:
                    for c in np.argsort(-shipped_c)[:12]:
                        if shipped_c[c] <= 0:
                            break
                        h = ctx.c_hub[c]
                        fl.append({'from': src, 'to': [float(ctx.loc_lon[h]), float(ctx.loc_lat[h])], 'weight': float(min(1.0, shipped_c[c] / max(shipped_c.max(), 1))), 'kind': 'trade'})
                flows.append(fl)

        units = N.sum()
        revenue = units * p['price_usd']
        out = {'units_m': units / 1e6, 'revenue_busd': revenue / 1e9, 'adopters_per_1k_world': units / ctx.p_pop.sum() * 1000,
               'countries_on_sale': float((avail_t <= T).sum()), 'peak_backlog_weeks': backlog_weeks_peak,
               'competitor_cut_week': float(cut_t * dt_w) if cut_t is not None else float('nan'),
               'assembler_revenue_busd': revenue * p['bom_assembly'] / 1e9, 'foundry_revenue_busd': revenue * p['bom_chips'] / 1e9,
               'addressable_m': float(addressable.sum() / 1e6)}
        traj = Trajectory(key=key, metrics=metrics, outcomes=out, affected_loc=np.bincount(ctx.p_loc, weights=N, minlength=ctx.L))  # adopters
        if detail:
            traj.p_status, traj.p_metric, traj.i_status, traj.i_metric = p_status, p_metric, i_status, i_metric
            traj.layers, traj.flows, traj.events = layers, flows, events
            adopters_c = np.bincount(ctx.p_c, weights=N, minlength=ctx.C)
            per1k = adopters_c / np.maximum(ctx.c_pop, 1) * 1000
            top = np.argsort(-adopters_c)[:10]
            traj.breakdown['top_countries'] = [{'country': ctx.c_name[c], 'iso3': ctx.iso3[c], 'units_k': round(adopters_c[c] / 1000, 1),
                                                'per_1k': round(per1k[c], 2), 'on_sale_week': round(float(avail_t[c] * dt_w), 1)} for c in top if adopters_c[c] > 0]
            seg_units = np.bincount(ctx.p_seg, weights=N, minlength=5)
            names = ['Households with children', 'Lower-income workers', 'Middle-income workers', 'Higher-income professionals', 'Adults 65+']
            traj.breakdown['segments'] = [{'segment': names[s], 'units_k': round(seg_units[s] / 1000, 1),
                                           'share_pct': round(seg_units[s] / max(units, 1) * 100, 1)} for s in range(5) if seg_units[s] > 0]
            priced = np.bincount(ctx.p_c, weights=ctx.p_pop * (afford < 0.02) * (BUYER[ctx.p_seg] > 0), minlength=ctx.C)
            traj.breakdown['priced_out'] = [{'country': ctx.c_name[c], 'people_m': round(priced[c] / 1e6, 1)} for c in np.argsort(-priced)[:5]]
            traj.causal = {
                'nodes': [
                    {'id': 'price', 'label': f'Price ${p["price_usd"]:,.0f}'},
                    {'id': 'income', 'label': 'Income distribution (GDP per capita, Gini)'},
                    {'id': 'afford', 'label': f'Affordable to {addressable.sum() / 1e6:,.0f}M addressable buyers'},
                    {'id': 'aware', 'label': 'Media awareness'},
                    {'id': 'avail', 'label': f'On sale in {int((avail_t <= T).sum())} countries'},
                    {'id': 'bass', 'label': 'Word of mouth (Bass q)'},
                    {'id': 'supply', 'label': f'Capacity up to {p["capacity_max_k"]:.0f}k/week; peak backlog {backlog_weeks_peak:.1f} weeks'},
                    {'id': 'units', 'label': f'{units / 1e6:.1f}M units, ${revenue / 1e9:.1f}B'},
                    {'id': 'competitor', 'label': 'Competitor price cut' + (f' (week {cut_t * dt_w:.0f})' if cut_t is not None else ' (not triggered)')},
                    {'id': 'suppliers', 'label': f'Assembler +${revenue * p["bom_assembly"] / 1e9:.2f}B, foundry +${revenue * p["bom_chips"] / 1e9:.2f}B'},
                ],
                'edges': [{'from': 'price', 'to': 'afford'}, {'from': 'income', 'to': 'afford'}, {'from': 'afford', 'to': 'units'},
                          {'from': 'aware', 'to': 'units'}, {'from': 'avail', 'to': 'units'}, {'from': 'bass', 'to': 'units'},
                          {'from': 'supply', 'to': 'units', 'label': 'caps'}, {'from': 'units', 'to': 'competitor', 'label': 'triggers'},
                          {'from': 'competitor', 'to': 'bass', 'label': 'slows'}, {'from': 'units', 'to': 'suppliers'}],
            }
        return traj

    explain_keys = [('gdp_per_capita_usd', 'GDP per capita $'), ('gini', 'Gini'), ('internet_users_pct', 'internet use %')]

    def inst_metric(self, role: str) -> tuple[str, str]:
        return ('capacity ramp', '% of peak') if role in ('assembler', 'foundry') else ('units shipped', 'million units')

    def inst_text(self, role: str, v: float) -> str:
        return f'{v:.0f}%' if role in ('assembler', 'foundry') else f'{v:.2f}M units'

    def counterfactuals(self, ctx: Context) -> list[dict]:
        base = {p.key: p for p in self.priors(ctx)}
        price = base['price_usd'].value
        return [{'action': f'Launch at ${price * 0.8:,.0f} (20% lower)', 'trigger': 'pricing decision before launch', 'params': {'price_usd': price * 0.8}},
                {'action': f'Secure peak capacity of {base["capacity_max_k"].high:.0f}k units/week', 'trigger': 'supplier contracts signed before launch',
                 'params': {'capacity_max_k': base['capacity_max_k'].high}},
                {'action': 'Clear EU and China reviews at launch', 'trigger': 'regulatory filings complete before launch',
                 'params': {'eu_delay_weeks': 0.0, 'china_delay_weeks': 0.0}}]

    def lead_weeks(self, ctx: Context) -> float:
        """Weeks between simulation start and the launch date (announcement window)."""
        return getattr(ctx, 'launch_lead_weeks', 0.0)

    def factory(self, ctx: Context):
        site = next((i for i in ctx.institutions if i.role == 'assembler'), None)
        return [site.lon, site.lat] if site else None

    @staticmethod
    def prepare(spec) -> tuple[str, float]:
        """Start the run up to six weeks before launch (never before t0) so pre-launch awareness is simulated."""
        ld = next((a.value for a in spec.assumptions if a.id == 'launch_date'), spec.start_date)
        launch = dt.date.fromisoformat(str(ld))
        start = max(dt.date.fromisoformat(T0), launch - dt.timedelta(days=42))
        return start.isoformat(), (launch - start).days / 7
