"""Crowd stances: labels become behavior priors in code-defined bands; no stance means today's runs, bit for bit."""
import numpy as np

from worldsim import agents, llm
from worldsim.engine import central, make_config, prepare, refresh_priors, sample_params
from worldsim.models import CrowdStance
from worldsim.modules.base import STANCE_BANDS, behavior
from worldsim.parse import parse_prompt
from worldsim.world import world

from test_agents import final, llm_on  # noqa: F401 - fixture

OUTBREAK = 'A novel H5N1 strain with human-to-human transmission emerges in Ho Chi Minh City'


def run_with(behavior_=()):
    spec = parse_prompt(OUTBREAK, world())
    spec.behavior = list(behavior_)
    return prepare(make_config(spec, 7, 'beh', 'fixture'))


def deaths(run):
    return run.module.simulate(run.ctx, central(run.priors), np.random.default_rng([7, 0, 1]), detail=False).key[-1]


def test_typical_stance_changes_nothing():
    base = run_with()
    typical = run_with([CrowdStance(cluster='group:High income', label='High income countries', stances={'contact_reduction': 'typical'})])
    assert not [p for p in typical.priors if p.key.startswith('beh_')]
    assert deaths(typical) == deaths(base)


def test_stance_becomes_a_banded_prior_and_moves_the_outcome():
    st = CrowdStance(cluster='origin', label='Vietnam (origin)', stances={'contact_reduction': 'much lower', 'compliance': 'typical'})
    base, run = run_with(), run_with([st])
    [p] = [p for p in run.priors if p.key.startswith('beh_')]
    assert p.key == 'beh_origin_contact_reduction' and (p.low, p.high) == STANCE_BANDS['much lower'] and p.origin == 'llm'
    assert deaths(run) > deaths(base)  # people cut contacts less, so more die
    # appended after the module's priors: the module's draws are unchanged
    rng = lambda: np.random.default_rng([7, 3])  # noqa: E731
    a, b = sample_params(base.priors, rng()), sample_params(run.priors, rng())
    assert all(a[k] == b[k] for k in a)


def test_origin_overrides_its_income_group():
    run = run_with([CrowdStance(cluster='origin', label='o', stances={'compliance': 'higher'}),
                    CrowdStance(cluster='group:Lower middle income', label='g', stances={'compliance': 'lower'})])
    p = central(run.priors)
    m = behavior(run.ctx, p, 'compliance')
    origin_c = run.ctx.loc_c[run.ctx.origin_loc]
    assert m[origin_c] == p['beh_origin_compliance'] > 1 and (m < 1).any() and (m == 1).any()


CROWDS = {'stances': [
    {'cluster': 'origin', 'stance': {'contact_reduction': 'higher', 'compliance': 'much higher'},
     'rationale': 'Dense cities with recent outbreak experience.', 'evidence': ['cluster:origin', 'cluster:invented']},
    {'cluster': 'origin', 'stance': {'contact_reduction': 'lower', 'compliance': 'lower'}, 'rationale': 'Second answer for the same cluster.', 'evidence': []},
    {'cluster': 'group:Atlantis', 'stance': {'contact_reduction': 'lower', 'compliance': 'lower'}, 'rationale': 'Unknown cluster.', 'evidence': []},
    {'cluster': 'group:Upper middle income', 'stance': {'contact_reduction': 'lower', 'compliance': 'sideways'}, 'rationale': 'Fewer can stay home.', 'evidence': []},
]}


def test_crowds_agent_labels_only(llm_on):  # noqa: F811
    llm_on({'judge how populations': [final(CROWDS)]})
    run = run_with()
    assert agents.setup_roles(run) == ['calibrator', 'actors', 'crowds']
    step, apply = agents.crowds(run, llm.Budget(), [])
    assert step.status == 'done' and step.summary == 'Stances for 2 population clusters; 3 behaviors differ from typical.'
    apply(run.config.spec)
    origin, low = run.config.spec.behavior
    assert origin.stances == {'contact_reduction': 'higher', 'compliance': 'much higher'} and origin.evidence == ['cluster:origin']
    assert low.stances == {'contact_reduction': 'lower'}  # invalid label dropped
    refresh_priors(run)
    assert {p.key for p in run.priors if p.key.startswith('beh_')} == {'beh_origin_contact_reduction', 'beh_origin_compliance',
                                                                       'beh_group_upper_middle_income_contact_reduction'}
