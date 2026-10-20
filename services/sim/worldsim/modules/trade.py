"""Trade policy shock: tariff on a product from an exporter into an importer (or bloc).

Bilateral baseline flows come from a gravity model on World Bank GDP and distance, scaled to a goods-export share
of GDP (prior). Product share of the bilateral flow, pass-through, import elasticity, diversion and retaliation are
priors. UN Comtrade bilateral flows by HS code replace the gravity baseline when that dataset is ingested.
"""
from __future__ import annotations

import re

import numpy as np

from ..geo import EU27
from .base import STATUS, TRAITS, Context, Module, Prior, Trajectory, monotone

GRAVITY = 'Tinbergen (1962) gravity model; distance elasticity ~1 (Disdier & Head 2008 meta-analysis)'
ELASTICITY = 'Import demand elasticities for manufactures typically -1.5 to -5 (Broda & Weinstein 2006; Imbs & Mejean 2015)'
# product keyword → (label, share of exporter→importer goods trade, low, high, elasticity central, low, high)
PRODUCTS = [
    (r'\bevs?\b|electric (car|vehicle)s?', 'electric vehicles', 0.02, 0.012, 0.03, -3.0, -5.0, -1.5),
    (r'\bsteel|alumin(i)?um', 'steel and aluminum', 0.015, 0.008, 0.025, -2.0, -4.0, -1.0),
    (r'\bsolar|photovoltaic|panels?', 'solar panels', 0.01, 0.005, 0.02, -3.0, -5.0, -1.5),
    (r'\bchips?\b|semiconductor', 'semiconductors', 0.04, 0.02, 0.06, -1.5, -3.0, -0.8),
    (r'\bcars?\b|\bauto(mobile)?s?\b|vehicles?', 'motor vehicles', 0.05, 0.03, 0.08, -2.5, -4.0, -1.2),
    (r'\bphones?\b|smartphones?|electronics', 'electronics', 0.08, 0.05, 0.12, -1.5, -3.0, -0.8),
    (r'\bsoy(beans?)?\b|wheat|corn|grain|food|agricultur', 'agricultural goods', 0.03, 0.015, 0.05, -2.0, -4.0, -1.0),
    (r'\ball (imports|goods)|everything', 'all goods', 1.0, 1.0, 1.0, -1.5, -2.5, -0.8),
]
GENERIC_PRODUCT = ('targeted goods', 0.02, 0.01, 0.04, -2.0, -4.0, -1.0)


def resolve_parties(ctx: Context) -> tuple[list[int], int | None, tuple]:
    """Importer country indices (a bloc for the EU), exporter index, and the product row, from the prompt."""
    from ..parse import DEMONYMS, find_place
    lower = ctx.spec.prompt.lower()
    m = re.search(r'^(?P<imp>.*?)\s+(imposes?|slaps?|levies|levy|announces?|places?|puts?|raises?)\b(?P<rest>.*)$', lower)
    imp_txt, rest = (m.group('imp'), m.group('rest')) if m else (lower, lower)
    on = re.search(r'\bon\s+(?P<exp>.+)$', rest)
    exp_txt = on.group('exp') if on else rest
    w = ctx.world
    if re.search(r'\b(eu|european union)\b', imp_txt):
        importers = [ctx.c_idx[c] for c in EU27 if c in ctx.c_idx]
    else:
        pl = find_place(imp_txt, w)
        importers = [ctx.c_idx[pl.iso3]] if pl and pl.iso3 in ctx.c_idx else []
    exporter = None
    for k in sorted(DEMONYMS, key=len, reverse=True):
        if re.search(rf'\b{re.escape(k)}\b', exp_txt) and DEMONYMS[k] in ctx.c_idx:
            exporter = ctx.c_idx[DEMONYMS[k]]
            break
    if exporter is None:
        pl = find_place(exp_txt, w)
        exporter = ctx.c_idx.get(pl.iso3) if pl else None
    if not importers and ctx.spec.origin and ctx.spec.origin.iso3 in ctx.c_idx and ctx.c_idx[ctx.spec.origin.iso3] != exporter:
        importers = [ctx.c_idx[ctx.spec.origin.iso3]]
    importers = [c for c in importers if c != exporter]
    product = next((p[1:] for p in PRODUCTS if re.search(p[0], exp_txt)), GENERIC_PRODUCT)
    return importers, exporter, product


class Trade(Module):
    name = 'trade'
    key_metric = 'lost_imports_busd'
    key_unit = 'USD billion of lost imports (cumulative)'
    persona_metric = ('price or export change', '%')
    layers = [('price_change_pct', 'Price change of the targeted product', '%'), ('trade_change_pct', 'Change in imports of the product from the target', '%'),
              ('gdp_impact_pct', 'GDP impact', '% of GDP')]
    outcome_spec = [('lost_imports_busd', 'Lost imports of the product from the target', 'USD billion'),
                    ('price_change_pct', 'Consumer price change of the product in the importer', '%'),
                    ('exporter_loss_busd', 'Exporter revenue loss', 'USD billion'),
                    ('diverted_busd', 'Demand diverted to other suppliers', 'USD billion'),
                    ('tariff_revenue_busd', 'Tariff revenue collected', 'USD billion'),
                    ('retaliation', 'Share of runs with retaliation', 'share of runs'),
                    ('exporter_gdp_pct', 'Exporter GDP impact', '% of GDP'), ('importer_gdp_pct', 'Importer GDP impact', '% of GDP')]
    mechanisms = ['price pass-through', 'import demand response', 'trade diversion', 'retaliation', 'tariff revenue']
    explain_keys = [('gdp_usd', 'GDP $'), ('gdp_per_capita_usd', 'GDP per capita $'), ('inflation_pct', 'inflation %')]
    confidence = 'low'
    calibration_note = 'Baseline flows are a gravity model, not customs data; product shares are analyst priors. Treat magnitudes as order-of-magnitude.'

    def priors(self, ctx: Context) -> list[Prior]:
        rate = next((a.value for a in ctx.spec.assumptions if a.id == 'tariff_pct'), None)
        label, share, slo, shi, el, elo, ehi = resolve_parties(ctx)[2]
        return [
            Prior('tariff_pct', 'Tariff rate' if rate else 'Tariff rate (not stated; prior)', float(rate or 25), float(rate or 10), float(rate or 50), '%',
                  'user' if rate else 'model', 'high' if rate else 'low'),
            Prior('export_share', 'Goods exports as a share of GDP (all countries)', 0.22, 0.15, 0.30, 'share', 'model', 'low', GRAVITY),
            Prior('product_share', f'Share of the bilateral goods flow that is {label}', share, slo, shi, 'share', 'model', 'low',
                  'analyst prior; UN Comtrade HS-level flows not yet ingested'),
            Prior('passthrough', 'Share of the tariff passed through to importer prices', 0.6, 0.3, 0.9, 'share', 'model', 'low',
                  'Amiti, Redding & Weinstein (2019): near-complete pass-through of 2018 US tariffs'),
            Prior('elasticity', f'Import demand elasticity for {label}', el, elo, ehi, '', 'model', 'low', ELASTICITY),
            Prior('adjust_weeks', 'Time constant for buyers and supply chains to adjust', 12.0, 4.0, 26.0, 'weeks', 'model', 'low'),
            Prior('diversion', 'Share of lost imports replaced by other suppliers (domestic or third countries)', 0.5, 0.2, 0.8, 'share', 'model', 'low'),
            Prior('retaliation_prob', 'Probability the target retaliates', 0.5, 0.2, 0.8, 'probability', 'model', 'low'),
            Prior('retaliation_week', 'Week retaliation takes effect', 10.0, 4.0, 20.0, 'week', 'model', 'low'),
            Prior('retaliation_share', 'Share of importer → target exports hit by retaliation', 0.03, 0.01, 0.08, 'share', 'model', 'low'),
            Prior('multiplier', 'Domestic value-added multiplier on lost exports', 1.2, 0.8, 1.6, '×', 'model', 'low'),
        ]

    def _flows(self, ctx: Context, export_share: float) -> tuple[np.ndarray, np.ndarray]:
        gdp = ctx.ind('gdp_usd')
        gdp = np.where(np.isfinite(gdp), gdp, np.nan_to_num(ctx.gdp_pc, nan=3000.0) * ctx.c_pop)
        d = np.maximum(ctx.c_dist, 200)
        w = gdp[None, :] / d
        np.fill_diagonal(w, 0)
        w /= w.sum(1, keepdims=True) + 1e-12
        return w * (gdp * export_share)[:, None], gdp  # X[i, j]: annual goods exports i → j (USD)

    def simulate(self, ctx: Context, p: dict, rng: np.random.Generator, detail: bool) -> Trajectory:
        T, C, dt_w = ctx.steps, ctx.C, ctx.dt / 7
        importers, exporter, prod = resolve_parties(ctx)
        retaliates = rng.random() < p['retaliation_prob']
        key = np.zeros(T + 1)
        metrics, layers, flows, events = [], [], [], []
        p_status = np.zeros((T + 1, ctx.P), np.int8) if detail else None
        p_metric = np.zeros((T + 1, ctx.P), np.float32) if detail else None
        i_status = np.zeros((T + 1, ctx.I), np.int8) if detail else None
        i_metric = np.zeros((T + 1, ctx.I), np.float32) if detail else None
        if exporter is None or not importers:
            # The parties could not be identified: report nothing rather than invent a flow.
            metrics = [{'lost_imports_busd': 0.0} for _ in range(T + 1)]
            return Trajectory(key=key, metrics=metrics, outcomes={k: float('nan') for k, _, _ in self.outcome_spec},
                              p_status=p_status, p_metric=p_metric, i_status=i_status, i_metric=i_metric,
                              layers=[{} for _ in range(T + 1)] if detail else None, flows=[[] for _ in range(T + 1)] if detail else None,
                              events=[{'t': 0, 'title': 'Trade parties not identified', 'cause': 'name the importer and the target country', 'places': [], 'severity': 3}])
        X, gdp = self._flows(ctx, p['export_share'])
        imp = np.zeros(C, bool)
        imp[importers] = True
        tau = p['tariff_pct'] / 100
        for iv in ctx.spec.interventions:
            if iv.kind == 'tariff_change' and iv.value is not None:
                tau = iv.value / 100
        base = X[exporter, importers] * p['product_share']  # annual product imports by importer country
        base_total = float(base.sum())
        price = tau * p['passthrough']
        target_drop = min(0.95, -p['elasticity'] * price) if price > 0 else 0.0
        third = np.where(~imp & (np.arange(C) != exporter), X[:, importers].sum(1), 0.0)
        third_w = third / max(third.sum(), 1)
        ret_flow = float(X[importers, exporter].sum() * p['retaliation_share'])
        ret_drop = min(0.95, -p['elasticity'] * 0.5 * tau * p['passthrough'])
        cum_lost = cum_div = cum_tariff = cum_ret = 0.0
        me = ctx.p_traits[:, TRAITS.index('media_exposure')]
        trust = ctx.p_traits[:, TRAITS.index('institutional_trust')]
        hubs = np.flatnonzero((ctx.loc_c == exporter) & ctx.loc_urban)
        hubs = hubs[np.argsort(-ctx.loc_pop[hubs])][:8]  # largest cities as a proxy for export manufacturing hubs (assumption)
        hub_mask = np.isin(ctx.p_loc, hubs)
        status = np.zeros(ctx.P, np.int8)
        ret_on_t = None
        logged: set[str] = set()
        for t in range(T + 1):
            week = t * dt_w
            adj = 1 - np.exp(-week / p['adjust_weeks'])
            drop = target_drop * adj
            lost_rate = base_total * drop / 52 * dt_w
            cum_lost += lost_rate
            cum_div += lost_rate * p['diversion']
            cum_tariff += base_total * (1 - drop) / 52 * dt_w * tau
            ret_on = retaliates and week >= p['retaliation_week']
            if ret_on and ret_on_t is None:
                ret_on_t = t
            if ret_on:
                cum_ret += ret_flow * ret_drop * (1 - np.exp(-(week - p['retaliation_week']) / p['adjust_weeks'])) / 52 * dt_w
            years = max(week, dt_w) / 52
            exporter_gdp = -(cum_lost * p['multiplier']) / gdp[exporter] / years * 100
            importer_gdp = -(cum_ret * p['multiplier'] + cum_lost * (1 - p['diversion']) * 0.1) / gdp[imp].sum() / years * 100
            key[t] = cum_lost / 1e9
            metrics.append({'lost_imports_busd': round(cum_lost / 1e9, 4), 'price_change_pct': round(price * 100 * adj, 3), 'diverted_busd': round(cum_div / 1e9, 4),
                            'tariff_revenue_busd': round(cum_tariff / 1e9, 4), 'retaliation_on': float(ret_on), 'retaliation_loss_busd': round(cum_ret / 1e9, 4)})
            if not detail:
                continue
            if t == 0:
                events.append({'t': 0, 'title': f'{tau * 100:.0f}% tariff on {prod[0]} from {ctx.c_name[exporter]} takes effect',
                               'cause': f'baseline flow ${base_total / 1e9:.1f}B/yr (gravity model × product share prior)', 'places': [ctx.c_name[exporter]], 'severity': 3})
            if ret_on_t == t:
                events.append({'t': t, 'title': f'{ctx.c_name[exporter]} retaliates', 'cause': f'tariffs on ${ret_flow / 1e9:.1f}B of the importer\'s exports',
                               'places': [ctx.c_name[exporter]], 'severity': 3})
            for frac, label in ((0.5, 'half'), (0.9, '90%')):
                if adj >= frac and label not in logged:
                    logged.add(label)
                    events.append({'t': t, 'title': f'Import response reaches {label} of its long-run size', 'cause': f'adjustment time constant {p["adjust_weeks"]:.0f} weeks',
                                   'places': [], 'severity': 2})
            if cum_lost >= 1e9 and '1b' not in logged:
                logged.add('1b')
                events.append({'t': t, 'title': 'Lost imports pass $1B', 'cause': f'{drop * 100:.0f}% fewer {prod[0]} from {ctx.c_name[exporter]}', 'places': [], 'severity': 2})
            pc = np.zeros(ctx.P)
            pc[imp[ctx.p_c]] = price * 100 * adj
            pc[hub_mask] = -drop * 100
            involved = imp[ctx.p_c] | (ctx.p_c == exporter)
            buyer_seg = np.isin(ctx.p_seg, [2, 3])
            new = np.zeros(ctx.P, np.int8)
            new[(involved & (me >= 0.3)) | ((me >= 0.8) & (week >= 1))] = STATUS['aware']
            new[imp[ctx.p_c] & buyer_seg & (price * 100 * adj >= 2)] = STATUS['reacting']
            new[imp[ctx.p_c] & buyer_seg & (price * 100 * adj >= 5)] = STATUS['affected']
            new[hub_mask & np.isin(ctx.p_seg, [1, 2]) & (drop * 100 >= 10)] = STATUS['affected']
            new[involved & (trust < 0.4) & np.isin(ctx.p_seg, [1, 2]) & (week >= 2) & (me >= 0.5)] = STATUS['opposed']
            status = np.where(status == STATUS['affected'], status, monotone(new, status)).astype(np.int8)
            p_status[t] = status
            p_metric[t] = np.round(pc, 2)
            for j, inst in enumerate(ctx.institutions):
                s = STATUS['reacting']
                if inst.role == 'exporter_authority' and ret_on:
                    s = STATUS['affected']
                if inst.role == 'importer_authority' and week >= 4:
                    s = STATUS['affected']
                if inst.role == 'arbiter' and week >= 8:
                    s = STATUS['affected']
                if inst.role in ('company', 'shipper') and (drop >= 0.1 or ret_on):
                    s = STATUS['affected']
                i_status[t, j] = max(s, i_status[t - 1, j] if t else 0)
                i_metric[t, j] = drop * 100 if inst.iso3 == ctx.iso3[exporter] else price * 100 * adj
            div = {ctx.iso3[c]: round(float(cum_div * third_w[c] / max(gdp[c], 1) * 100 / years), 5) for c in np.argsort(-third_w)[:10] if third_w[c] > 0}
            layers.append({'price_change_pct': {ctx.iso3[c]: round(price * 100 * adj, 2) for c in importers},
                           'trade_change_pct': {ctx.iso3[c]: round(-drop * 100, 2) for c in importers},
                           'gdp_impact_pct': {**div, ctx.iso3[exporter]: round(float(exporter_gdp), 5), **{ctx.iso3[c]: round(float(importer_gdp), 5) for c in importers}}})
            fl = []
            src = ctx.c_hub[exporter]
            for i in np.argsort(-base)[:10]:
                h = ctx.c_hub[importers[i]]
                fl.append({'from': [float(ctx.loc_lon[src]), float(ctx.loc_lat[src])], 'to': [float(ctx.loc_lon[h]), float(ctx.loc_lat[h])],
                           'weight': float(max(0.1, 1 - drop)), 'kind': 'trade'})
            dest = ctx.c_hub[importers[int(np.argmax(base))]]
            for c in np.argsort(-third_w)[:4]:
                h = ctx.c_hub[c]
                fl.append({'from': [float(ctx.loc_lon[h]), float(ctx.loc_lat[h])], 'to': [float(ctx.loc_lon[dest]), float(ctx.loc_lat[dest])],
                           'weight': float(min(1, drop * third_w[c] * 4)), 'kind': 'trade'})
            flows.append(fl)
        years = ctx.steps * dt_w / 52
        out = {'lost_imports_busd': cum_lost / 1e9, 'price_change_pct': price * 100, 'exporter_loss_busd': cum_lost / 1e9, 'diverted_busd': cum_div / 1e9,
               'tariff_revenue_busd': cum_tariff / 1e9, 'retaliation': float(retaliates),
               'exporter_gdp_pct': -(cum_lost * p['multiplier']) / gdp[exporter] / years * 100,
               'importer_gdp_pct': -(cum_ret * p['multiplier'] + cum_lost * (1 - p['diversion']) * 0.1) / gdp[imp].sum() / years * 100}
        traj = Trajectory(key=key, metrics=metrics, outcomes=out)
        if detail:
            traj.p_status, traj.p_metric, traj.i_status, traj.i_metric = p_status, p_metric, i_status, i_metric
            traj.layers, traj.flows, traj.events = layers, flows, events
            traj.breakdown['importers'] = [{'country': ctx.c_name[importers[i]], 'baseline_busd': round(float(base[i]) / 1e9, 2),
                                            'lost_busd': round(float(base[i]) * target_drop * years / 1e9, 2)} for i in np.argsort(-base)[:10]]
            traj.breakdown['diversion_beneficiaries'] = [{'country': ctx.c_name[c], 'gain_busd': round(cum_div * third_w[c] / 1e9, 2)} for c in np.argsort(-third_w)[:5]]
            traj.breakdown['winners'] = [{'name': 'Domestic and third-country producers', 'why': f'${cum_div / 1e9:.1f}B of diverted demand', 'detail': 'diversion prior'},
                                         {'name': 'Importer treasuries', 'why': f'${cum_tariff / 1e9:.1f}B tariff revenue', 'detail': 'remaining imports × tariff'}] + \
                                        [{'name': ctx.c_name[c], 'why': f'${cum_div * third_w[c] / 1e9:.2f}B diverted to it', 'detail': 'gravity-weighted supplier share'}
                                         for c in np.argsort(-third_w)[:2]]
            traj.breakdown['losers'] = [{'name': f'{prod[0].capitalize()} exporters in {ctx.c_name[exporter]}', 'why': f'${cum_lost / 1e9:.1f}B lost sales', 'detail': f'elasticity {p["elasticity"]:.1f}'},
                                        {'name': 'Buyers in the importer', 'why': f'+{price * 100:.1f}% on {prod[0]}', 'detail': f'pass-through {p["passthrough"] * 100:.0f}%'}] + \
                                       ([{'name': 'Importer exporters hit by retaliation', 'why': f'${cum_ret / 1e9:.2f}B', 'detail': 'retaliation share prior'}] if retaliates else [])
            traj.causal = {'nodes': [{'id': 'tariff', 'label': f'{tau * 100:.0f}% tariff on {prod[0]}'},
                                     {'id': 'base', 'label': f'${base_total / 1e9:.1f}B/yr baseline flow'},
                                     {'id': 'price', 'label': f'+{price * 100:.1f}% importer price'},
                                     {'id': 'volume', 'label': f'-{target_drop * 100:.0f}% imports from {ctx.c_name[exporter]}'},
                                     {'id': 'diversion', 'label': f'${cum_div / 1e9:.1f}B diverted to other suppliers'},
                                     {'id': 'revenue', 'label': f'${cum_tariff / 1e9:.1f}B tariff revenue'},
                                     {'id': 'retaliation', 'label': 'Retaliation' + (f' (week {p["retaliation_week"]:.0f})' if retaliates else ' (not in this run)')}],
                           'edges': [{'from': 'tariff', 'to': 'price', 'label': 'pass-through'}, {'from': 'price', 'to': 'volume', 'label': 'elasticity'},
                                     {'from': 'base', 'to': 'volume'}, {'from': 'volume', 'to': 'diversion'}, {'from': 'tariff', 'to': 'revenue'},
                                     {'from': 'volume', 'to': 'retaliation', 'label': 'provokes'}]}
            ctx.partner_name = ctx.c_name[exporter]
        return traj

    def inst_metric(self, role: str) -> tuple[str, str]:
        return ('price or import change', '%')

    def inst_text(self, role: str, v: float) -> str:
        return f'{v:.1f}%'

    def counterfactuals(self, ctx: Context) -> list[dict]:
        base = {p.key: p for p in self.priors(ctx)}
        rate = base['tariff_pct'].value
        return [{'action': f'Set the tariff at {rate / 2:.0f}% instead of {rate:.0f}%', 'trigger': 'policy design', 'params': {'tariff_pct': rate / 2}},
                {'action': 'Negotiate price undertakings (pass-through 30%)', 'trigger': 'exporters agree minimum prices', 'params': {'passthrough': 0.3}},
                {'action': 'Avoid retaliation through a negotiated package', 'trigger': 'talks open before the tariff takes effect', 'params': {'retaliation_prob': 0.0}}]
