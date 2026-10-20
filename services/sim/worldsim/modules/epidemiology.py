"""Epidemiology: stochastic age-structured SEIRD metapopulation over every location.

Coupling: local mixing, within-country gravity mixing, international seeding through a gravity travel network.
Data used: population and age shares, hospital beds and physicians per 1,000 (World Bank), income group (vaccine
access). Natural-history and severity parameters are priors drawn from analog ranges and carried into the ensemble.
"""
from __future__ import annotations

import numpy as np

from .base import STATUS, TRAITS, Context, Module, Prior, Trajectory, monotone

R0_SRC = 'Biggerstaff et al. (2014), systematic review of influenza reproduction numbers: pandemic medians ~1.5-1.8; 1918 up to ~2-3'
FLU_SRC = 'Influenza natural history: latent ~1-2 days, infectious ~4-6 days (CDC, WHO pandemic planning assumptions)'
# Stylized POLYMOD-shaped contact matrix between age groups 0-14, 15-64, 65+ (model)
CONTACT = np.array([[7.0, 5.0, 1.0], [5.0, 10.0, 2.0], [1.0, 2.0, 3.0]])
IFR_BASE = np.array([0.0003, 0.002, 0.02])   # by age, before the severity multiplier (model prior shape)
AGE_DEFAULT = np.array([0.25, 0.66, 0.09])


class Epidemiology(Module):
    name = 'epidemiology'
    key_metric = 'deaths'
    key_unit = 'deaths'
    persona_metric = ('reported cases', 'per 100k (reported)')
    layers = [('cases_per_100k', 'Reported cases per 100k', 'per 100k'), ('deaths_per_100k', 'Deaths per 100k', 'per 100k'),
              ('hospital_load_pct', 'Hospital demand vs surge beds', '%'), ('activity_drop_pct', 'Drop in contacts (behavior and policy)', '%')]
    outcome_spec = [('deaths', 'Deaths', 'people'), ('infections', 'Infections (true)', 'people'), ('reported', 'Reported cases', 'people'),
                    ('countries', 'Countries with community transmission', 'countries'), ('overloaded', 'Countries with hospitals over surge capacity', 'countries'),
                    ('days_to_10', 'Days until 10 countries have transmission', 'days'), ('peak_day', 'Global peak of active infections', 'day')]
    mechanisms = ['human-to-human transmission', 'air-travel seeding', 'health-system capacity', 'behavioral response', 'reporting lag']
    explain_keys = [('hospital_beds_per1000', 'hospital beds per 1,000'), ('physicians_per1000', 'physicians per 1,000'), ('age_65_plus_pct', 'aged 65+ %'),
                    ('urban_pct', 'urban %')]

    def priors(self, ctx: Context) -> list[Prior]:
        return [
            Prior('r0', 'Basic reproduction number R0', 1.9, 1.4, 2.8, '', 'model', 'low', R0_SRC),
            Prior('latent_days', 'Latent period', 2.0, 1.0, 4.0, 'days', 'model', 'medium', FLU_SRC),
            Prior('infectious_days', 'Infectious period', 5.0, 3.0, 7.0, 'days', 'model', 'medium', FLU_SRC),
            Prior('severity', 'Severity multiplier on the age-specific fatality curve (0.03% / 0.2% / 2%)', 1.0, 0.2, 5.0, '×', 'model', 'low',
                  'No human-transmissible H5N1 exists to calibrate against; range spans 2009 H1N1 to 1918-like severity'),
            Prior('hosp_per_death', 'Hospitalizations per death', 8.0, 5.0, 15.0, '', 'model', 'low'),
            Prior('surge_bed_share', 'Share of hospital beds available for surge', 0.25, 0.1, 0.4, 'share', 'model', 'low'),
            Prior('overflow_mult', 'Fatality multiplier for patients beyond surge capacity', 2.0, 1.5, 3.0, '×', 'model', 'low'),
            Prior('travel_rate', 'Daily outbound international travel share (at $10k GDP per capita)', 2e-4, 1e-4, 4e-4, '/day', 'model', 'low',
                  'Gravity model on population, GDP and distance; flight data (OpenFlights) not yet ingested'),
            Prior('domestic_mixing', 'Share of contacts with other locations in the same country', 0.08, 0.03, 0.15, 'share', 'model', 'low'),
            Prior('behavior_max', 'Largest voluntary drop in contacts once deaths become visible', 0.4, 0.2, 0.6, 'share', 'model', 'low',
                  'COVID-19 mobility analogs (Google Community Mobility Reports, 2020): 20-60% drops'),
            Prior('ascertainment', 'Share of infections reported (at 2 physicians per 1,000)', 0.15, 0.05, 0.35, 'share', 'model', 'low'),
            Prior('report_lag', 'Reporting lag', 5.0, 3.0, 10.0, 'days', 'model', 'medium'),
            Prior('seed', 'Initial infections in the rural cluster', 20.0, 5.0, 100.0, 'people', 'model', 'low'),
            Prior('vaccine_day', 'Day vaccination begins in high-income countries', 200.0, 120.0, 300.0, 'day', 'model', 'low',
                  '2009 H1N1 analog: first doses ~6 months after detection'),
            Prior('vaccine_rate', 'Daily vaccination rate in high-income countries', 0.005, 0.002, 0.01, 'share/day', 'model', 'low'),
        ]

    def _static(self, ctx: Context):
        age = np.stack([ctx.ind('age_0_14_pct'), 100 - ctx.ind('age_0_14_pct') - ctx.ind('age_65_plus_pct'), ctx.ind('age_65_plus_pct')], 1) / 100
        age = np.where(np.isfinite(age).all(1, keepdims=True), age, AGE_DEFAULT)
        N = ctx.loc_pop[:, None] * age[ctx.loc_c]
        beds = ctx.ind('hospital_beds_per1000')
        beds_missing = ~np.isfinite(beds)
        beds = np.where(beds_missing, np.nanmedian(beds) if np.isfinite(beds).any() else 2.5, beds)
        phys = ctx.ind('physicians_per1000')
        phys = np.where(np.isfinite(phys), phys, np.nanmedian(phys) if np.isfinite(phys).any() else 1.5)
        # within-country gravity mixing matrix (rows sum to 1 inside each country)
        G = np.zeros((ctx.L, ctx.L))
        for c in range(ctx.C):
            idx = np.flatnonzero(ctx.loc_c == c)
            if len(idx) < 2:
                G[idx, idx] = 1.0
                continue
            la, lo = ctx.loc_lat[idx], ctx.loc_lon[idx]
            d = np.sqrt(((la[:, None] - la[None]) * 111) ** 2 + ((lo[:, None] - lo[None]) * 111 * np.cos(np.radians(la[:, None]))) ** 2)
            w = ctx.loc_pop[idx][None] / np.maximum(d, 15) ** 2
            np.fill_diagonal(w, 0)
            w /= w.sum(1, keepdims=True)
            G[np.ix_(idx, idx)] = w
        # spectral radius of the next-generation shape per country, to calibrate β to R0
        rho = np.array([np.max(np.abs(np.linalg.eigvals(CONTACT * age[c][None, :]))) for c in range(ctx.C)])
        hic = np.array([ctx.world.countries[c].income_group == 'High income' if c in ctx.world.countries else False for c in ctx.iso3])
        return age, N, beds, beds_missing, phys, G, rho, hic

    def simulate(self, ctx: Context, p: dict, rng: np.random.Generator, detail: bool) -> Trajectory:
        age, N, beds, beds_missing, phys, G, rho, hic = getattr(ctx, '_epi_static', None) or self._static(ctx)
        ctx._epi_static = (age, N, beds, beds_missing, phys, G, rho, hic)
        L, C, T = ctx.L, ctx.C, ctx.steps
        Ni = np.maximum(N.round().astype(np.int64), 0)
        S = Ni.copy()
        E = np.zeros_like(S)
        I = np.zeros_like(S)
        R = np.zeros_like(S)
        D = np.zeros_like(S)
        V = np.zeros_like(S)
        cum = np.zeros_like(S)
        # seed: the origin country's rural remainder if present (a rural cluster), else the origin location
        o = ctx.origin_loc if ctx.origin_loc is not None else int(np.argmax(ctx.loc_pop))
        rural = np.flatnonzero((ctx.loc_c == ctx.loc_c[o]) & ~ctx.loc_urban)
        seed_loc = int(rural[0]) if len(rural) else o
        E[seed_loc, 1] = int(p['seed'])
        S[seed_loc, 1] -= int(p['seed'])
        sigma, gamma = 1 / p['latent_days'], 1 / p['infectious_days']
        beta_c = p['r0'] * gamma / rho
        ifr = np.minimum(IFR_BASE * p['severity'], 0.5)
        asc = np.clip(p['ascertainment'] * np.sqrt(phys / 2.0), 0.02, 0.6)
        surge_beds = beds / 1000 * ctx.c_pop * p['surge_bed_share']
        Tm = ctx.travel_matrix(p['travel_rate'])
        ivs = ctx.spec.interventions
        lag = int(round(p['report_lag']))
        inf_hist = []  # daily new infections by country (for lagged reporting)
        reported_c = np.zeros(C)
        key = np.zeros(T + 1)
        metrics, layers, flows, events = [], [], [], []
        p_status = np.zeros((T + 1, ctx.P), np.int8) if detail else None
        p_metric = np.zeros((T + 1, ctx.P), np.float32) if detail else None
        i_status = np.zeros((T + 1, ctx.I), np.int8) if detail else None
        i_metric = np.zeros((T + 1, ctx.I), np.float32) if detail else None
        status = np.zeros(ctx.P, np.int8)
        reached = np.zeros(C, bool)
        over_any = np.zeros(C, bool)
        detected_t = None
        days_to_10 = np.nan
        active_series = []
        me = ctx.p_traits[:, TRAITS.index('media_exposure')]
        trust = ctx.p_traits[:, TRAITS.index('institutional_trust')]
        loc_rep = np.zeros(L)
        prev_prev = np.zeros(L)
        vacc_started = False
        border_on, lock_c = False, np.zeros(C, bool)
        milestones = set()
        for t in range(T + 1):
            if t > 0:
                for iv in ivs:
                    if iv.day == t:
                        cs = [ctx.c_idx[c] for c in iv.countries if c in ctx.c_idx] or list(range(C))
                        if iv.kind == 'border_closure':
                            border_on = True
                        elif iv.kind == 'lockdown':
                            lock_c[cs] = True
                        if detail:
                            events.append({'t': t, 'title': f'Intervention: {iv.kind.replace("_", " ")}', 'cause': iv.text[:120], 'places': [], 'severity': 3})
                # behavior: contacts fall as deaths become visible (country level)
                dc = np.bincount(ctx.loc_c, weights=D.sum(1), minlength=C) / np.maximum(ctx.c_pop, 1) * 1e5
                drop = p['behavior_max'] * (1 - np.exp(-dc / 5.0))
                drop = np.where(lock_c, np.maximum(drop, 0.5), drop)
                beta_eff = beta_c * (1 - drop)
                prev = I / np.maximum(Ni, 1)
                mixed = (1 - p['domestic_mixing']) * prev + p['domestic_mixing'] * (G @ prev)
                # mixing M_ab = c_ab · share_b (contacts scale with the availability of age group b), matching rho below
                lam = beta_eff[ctx.loc_c, None] * ((mixed * age[ctx.loc_c]) @ CONTACT.T)
                p_inf = 1 - np.exp(-lam)
                new_E = rng.binomial(S, np.clip(p_inf, 0, 1))
                new_I = rng.binomial(E, 1 - np.exp(-sigma))
                out_I = rng.binomial(I, 1 - np.exp(-gamma))
                # deaths among resolving infections, with overflow beyond surge beds
                inf_c = np.bincount(ctx.loc_c, weights=I.sum(1), minlength=C)
                demand = inf_c * (ifr @ AGE_DEFAULT) * p['hosp_per_death'] * gamma * p['infectious_days']
                load = demand / np.maximum(surge_beds, 1)
                over = np.clip(1 - 1 / np.maximum(load, 1e-9), 0, 1)  # share of hospital demand beyond capacity
                ifr_loc = ifr[None, :] * (1 + (p['overflow_mult'] - 1) * over[ctx.loc_c, None])
                new_D = rng.binomial(out_I, np.clip(ifr_loc, 0, 1))
                S -= new_E
                E += new_E - new_I
                I += new_I - out_I
                R += out_I - new_D
                D += new_D
                cum += new_E
                # international importations to each country's hub
                inf_frac_c = inf_c / np.maximum(ctx.c_pop, 1)
                travel = Tm * (0.1 if border_on else 1.0)
                lam_import = inf_frac_c @ travel * ctx.c_pop  # expected infectious arrivals per country
                arrivals = rng.poisson(lam_import * (1 - drop))
                hubs = ctx.c_hub
                take = np.minimum(arrivals, S[hubs, 1])
                S[hubs, 1] -= take
                E[hubs, 1] += take
                cum[hubs, 1] += take
                # vaccination
                vday = p['vaccine_day']
                for iv in ivs:
                    if iv.kind == 'vaccine':
                        vday = min(vday, iv.day)
                if t >= vday:
                    if not vacc_started and detail:
                        events.append({'t': t, 'title': 'Vaccination begins in high-income countries', 'cause': f'vaccine available on day {int(vday)}', 'places': [], 'severity': 3})
                    vacc_started = True
                    rate = np.where(hic, p['vaccine_rate'], p['vaccine_rate'] * 0.3 if t >= vday + 60 else 0.0)
                    vac = rng.binomial(S, np.clip(rate[ctx.loc_c, None] * 0.7, 0, 1))
                    S -= vac
                    V += vac
                inf_hist.append(np.bincount(ctx.loc_c, weights=new_E.sum(1), minlength=C))
                if len(inf_hist) > lag:
                    reported_c += inf_hist[-lag - 1] * asc
                if detail:
                    loc_new = new_E.sum(1)
                    loc_rep += loc_new * asc[ctx.loc_c]
                    fl = []
                    for c in np.argsort(-arrivals)[:15]:
                        if arrivals[c] <= 0:
                            break
                        src = int(np.argmax(inf_frac_c * travel[:, c]))
                        fl.append({'from': [float(ctx.loc_lon[hubs[src]]), float(ctx.loc_lat[hubs[src]])], 'to': [float(ctx.loc_lon[hubs[c]]), float(ctx.loc_lat[hubs[c]])],
                                   'weight': float(min(1, arrivals[c] / 20)), 'kind': 'spread'})
                    flows.append(fl)
            elif detail:
                flows.append([])
                drop = np.zeros(C)
                load = np.zeros(C)
            if t == 0:
                drop, load = np.zeros(C), np.zeros(C)
            cum_c = np.bincount(ctx.loc_c, weights=cum.sum(1), minlength=C)
            newly = (~reached) & (cum_c >= 100)
            reached |= cum_c >= 100
            if np.isnan(days_to_10) and reached.sum() >= 10:
                days_to_10 = float(t * ctx.dt)
            over_any |= load > 1
            total_D, total_cum, total_rep = D.sum(), cum.sum(), reported_c.sum()
            active = I.sum()
            active_series.append(active)
            key[t] = total_D
            metrics.append({'deaths_k': round(total_D / 1000, 3), 'infections_m': round(total_cum / 1e6, 4), 'reported_m': round(total_rep / 1e6, 4),
                            'active_infections_m': round(active / 1e6, 4), 'countries': int(reached.sum()), 'overloaded_now': int((load > 1).sum()),
                            'vaccinated_m': round(V.sum() / 1e6, 3)})
            if detail:
                if detected_t is None and total_rep >= 5:
                    detected_t = t
                    events.append({'t': t, 'title': f'Human-to-human cluster confirmed in {ctx.c_name[ctx.loc_c[seed_loc]]}', 'cause': f'{total_rep:.0f} reported cases after a {lag}-day reporting lag',
                                   'places': [ctx.loc_name[seed_loc]], 'severity': 3})
                for c in np.flatnonzero(newly):
                    n = int(reached.sum())
                    if n <= 12 or n in (25, 50, 100, 150):
                        events.append({'t': t, 'title': f'Community transmission in {ctx.c_name[c]}' + (f' ({n} countries)' if n >= 25 else ''),
                                       'cause': 'imported infections via the travel network' if c != ctx.loc_c[seed_loc] else 'local chains from the seed cluster',
                                       'places': [ctx.c_name[c]], 'severity': 3 if n <= 3 or n >= 25 else 2})
                for c in np.flatnonzero((load > 1) & ~np.isin(np.arange(C), list(milestones_set(milestones, 'over')))):
                    milestones.add(('over', int(c)))
                    if len([m for m in milestones if m[0] == 'over']) <= 8:
                        events.append({'t': t, 'title': f'Hospitals over surge capacity in {ctx.c_name[c]}',
                                       'cause': f'demand {load[c] * 100:.0f}% of surge beds ({beds[c]:.1f} beds per 1,000{", median used" if beds_missing[c] else ""})',
                                       'places': [ctx.c_name[c]], 'severity': 3})
                for thr, label in ((1e5, '100k'), (1e6, '1M'), (1e7, '10M'), (1e8, '100M')):
                    if total_rep >= thr and ('rep', label) not in milestones:
                        milestones.add(('rep', label))
                        events.append({'t': t, 'title': f'Reported cases pass {label}', 'cause': f'{total_cum / 1e6:.1f}M true infections (ascertainment {asc.mean() * 100:.0f}% on average)',
                                       'places': [], 'severity': 2})
                if border_on and ('border', 0) not in milestones:
                    milestones.add(('border', 0))
                # persona states
                loc_prev = I.sum(1) / np.maximum(Ni.sum(1), 1)
                rep_100k = loc_rep / np.maximum(Ni.sum(1), 1) * 1e5
                attack = cum / np.maximum(Ni, 1)
                pa = attack[ctx.p_loc, ctx.p_age]
                lp = loc_prev[ctx.p_loc]
                c_rep_100k = reported_c / np.maximum(ctx.c_pop, 1) * 1e5
                new = np.zeros(ctx.P, np.int8)
                aware = (total_rep >= 1) & ((reported_c[ctx.p_c] >= 1) | (me >= 0.5) & (total_rep >= 100) | (total_rep >= 10000))
                new[aware] = STATUS['aware']
                new[aware & ((lp >= 2e-4) | (c_rep_100k[ctx.p_c] >= 10))] = STATUS['reacting']
                new[(pa >= 0.02) | (lp >= 1e-3)] = STATUS['affected']
                falling = lp < prev_prev[ctx.p_loc]
                rec = (status == STATUS['affected']) & falling & (lp < 2e-4) & (pa >= 0.05)
                status = monotone(new, status)
                status[rec] = STATUS['recovered']
                p_status[t] = status
                p_metric[t] = rep_100k[ctx.p_loc]
                prev_prev = loc_prev
                for j, inst in enumerate(ctx.institutions):
                    s = 0
                    if inst.role == 'health_ministry':
                        s = STATUS['affected'] if (load[ctx.loc_c[seed_loc]] > 1) else STATUS['reacting'] if detected_t is not None else STATUS['aware'] if total_cum > 50 else 0
                    elif inst.role == 'health_agency':
                        s = STATUS['affected'] if total_rep >= 1e6 else STATUS['reacting'] if total_rep >= 1000 else STATUS['aware'] if detected_t is not None else 0
                    elif inst.role == 'airline':
                        s = STATUS['affected'] if (border_on or reached.sum() >= 30) else STATUS['reacting'] if reached.sum() >= 5 else STATUS['aware'] if detected_t is not None else 0
                    elif inst.role == 'vaccine_maker':
                        s = STATUS['affected'] if vacc_started else STATUS['reacting'] if detected_t is not None and t - detected_t >= 14 else STATUS['aware'] if detected_t is not None else 0
                    elif inst.role == 'media':
                        s = STATUS['affected'] if total_rep >= 1e5 else STATUS['reacting'] if total_rep >= 100 else STATUS['aware'] if detected_t is not None else 0
                    i_status[t, j] = max(s, i_status[t - 1, j] if t else 0)
                    i_metric[t, j] = float(c_rep_100k[ctx.c_idx.get(inst.iso3, 0)]) if inst.iso3 in ctx.c_idx else total_rep
                dc_100k = np.bincount(ctx.loc_c, weights=D.sum(1), minlength=C) / np.maximum(ctx.c_pop, 1) * 1e5
                layers.append({'cases_per_100k': {ctx.iso3[c]: round(float(c_rep_100k[c]), 2) for c in np.flatnonzero(c_rep_100k > 0.01)},
                               'deaths_per_100k': {ctx.iso3[c]: round(float(dc_100k[c]), 3) for c in np.flatnonzero(dc_100k > 0.001)},
                               'hospital_load_pct': {ctx.iso3[c]: round(float(load[c] * 100), 1) for c in np.flatnonzero(load > 0.01)},
                               'activity_drop_pct': {ctx.iso3[c]: round(float(drop[c] * 100), 1) for c in np.flatnonzero(drop > 0.005)}})
        out = {'deaths': float(D.sum()), 'infections': float(cum.sum()), 'reported': float(reported_c.sum()), 'countries': float(reached.sum()),
               'overloaded': float(over_any.sum()), 'days_to_10': days_to_10, 'peak_day': float(np.argmax(active_series) * ctx.dt)}
        traj = Trajectory(key=key, metrics=metrics, outcomes=out)
        if detail:
            traj.p_status, traj.p_metric, traj.i_status, traj.i_metric = p_status, p_metric, i_status, i_metric
            traj.layers, traj.flows, traj.events = layers, flows, events
            dcs = np.bincount(ctx.loc_c, weights=D.sum(1), minlength=C)
            d100k = dcs / np.maximum(ctx.c_pop, 1) * 1e5
            top = [c for c in np.argsort(-dcs)[:10] if dcs[c] > 0]
            traj.breakdown['hardest_hit'] = [{'country': ctx.c_name[c], 'deaths_k': round(dcs[c] / 1000, 2), 'deaths_per_100k': round(d100k[c], 1),
                                              'beds_per_1000': round(float(beds[c]), 1), 'reached_day': None} for c in top]
            spared = [c for c in np.argsort(d100k) if ctx.c_pop[c] > 5e6][:5]
            traj.breakdown['least_affected'] = [{'country': ctx.c_name[c], 'deaths_per_100k': round(d100k[c], 2)} for c in spared]
            age_d = D.sum(0)
            traj.breakdown['deaths_by_age'] = [{'age': a, 'deaths_k': round(age_d[i] / 1000, 2), 'share_pct': round(age_d[i] / max(D.sum(), 1) * 100, 1)}
                                               for i, a in enumerate(['0-14', '15-64', '65+'])]
            traj.breakdown['winners'] = [{'name': 'Vaccine makers', 'why': f'vaccination from day {int(p["vaccine_day"])}', 'detail': 'demand for doses'},
                                         {'name': 'Countries with surge capacity', 'why': f'{C - int(over_any.sum())} of {C} never exceeded surge beds', 'detail': 'hospital beds per 1,000 (World Bank)'}]
            traj.breakdown['losers'] = [{'name': ctx.c_name[c], 'why': f'{d100k[c]:.0f} deaths per 100k', 'detail': f'{beds[c]:.1f} beds per 1,000'} for c in top[:3]] + \
                                       [{'name': 'Airlines', 'why': f'transmission reached {int(reached.sum())} countries', 'detail': 'travel demand falls with contact drops'},
                                        {'name': 'Adults 65+', 'why': f'{age_d[2] / max(D.sum(), 1) * 100:.0f}% of deaths', 'detail': 'age-specific fatality curve'}]
            traj.causal = {'nodes': [
                {'id': 'seed', 'label': f'Rural cluster in {ctx.c_name[ctx.loc_c[seed_loc]]} ({int(p["seed"])} infections)'},
                {'id': 'r0', 'label': f'R0 {p["r0"]:.2f}'}, {'id': 'local', 'label': 'Local and domestic spread'},
                {'id': 'travel', 'label': 'Travel network seeding'}, {'id': 'countries', 'label': f'{int(reached.sum())} countries with transmission'},
                {'id': 'hosp', 'label': f'Hospitals over capacity in {int(over_any.sum())} countries'},
                {'id': 'behavior', 'label': f'Contacts drop up to {p["behavior_max"] * 100:.0f}%'},
                {'id': 'deaths', 'label': f'{D.sum() / 1000:,.0f}k deaths'}, {'id': 'vaccine', 'label': f'Vaccine from day {int(p["vaccine_day"])}'}],
                'edges': [{'from': 'seed', 'to': 'local'}, {'from': 'r0', 'to': 'local'}, {'from': 'local', 'to': 'travel'}, {'from': 'travel', 'to': 'countries'},
                          {'from': 'countries', 'to': 'hosp'}, {'from': 'hosp', 'to': 'deaths', 'label': 'raises fatality'}, {'from': 'deaths', 'to': 'behavior', 'label': 'visible deaths'},
                          {'from': 'behavior', 'to': 'local', 'label': 'slows'}, {'from': 'vaccine', 'to': 'local', 'label': 'slows'}]}
        return traj

    def inst_metric(self, role: str) -> tuple[str, str]:
        return ('reported cases in its country', 'per 100k')

    def inst_text(self, role: str, v: float) -> str:
        from ..util import fmt
        return f'{fmt(v)} reported cases per 100k'

    def counterfactuals(self, ctx: Context) -> list[dict]:
        from ..models import Intervention
        return [{'action': 'Close borders on day 10', 'trigger': 'confirmed human-to-human cluster', 'interventions': [Intervention(kind='border_closure', day=10, text='borders close on day 10')]},
                {'action': 'Lockdown in the origin country on day 14', 'trigger': 'local reported cases > 10 per 100k',
                 'interventions': [Intervention(kind='lockdown', day=14, countries=[ctx.iso3[ctx.loc_c[ctx.origin_loc]]] if ctx.origin_loc is not None else [], text='origin lockdown on day 14')]},
                {'action': 'Vaccine 80 days sooner (day 120)', 'trigger': 'platform vaccine pre-approved', 'params': {'vaccine_day': 120.0}}]


def milestones_set(ms: set, kind: str) -> set:
    return {m[1] for m in ms if isinstance(m, tuple) and m[0] == kind}
