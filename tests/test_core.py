"""Unit tests: verifier soundness, solver optimality vs baselines, floor invariance, memory."""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hmplan.casestudy import calibrated_params, run1, run2  # noqa: E402
from hmplan.errors import corrupt  # noqa: E402
from hmplan.generator import generate  # noqa: E402
from hmplan.heuristics import plan  # noqa: E402
from hmplan.memory import RouteMemory  # noqa: E402
from hmplan.mission import Mission, Stop  # noqa: E402
from hmplan.semantics import semantic_floor  # noqa: E402
from hmplan.solver import _lex_ge, solve  # noqa: E402
from hmplan.travel import TravelModel  # noqa: E402
from hmplan.verify import verify  # noqa: E402

PRM, _ = calibrated_params()


def _tm(inst):
    return TravelModel(inst, PRM)


def test_case_run1_feasible_without_intervention():
    inst = run1()
    r = solve(inst, _tm(inst), time_limit=60)
    assert r.report.feasible and r.report.n_int == 0 and r.report.charges == 0
    assert r.mission.n_legs == 6          # matches the six-trip field plan


def test_case_run2_requires_one_reschedule_with_sole_escort():
    inst = run2()
    r = solve(inst, _tm(inst), time_limit=60)
    assert r.report.feasible and r.report.n_int == 1 and r.report.e_short == 0
    assert "p1_dentist" in r.mission.starts


def test_case_run2_no_reschedule_when_any_caregiver_may_collect():
    inst = run2(escorts=())
    r = solve(inst, _tm(inst), time_limit=60)
    assert r.report.feasible and r.report.n_int == 0


def test_deployed_rule_reproduces_field_recommendation():
    inst = run2()
    m = plan(inst, _tm(inst), "rules")
    assert m.starts.get("p1_dentist") == 17 * 60 + 45   # 5:45 PM in the field run


def test_verifier_catches_escort_and_unknown_location():
    inst = run2()
    m = Mission(stops=[Stop("home", inst.day_start, inst.day_start),
                       Stop("school1", 0, 16 * 60, (), ("Child1",)),     # child boards with nobody aboard
                       Stop("Narnia", 0, 0),
                       Stop("home", 0, 0, ("Child1",))])
    rep = verify(inst, m, _tm(inst), check_consistency=False)
    codes = rep.codes()
    assert "ESCORT" in codes and "LOC_UNKNOWN" in codes and "UNAUTHORIZED_PICKUP" in codes


def test_solver_never_worse_than_baselines():
    for seed in range(12):
        inst = generate(seed)
        tm = _tm(inst)
        r = solve(inst, tm, time_limit=20)
        for lvl in ("rules", "context", "replay"):
            rep = verify(inst, plan(inst, tm, lvl), tm)
            assert _lex_ge(rep.phi, r.phi), (seed, lvl, rep.phi, r.phi)
        assert r.report.n_time_inconsistent == 0


def test_floor_makes_protection_invariant_to_label_errors():
    """Proposition 3: with the floor, interpretation errors cannot create protected violations."""
    for seed in range(8):
        inst = generate(seed)
        tm = _tm(inst)
        base = solve(inst, tm, time_limit=20).report
        rng = random.Random(seed)
        perceived, _ = corrupt(inst, 0.5, rng, record_errors=False)
        perceived = perceived.with_semantics(semantic_floor(perceived, {a.id: a.sem for a in perceived.activities}))
        r = solve(perceived, tm, time_limit=20)
        true_rep = verify(inst, r.mission, tm)
        if not r.timed_out:
            assert (true_rep.v_ops, true_rep.v_prot) <= (base.v_ops, base.v_prot), seed


def test_memory_detects_stale_context():
    inst = run1()
    mem = RouteMemory()
    m = plan(inst, _tm(inst), "rules")
    mem.save("Parent1", "2026-11-16", m, inst, created=0.0)
    assert mem.lookup("Parent1", "2026-11-16", inst)[1] == "hit"
    changed = inst.with_vehicle(soc0=0.30)
    assert mem.lookup("Parent1", "2026-11-16", changed)[1] == "stale"
    assert mem.lookup("Parent2", "2026-11-16", inst)[1] == "miss"
