# Demo script — Milestone 6 (agents layer and scale)

About fifteen minutes. Steps 1–4 run with the LLM off and cost nothing. Step 5 spends API credit (at most $1 per run).

## 1. Test suites

```bash
cd services/sim && .venv/bin/python -m pytest -q
```

New in this milestone:
- `test_scale.py`: reach classes, magnitude bands, escalation paths sized on paired seeds.
- `test_agents.py`: every agent role against a scripted fake client: the tool loop, budgets, clamping, uncited proposals dropped, setup and re-plan in the stream, and replays that make no API calls.
- `test_policies.py`: actor policies fire where their trigger crosses, lockdowns lower deaths, the detail run still equals its ensemble member.
- `test_behavior.py`: crowd stances become banded priors; no stance means a bit-identical run.
- `test_scale_eval.py`: eleven historical events phrased as prompts (`evals/scale_cases.jsonl`), scored against the analog library on the real snapshot. Run it with `-s` to see the table. Today: reach class right in 7 of 11, headline outcome within 10× of the record in 7 of 10.

## 2. Scale card (LLM off)

Run "A magnitude 7.0 earthquake hits Port-au-Prince, Haiti". Under the scenario card, the Scale card shows:
- **Reach**: the share of ensemble runs that stayed local, regional, national, multi-country or global, from each run's people materially affected per location.
- **Magnitude**: the simulated median against past events of the same kind (Haiti 2010: comparable).
- **Escalation paths**: the most influential assumptions pushed into their tails, re-run on the same seeds, with how many base runs reach that size ("3 of 24 runs").

Open the report: section 2 has the same, plus the analog ladder on a log scale.

## 3. Plausibility gate (LLM off)

Run "A magnitude 11 earthquake hits Tokyo". The run stops with a clarifying question (the largest recorded earthquake is magnitude 9.5) and offers a magnitude 9.0 premise instead.

## 4. Decisions in the engine (LLM off)

Actor policies and crowd stances are spec fields, so they work without the agents; `tests/test_policies.py` and `tests/test_behavior.py` set them directly. A policy is a menu action (stay-at-home order, border closure, vaccine program, relief deployment, retaliatory tariffs), a scope (origin country, all countries, or a World Bank income group) and its priors: trigger threshold, lag and, where it applies, duration. It fires inside each run when its trigger crosses, so different runs act at different times.

## 5. Agents (LLM on, spends credit)

```bash
cd services/sim && WORLDSIM_LLM=on .venv/bin/uvicorn worldsim.api:app --port 8000
```

Run "A novel H5N1 strain with human-to-human transmission emerges in Ho Chi Minh City". In order:
1. **Intake** (Claude Opus 5.5) reads the prompt and judges plausibility.
2. **Setup**, shown in the agent roster under the scenario card with the cost of each role:
   - **Calibrator** (Claude Sonnet 5.5) moves module parameters toward country data and past events, inside their ranges. Its values show as assumption chips marked AI.
   - **Actors** (Sonnet) choose conditional policies from the module's menu: who acts, what they do, at what trigger.
   - **Crowds** (Claude Haiku 5.5) give a stance per population cluster: contact reduction and compliance, lower to higher than typical. Code turns each label into a range.
3. **Scale assessor** (Opus) writes its reach and magnitude forecast in the background, before the numbers exist.
4. **Actors, re-plan**: after a first look at 8 runs, the actors revise once. The full ensemble then runs.
5. Frames stream. Policy decisions appear on the timeline, for example "Lower middle income governments: stay-at-home order (Vietnam, …)".
6. **Reporter** (Opus) and **critic** (Sonnet) finish the report.

In the report:
- Section 2 opens with the reporter's scale paragraph and scores the assessor's forecast against the measurement.
- Section 10, "Who decided what": each policy, in how many runs it fired and the median day, and how the re-plan changed the median outcome over the same runs. "How populations behave" lists the crowd stances.
- Section 11 lists flags: rule checks (a policy that never fired, a "likely" path no run reached, a missed forecast) and the critic's.

Reload the run: the roster, policies, voices and report come back from the run file with no API calls.

## 6. Cost and caps

| Role | Model | Cap per run |
|---|---|---|
| Intake | Opus 5.5, low effort | $0.12 |
| Scale assessor | Opus 5.5, medium | $0.22 |
| Calibrator | Sonnet 5.5, medium | $0.10 |
| Actors, re-plan | Sonnet 5.5 | $0.10, $0.08 |
| Crowds | Haiku 5.5, low | $0.04 |
| Critic | Sonnet 5.5, low | $0.05 |
| Reporter | Opus 5.5 | within the run cap |
| Voices | Haiku 5.5; Sonnet 5.5 for institutions | $0.18, 60 calls |

The run cap is $1.00 and 80 calls (`WORLDSIM_LLM_MAX_USD`, `WORLDSIM_LLM_MAX_CALLS`). Setup roles get 45 s (`WORLDSIM_SETUP_CAP_S`); a role that fails, refuses, times out or runs out of budget leaves the rule-based defaults in place. Every call is logged to `runs/<id>.agents.jsonl` (role, model, cost, evidence ids, output).

## 7. Calibration log and evaluation

Each streamed run appends one line to `runs/calibration.jsonl`: the assessor's forecast next to the measured reach, headline percentiles, analog bands and branch counts, keyed by snapshot and engine version. `truth` is empty until a historical outcome is attached.

```bash
cd services/sim && WORLDSIM_LIVE_EVAL=1 .venv/bin/python -m pytest -q -s tests/test_scale_eval.py
```

This also scores the scale assessor's forecasts on the eleven cases (intake and assessor per case, up to about $4).
