"""Read-only evidence tools for agents. Every item carries an id, value, year and source; agents cite ids, and a
proposal citing an id no tool returned is rejected (`ok`). `text()` is the allowed-numbers context for numbers_ok."""
from __future__ import annotations

import duckdb

from . import analogs

KEY_INDICATORS = ['population', 'gdp_per_capita_usd', 'gdp_usd', 'urban_pct', 'internet_users_pct', 'age_65_plus_pct', 'age_0_14_pct',
                  'hospital_beds_per1000', 'physicians_per1000', 'gini', 'inflation_pct', 'unemployment_pct', 'life_expectancy']


def _obj(props: dict) -> dict:
    return {'type': 'object', 'additionalProperties': False, 'required': list(props), 'properties': props}


SPECS = {
    'find_place': ('Look up a city or country by name in the gazetteer: coordinates, country, metro population.',
                   _obj({'name': {'type': 'string'}})),
    'get_country': ('Country profile: income group, continent, and the latest World Bank indicators (population, GDP per capita, '
                    'urbanization, internet use, age structure, hospital beds, physicians, Gini, inflation, unemployment).',
                    _obj({'iso3': {'type': 'string', 'description': 'ISO 3166-1 alpha-3 code, e.g. VNM'}})),
    'get_indicator_series': ('Annual series of one World Bank indicator for one country (2000 onward).',
                             _obj({'iso3': {'type': 'string'}, 'key': {'type': 'string', 'enum': KEY_INDICATORS}})),
    'get_company': ('Company profile from the company store: country, industry, employees, latest revenue.',
                    _obj({'name': {'type': 'string'}})),
    'search_analogs': ('Search the library of past events with recorded outcomes (deaths, cases, units, countries) and sources.',
                       _obj({'query': {'type': 'string'}})),
    'list_priors': ('The simulation model parameters for this scenario: central value, allowed range, unit and source.', _obj({})),
}


class Evidence:
    def __init__(self, world, spec=None, priors=None):
        self.world, self.spec, self.priors = world, spec, list(priors or [])
        self.seen: dict[str, dict] = {}

    def _add(self, items: list[dict], note: str | None = None) -> dict:
        for it in items:
            self.seen[it['id']] = it
        return {'items': items, **({'note': note} if note else {})}

    def find_place(self, name: str) -> dict:
        from .parse import find_place
        pl = find_place(name, self.world)
        if not pl:
            return self._add([], f'no place named "{name}" in the gazetteer')
        return self._add([{'id': f'place:{pl.id}', 'title': f'{pl.name}, {pl.country}', 'value': pl.pop, 'unit': 'people (metro estimate)',
                           'year': None, 'source': 'Natural Earth populated places', 'text': f'iso3 {pl.iso3}; lat {pl.lat}, lon {pl.lon}; capital {pl.capital}'}])

    def get_country(self, iso3: str) -> dict:
        c = self.world.countries.get(iso3.upper())
        if not c:
            return self._add([], f'unknown ISO3 code {iso3}')
        items = [{'id': f'country:{c.iso3}', 'title': c.name, 'value': None, 'unit': '', 'year': None, 'source': 'Natural Earth; World Bank income groups',
                  'text': f'{c.kind}; continent {c.continent or "unknown"}; income group {c.income_group or "unknown"}'}]
        for k in KEY_INDICATORS:
            v = c.ind.get(k)
            if v:
                items.append({'id': f'ind:{c.iso3}:{k}', 'title': f'{c.name}: {k}', 'value': v.value, 'unit': v.unit, 'year': v.year,
                              'source': v.source, 'text': ''})
        return self._add(items)

    def get_indicator_series(self, iso3: str, key: str) -> dict:
        path = getattr(self.world, 'path', None)
        f = path / 'indicators.parquet' if path else None
        if not f or not f.exists():
            return self._add([], 'no data snapshot available')
        rows = duckdb.connect().execute(f"SELECT year, value, unit, source FROM read_parquet('{f.as_posix()}') WHERE iso3 = ? AND key = ? ORDER BY year",
                                        [iso3.upper(), key]).fetchall()
        return self._add([{'id': f'ind:{iso3.upper()}:{key}:{y}', 'title': f'{iso3.upper()} {key} {y}', 'value': float(v), 'unit': u or '', 'year': int(y),
                           'source': s, 'text': ''} for y, v, u, s in rows], None if rows else f'no {key} series for {iso3}')

    def get_company(self, name: str) -> dict:
        q = name.casefold()
        hits = [c for cid, c in self.world.companies.items() if q in cid or q in c.name.casefold()][:3]
        items = []
        for c in hits:
            rev = c.financials.get('revenue')
            items.append({'id': f'company:{c.id}', 'title': c.name, 'value': c.employees, 'unit': 'employees', 'year': None, 'source': c.source or 'company store',
                          'text': f'country {c.country_iso3}; industry {c.industry or "n/a"}' + (f'; revenue {rev.value:.4g} {rev.unit} ({rev.year}, {rev.source})' if rev else '')})
        return self._add(items, None if items else f'"{name}" is not in the company store')

    def search_analogs(self, query: str) -> dict:
        found = analogs.search(query, self.spec.event_type if self.spec else None, k=6)
        return self._add([{'id': f'analog:{a["id"]}', 'title': a['name'], 'value': None, 'unit': '', 'year': None, 'source': a['source'],
                           'text': a['outcomes'] + (f' Metrics: {a["metrics"]} ({a["definition"]}).' if a.get('metrics') else '') + f' Reach: {a["reach"]}.'}
                          for a in found], None if found else 'no analog matched')

    def list_priors(self) -> dict:
        return self._add([{'id': f'prior:{p.key}', 'title': p.text, 'value': p.value, 'unit': p.unit, 'year': None, 'source': p.source or p.origin,
                           'text': f'allowed range {p.low:g} to {p.high:g}; confidence {p.confidence}'} for p in self.priors])

    def tools(self, names: list[str]) -> list[dict]:
        return [{'name': n, 'description': SPECS[n][0], 'input_schema': SPECS[n][1], 'fn': getattr(self, n)} for n in names]

    def ok(self, ids: list[str]) -> bool:
        return bool(ids) and all(i in self.seen for i in ids)

    def text(self) -> str:
        return ' '.join(f'{it["title"]} {it["value"] if it["value"] is not None else ""} {it["year"] or ""} {it["text"]}' for it in self.seen.values())
