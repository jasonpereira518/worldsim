"""Actor policies in the engine, LLM off: they fire where the trigger crosses, move outcomes, and keep runs reproducible."""
import numpy as np

from worldsim import scale
from worldsim.engine import central, execute, make_config, prepare, sensitivity
from worldsim.models import Policy
from worldsim.parse import parse_prompt
from worldsim.world import world


def run_with(prompt, policies, rid='pol'):
    spec = parse_prompt(prompt, world())
    spec.policies = policies
    return prepare(make_config(spec, 7, rid, 'fixture'))


def pol(action, scope, metric):
    return Policy(id=f'{action}_{scope}'.replace(':', '_').replace(' ', '_').lower(), actor_id='gov', actor_label='Governments', action=action,
                  scope=scope, trigger_metric=metric)


def sim(run):
    return run.module.simulate(run.ctx, central(run.priors), np.random.default_rng([7, 0, 1]), detail=True)


def test_policy_fires_when_the_trigger_crosses():
    run = run_with('A magnitude 8.1 quake hits Istanbul', [pol('aid', 'all', 'deaths_reported')])
    thr = next(p.value for p in run.priors if p.key == 'pol_aid_all_threshold')
    tr = sim(run)
    [d] = tr.decisions
    assert tr.key[d['t']] >= thr and (d['t'] == 0 or tr.key[d['t'] - 1] < thr)
    lag = next(p.value for p in run.priors if p.key == 'pol_aid_all_lag')
    assert d['day'] == (d['t'] + max(1, round(lag / run.ctx.dt))) * run.ctx.dt
    assert any(e['title'] == 'Governments: international relief deployment' for e in tr.events)  # timeline marker in detail mode


def test_lockdown_policy_changes_the_outbreak_per_country():
    prompt = 'A novel H5N1 strain with human-to-human transmission emerges in Ho Chi Minh City'
    free, locked = run_with(prompt, []), run_with(prompt, [pol('lockdown', 'all', 'reported_per_100k')])
    a, b = sim(free), sim(locked)
    assert not a.decisions and b.decisions
    first = b.decisions[0]
    assert first['countries'] and len(first['countries']) < locked.ctx.C  # country metric: fires where it crossed, not everywhere
    assert b.key[-1] < a.key[-1]  # lockdowns lower deaths


def test_detail_run_matches_its_member_and_sensitivity_ranks_policies():
    run = run_with('A magnitude 8.1 quake hits Istanbul', [pol('aid', 'all', 'deaths_reported')])
    execute(run)  # asserts the detail run equals its ensemble member
    assert run.traj.decisions == run.ensemble[run.median].decisions
    rows = sensitivity(run, top=100)
    assert {'pol_aid_all_threshold', 'pol_aid_all_lag'} <= {r['key'] for r in rows}
    assert run.report['decisions']['policies'][0]['fired_runs'] == len(run.ensemble)


def test_no_response_branch_reruns_without_policies():
    run = run_with('A magnitude 8.1 quake hits Istanbul', [pol('aid', 'all', 'deaths_reported')])
    execute(run)
    [b] = [b for b in run.scale['branches'] if b['id'] == 'no_response']
    assert b['disable_policies'] and b['n'] > 0
    paired = np.median([tr.outcomes['deaths'] for tr in run.ensemble[:b['n']]])
    assert b['exceedance']['direction'] == ('at least' if b['size']['p50'] >= paired else 'at most')  # judged on the same members
    assert run.config.spec.policies  # restored after sizing


def test_retaliation_policy_replaces_the_coin_flip():
    prompt = 'The US imposes a 25% tariff on all imports from China'
    run = run_with(prompt, [pol('retaliation', 'all', 'lost_imports_busd')])
    tr = sim(run)
    assert [d['policy'] for d in tr.decisions] == ['retaliation_all']
    assert scale.reach_class(run.ctx, tr.affected_loc)[0] in ('multi_country', 'global')
