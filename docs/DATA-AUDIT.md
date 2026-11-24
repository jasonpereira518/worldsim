# Data and parameter audit

2026-11-24, snapshot 2026-10-23, engine worldsim-0.2. Every dataset, model prior, model constant and analog the simulator uses, sorted by where its value comes from.

**Rule.** A value is *verified* when it comes from a government or intergovernmental body (World Bank, UN, WHO, national agencies, regulators) or from peer-reviewed research. Anything else counts as a guess and must be replaced or clearly labeled.

Tiers used below:

| Tier | Meaning |
|---|---|
| **G** | Government or intergovernmental source; the value is taken as published |
| **P** | Peer-reviewed study; the value or range is taken from it |
| **Fit** | Our fit of a published functional form to verified records (the six earthquake backtests) |
| **Partial** | A verified source sets the form or the plausible range; the central value is our pick |
| **Guess** | No source, or a source that does not meet the rule (company, industry, community, our judgment) |

## Summary

| | Verified (G, P) | Fit or Partial | Guess | Total |
|---|---|---|---|---|
| Datasets | 4 | – | 5 | 9 |
| Model priors | 8 | 6 | 48 | 62 |
| Model constants | 1 | – | 5 | 6 |
| Analogs (past events) | 17 | – | 2 | 19 |

Three quarters of the model priors are guesses. Most carry wide ranges and low confidence, which the ensemble propagates, but the product does not yet tell a reader which numbers are guesses. User-stated values (price, magnitude, tariff rate) are the scenario's premise and are not audited.

## Datasets

| Dataset | Publisher | Tier | Used for | Note |
|---|---|---|---|---|
| World Development Indicators | World Bank | G | Population, age shares, GDP per capita, Gini, internet use, hospital beds, physicians | |
| Country classification | World Bank | G | Income group, region | |
| EDGAR XBRL company facts | U.S. SEC | G | Company financials, supplier revenue shares | |
| Legal Entity Identifiers | GLEIF | G | Company legal identity, headquarters | GLEIF is overseen by a committee of public regulators (FSB / G20 mandate) |
| Admin-0 countries, 1:50m | Natural Earth | Guess | Country keys, boundaries, centroids | Community cartography (public domain). Geometry is fine in practice; it is still not a qualifying source |
| Admin-1 provinces, 1:10m | Natural Earth | Guess | Province areas: rural population spread, quake exposure | Same |
| Populated places, 1:50m | Natural Earth | Guess | **Persona placement and city populations** (`pop_max`, a metro estimate circa 2015); quake exposure discs | The highest-impact unverified input: city sizes drive where people are and who shakes |
| Populated places, 1:10m (gazetteer) | Natural Earth | Guess | Place lookup only | Coordinates only; low impact |
| Company profiles | Wikidata | Guess | Company selection, sector, headcount, headquarters | Community-edited. SEC and GLEIF cover the same companies where they file |

## Model priors

`tier` is the tier of the central value; ranges are in the code (`worldsim/modules/*.py`, `priors()`).

### Launch (18 model priors: 2 verified, 16 guesses)

| Prior | Tier | Source or reason |
|---|---|---|
| `bass_p`, `bass_q` | P | Sultan, Farley & Lehmann (1990), meta-analysis of 213 Bass applications |
| `market_ceiling`, `spend_share`, `ecosystem_share`, `awareness_rate` | Guess | Analyst priors. These four drive most of the unit spread |
| `capacity_initial_k`, `capacity_max_k`, `ramp_weeks` | Guess | Analyst priors |
| `wave2_weeks`, `wave3_weeks`, `china_delay_weeks`, `eu_delay_weeks` | Guess | Analyst priors |
| `competitor_trigger_m`, `competitor_cut`, `competitor_effect` | Guess | Analyst priors |
| `bom_assembly`, `bom_chips` | Guess | Analyst priors (supplier revenue comes from SEC filings; the shares of the device price do not) |

### Epidemiology (15 model priors: 3 verified, 2 partial, 10 guesses)

| Prior | Tier | Source or reason |
|---|---|---|
| `r0` | P | Biggerstaff et al. (2014), systematic review of influenza reproduction numbers |
| `latent_days`, `infectious_days` | G | CDC and WHO pandemic-planning assumptions |
| `severity` | Partial | Range spans recorded pandemics (2009 H1N1, Dawood et al. 2012, to 1918); no human-transmissible H5N1 exists to fix the center |
| `vaccine_day` | Partial | 2009 H1N1 timeline (WHO); first doses about six months after detection |
| `behavior_max` | Guess | Cites Google Community Mobility Reports (a company) |
| `travel_rate` | Guess | Gravity form; no flight or arrivals data |
| `hosp_per_death`, `surge_bed_share`, `overflow_mult` | Guess | Analyst priors (bed counts themselves are WDI, G) |
| `domestic_mixing`, `ascertainment`, `report_lag`, `seed`, `vaccine_rate` | Guess | Analyst priors |
| Policy menu ranges (lockdown, border closure) | Guess | Cites the Oxford COVID-19 Government Response Tracker (Hale et al. 2021, peer-reviewed), but thresholds and lags are not fitted to it |

### Disaster: earthquakes (14 model priors: 1 verified, 3 fit or partial, 10 guesses)

| Prior | Tier | Source or reason |
|---|---|---|
| `rupture_factor` | P | Wells & Coppersmith (1994) subsurface rupture length; the 0.7–1.6 factor is ours |
| `theta_rich`, `beta` | Fit | USGS PAGER form (Jaiswal & Wald 2010), fitted by us to six historical death tolls from national agencies |
| `theta_drop` | Partial | PAGER form; the size of the drop is ours |
| `attenuation` | Guess | Uncited "simplified isoseismal relation". At damaging distances it is within about 0.2 MMI of a published intensity prediction equation |
| `depth_km`, `urban_density` | Guess | Analyst priors |
| `injury_ratio`, `displacement`, `capital_ratio` | Guess | Analyst priors |
| `restore_days`, `return_days`, `aid_days`, `report_days` | Guess | Analyst priors |
| Relief policy range | Guess | Cites UN INSARAG (G) timelines in general terms; values are ours |

### Trade (10 model priors: 2 verified, 1 partial, 7 guesses)

| Prior | Tier | Source or reason |
|---|---|---|
| `passthrough` | P | Amiti, Redding & Weinstein (2019) |
| `elasticity` | P | Broda & Weinstein (2006); Imbs & Mejean (2015) |
| `export_share` | Partial | Gravity form (Disdier & Head 2008); a single global 0.22 where WDI publishes each country's export share |
| `product_share` | Guess | No bilateral product data |
| `adjust_weeks`, `diversion`, `multiplier` | Guess | Analyst priors |
| `retaliation_prob`, `retaliation_week`, `retaliation_share` | Guess | Analyst priors (the 2018–2019 rounds inform them only loosely) |

### Generic fallback (5 model priors: all guesses)

`reach_km`, `spread_rate`, `hub_coupling`, `recovery_days`, `peak_share` come from an event-class table (`modules/generic.py`, `CLASS`), nudged by the closest analog when one exists. This is by design: generic runs are always labeled low confidence.

## Model constants (not sampled)

| Constant | Tier | Note |
|---|---|---|
| Income distribution per country | G | Lognormal fitted to WDI GDP per capita and Gini (σ from Gini is exact for a lognormal) |
| `IFR_BASE` (0.03% / 0.2% / 2% by age) | Guess | Age-specific fatality shape; uncited |
| `vulnerability()` (θ from GDP per capita) | Guess | Our log-linear mapping between $1,000 and $60,000 |
| `STANCE_BANDS` (crowd behavior multipliers) | Guess | Our bands per label |
| Scale thresholds (100 people, 0.01%, 25%, 25 countries on 3 continents) | Guess | Definitions, not estimates; they should be labeled as conventions |
| Generic `CLASS` table | Guess | As above |

LLM-set values (origin `llm`, the calibrator, actor and crowd agents) are bounded by the ranges above and cite evidence ids from the datasets above. They inherit the tier of the prior they move and are never verified on their own.

## Analogs (past events used for comparison)

17 of 19 are verified:
- **WHO:** COVID-19, SARS, H1N1, Ebola.
- **National agencies:** Japan's National Police Agency and Cabinet Office, Türkiye's AFAD, the governments of Nepal and China, the U.S. Bureau of Labor Statistics, the Bank of England, the European Commission.
- **Peer-reviewed studies:** Kolbe et al. 2010 (Haiti), Dawood et al. 2012 (H1N1), Amiti et al. 2019 (tariffs).
- **Company-reported figures filed with the SEC:** Apple for the iPhone, Tesla for the Model 3.

Two are guesses:
- **Vision Pro 2024:** an IDC estimate (an industry analyst), not company-reported.
- **Suez blockage 2021:** a Lloyd's List estimate (a trade publication).

## Gaps, by impact on headline numbers

1. **Label tiers in the product.** Add a tier to every prior and assumption, and show "unverified" on assumption chips and in the report appendix. This satisfies "clearly labeled" for all 48 guesses at once and is the cheapest step.
2. **City populations.** Replace Natural Earth `pop_max` with UN DESA World Urbanization Prospects (city agglomerations) and the EU JRC Global Human Settlement Layer population grid. This moves persona placement and quake exposure onto G sources.
3. **Epidemiology fatality curve.** Replace `IFR_BASE` with a peer-reviewed age-specific curve (for example Verity et al. 2020 for a COVID-like profile, or a published H1N1 systematic review) and keep `severity` as the scenario dial.
4. **Quick verified swaps:**
   - `export_share`: use WDI's per-country exports share of GDP.
   - `attenuation`: replace the uncited relation with a published intensity prediction equation (Allen, Wald & Worden 2012) and refit θ.
5. **Trade inputs:**
   - `product_share`: UN Comtrade (UN Statistics Division).
   - `multiplier`: OECD Trade in Value Added.
6. **Travel:** UN Tourism international arrivals in place of the uncalibrated `travel_rate`.
7. **Policy timing:** fit lockdown and border-closure thresholds and lags to the OxCGRT data rather than citing it.
8. **Analogs:** drop or mark the IDC and Lloyd's List estimates.
9. **No verified source expected:** launch behavior (awareness, capacity, competitor moves), recovery time constants, crowd bands. Keep these as labeled scenario assumptions after step 1.
