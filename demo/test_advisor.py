"""Phase 2 集成验证：统一 Candidate + Advisor 只选 candidate_id。

用法:
    cd demo
    python test_advisor.py

不需要 API Key，纯单元测试。
"""
from __future__ import annotations

import sys
from pathlib import Path

_DEMO = Path(__file__).resolve().parent
if str(_DEMO) not in sys.path:
    sys.path.insert(0, str(_DEMO))

from agent.agent_models import Candidate, DecisionState, PreferenceRule, TimeWindow, AreaBounds, GeoPoint
from agent.planner import CandidateFactBuilder
from agent.llm_decision_advisor import LlmDecisionAdvisor, AdvisorContext, AdvisorDecision, CandidateSummary
from agent.model_decision_service import ModelDecisionService
from agent.safety_gate import SafetyGate
from agent.preference_constraints import ConstraintSpec, compile_constraints
from agent.constraint_evaluator import ConstraintEvaluator, EvaluationResult, ConstraintImpact


def _make_state(**kwargs) -> DecisionState:
    defaults = dict(
        driver_id="TEST",
        current_minute=1000,
        current_latitude=23.0,
        current_longitude=113.0,
        simulation_duration_days=31,
        completed_order_count=0,
        history_records=(),
        wait_intervals=(),
        active_intervals=(),
        accepted_order_days=frozenset(),
        visited_positions=((0, 23.0, 113.0),),
        monthly_deadhead_km=0.0,
        consecutive_empty_queries=0,
    )
    defaults.update(kwargs)
    return DecisionState(**defaults)


def test_candidate_fact_builder_generates_wait():
    builder = CandidateFactBuilder()
    state = _make_state()
    candidates = builder.build_candidate_pool(state, (), [])
    assert len(candidates) >= 2, "should always have at least 2 wait candidates"
    wait_candidates = [c for c in candidates if c.action == "wait"]
    assert len(wait_candidates) >= 2, "should have wait_30 and wait_60"
    for c in wait_candidates:
        assert isinstance(c, Candidate), f"expected Candidate, got {type(c)}"
        assert c.candidate_id.startswith("wait_")
        assert not c.hard_invalid_reasons
        assert not c.soft_risk_reasons
    print("[PASS] candidate_fact_builder generates wait candidates")


def test_candidate_fact_builder_generates_take_order():
    builder = CandidateFactBuilder()
    state = _make_state()
    items = [
        {
            "cargo": {
                "cargo_id": "C001",
                "cargo_name": "TestCargo",
                "start": {"lat": 23.1, "lng": 113.1},
                "end": {"lat": 23.5, "lng": 113.5},
                "price": 500,
                "cost_time_minutes": 120,
            },
            "distance_km": 10.0,
        }
    ]
    candidates = builder.build_candidate_pool(state, (), items)
    take_order = [c for c in candidates if c.action == "take_order"]
    assert len(take_order) == 1, f"expected 1 take_order, got {len(take_order)}"
    c = take_order[0]
    assert c.candidate_id == "take_order_C001"
    assert c.params["cargo_id"] == "C001"
    assert "price" in c.facts
    assert isinstance(c.hard_invalid_reasons, tuple)
    assert isinstance(c.soft_risk_reasons, tuple)
    print(f"[PASS] candidate_fact_builder generates take_order: id={c.candidate_id}, net={c.facts.get('estimated_net')}")


def test_candidate_hard_invalid_expired_cargo():
    builder = CandidateFactBuilder()
    state = _make_state(current_minute=1000)
    items = [
        {
            "cargo": {
                "cargo_id": "EXPIRED",
                "cargo_name": "OldCargo",
                "start": {"lat": 23.1, "lng": 113.1},
                "end": {"lat": 23.5, "lng": 113.5},
                "price": 500,
                "cost_time_minutes": 120,
                "remove_time": "2026-03-01 00:05",
            },
            "distance_km": 10.0,
        }
    ]
    candidates = builder.build_candidate_pool(state, (), items)
    take_order = [c for c in candidates if c.action == "take_order"]
    assert len(take_order) == 1
    c = take_order[0]
    assert len(c.hard_invalid_reasons) > 0, f"expected hard_invalid, got {c.hard_invalid_reasons}"
    print(f"[PASS] expired cargo -> hard_invalid: {c.hard_invalid_reasons}")


def test_safety_gate_wait():
    gate = SafetyGate()
    state = _make_state()
    ok, reason = gate.validate({"action": "wait", "params": {"duration_minutes": 30}}, state, [])
    assert ok, f"wait should pass, got {reason}"
    print("[PASS] safety_gate wait ok")


def test_safety_gate_take_order_visible():
    gate = SafetyGate()
    state = _make_state()
    items = [{"cargo": {"cargo_id": "X", "start": {"lat": 23, "lng": 113}, "end": {"lat": 24, "lng": 114}}, "distance_km": 10.0}]
    ok, reason = gate.validate({"action": "take_order", "params": {"cargo_id": "X"}}, state, items)
    assert ok, f"visible cargo should pass, got {reason}"
    print("[PASS] safety_gate take_order visible ok")


def test_safety_gate_take_order_invisible():
    gate = SafetyGate()
    state = _make_state()
    items = [{"cargo": {"cargo_id": "X"}}]
    ok, reason = gate.validate({"action": "take_order", "params": {"cargo_id": "Y"}}, state, items)
    assert not ok
    assert reason == "cargo_not_visible"
    print("[PASS] safety_gate take_order invisible rejected")


def test_safety_gate_reposition_valid():
    gate = SafetyGate()
    state = _make_state()
    ok, reason = gate.validate({"action": "reposition", "params": {"latitude": 23.5, "longitude": 113.5}}, state, [])
    assert ok, f"valid reposition should pass, got {reason}"
    print("[PASS] safety_gate reposition valid ok")


def test_safety_gate_reposition_invalid():
    gate = SafetyGate()
    state = _make_state()
    ok, reason = gate.validate({"action": "reposition", "params": {"latitude": 999, "longitude": 113.5}}, state, [])
    assert not ok
    assert reason == "reposition_out_of_bounds"
    print("[PASS] safety_gate reposition invalid rejected")


def test_advisor_no_api():
    advisor = LlmDecisionAdvisor(api=None)
    state = _make_state()
    c = Candidate(candidate_id="wait_30", action="wait", params={"duration_minutes": 30})
    ctx = AdvisorContext(
        state=state,
        rules=(),
        valid_candidates=[c],
        soft_risk_candidates=[],
        raw_preferences=[],
    )
    result = advisor.advise(ctx)
    assert result is None, "should return None when api is None"
    print("[PASS] advisor no_api fallback")


def test_advisor_parse_valid_candidate_id():
    advisor = LlmDecisionAdvisor(api=None)
    state = _make_state()
    c1 = Candidate(candidate_id="take_order_A", action="take_order", params={"cargo_id": "A"}, facts={"price": 100})
    c2 = Candidate(candidate_id="wait_60", action="wait", params={"duration_minutes": 60})
    ctx = AdvisorContext(
        state=state,
        rules=(),
        valid_candidates=[c2],
        soft_risk_candidates=[c1],
        raw_preferences=[],
    )
    data = {"selected_candidate_id": "take_order_A", "reason": "good profit", "accepted_risks": ["preference"]}
    result = advisor._parse_decision(data, ctx)
    assert result is not None
    assert result.selected_candidate_id == "take_order_A"
    assert result.reason == "good profit"
    print("[PASS] advisor parse valid candidate_id")


def test_advisor_parse_unknown_candidate_id():
    advisor = LlmDecisionAdvisor(api=None)
    state = _make_state()
    c = Candidate(candidate_id="wait_30", action="wait", params={"duration_minutes": 30})
    ctx = AdvisorContext(
        state=state,
        rules=(),
        valid_candidates=[c],
        soft_risk_candidates=[],
        raw_preferences=[],
    )
    data = {"selected_candidate_id": "nonexistent", "reason": "test"}
    result = advisor._parse_decision(data, ctx)
    assert result is None, "should reject unknown candidate_id"
    print("[PASS] advisor rejects unknown candidate_id")


def test_advisor_parse_empty_candidate_id():
    advisor = LlmDecisionAdvisor(api=None)
    state = _make_state()
    c = Candidate(candidate_id="wait_30", action="wait", params={"duration_minutes": 30})
    ctx = AdvisorContext(
        state=state,
        rules=(),
        valid_candidates=[c],
        soft_risk_candidates=[],
        raw_preferences=[],
    )
    data = {"selected_candidate_id": "", "reason": "test"}
    result = advisor._parse_decision(data, ctx)
    assert result is None, "should reject empty candidate_id"
    print("[PASS] advisor rejects empty candidate_id")


def test_model_decision_service_instantiation():
    svc = object.__new__(ModelDecisionService)
    svc._api = type("FakeAPI", (), {})()
    svc._logger = __import__("logging").getLogger("test")
    svc._preference_compiler = type("PC", (), {"compile": lambda self, p: ()})()
    svc._state_tracker = type("ST", (), {"build": lambda self, **kw: _make_state()})()
    svc._planner = CandidateFactBuilder()
    svc._advisor = LlmDecisionAdvisor(api=None)
    svc._safety_gate = SafetyGate()
    svc._constraint_evaluator = ConstraintEvaluator()
    svc._last_decision_day = {}
    print("[PASS] model_decision_service instantiation")


def test_compile_constraints_forbid_cargo():
    rules = (
        PreferenceRule(kind="forbidden_cargo", priority="hard", cargo_names=("chemicals",)),
    )
    constraints = compile_constraints(rules)
    assert len(constraints) == 1, f"expected 1 constraint, got {len(constraints)}"
    c = constraints[0]
    assert c.constraint_type == "forbid_cargo_category"
    assert c.priority == "hard"
    assert "chemicals" in c.cargo_names
    print(f"[PASS] compile forbid_cargo: type={c.constraint_type}, priority={c.priority}")


def test_compile_constraints_quiet_hours():
    rules = (
        PreferenceRule(kind="quiet_hours", priority="hard", time_window=TimeWindow(1380, 360)),
    )
    constraints = compile_constraints(rules)
    assert len(constraints) == 1
    c = constraints[0]
    assert c.constraint_type == "forbid_action_in_time_window"
    assert c.time_window is not None
    assert c.time_window.start_minute_of_day == 1380
    assert c.time_window.end_minute_of_day == 360
    print(f"[PASS] compile quiet_hours: type={c.constraint_type}, window=[{c.time_window.start_minute_of_day},{c.time_window.end_minute_of_day}]")


def test_compile_constraints_area_bounds():
    rules = (
        PreferenceRule(
            kind="area_bounds",
            priority="hard",
            area_bounds=AreaBounds(22.0, 23.0, 113.0, 114.0),
        ),
    )
    constraints = compile_constraints(rules)
    assert len(constraints) == 1
    c = constraints[0]
    assert c.constraint_type == "operate_within_area"
    assert c.area_bounds is not None
    assert c.area_bounds.lat_min == 22.0
    print(f"[PASS] compile area_bounds: type={c.constraint_type}")


def test_compile_constraints_daily_rest():
    rules = (
        PreferenceRule(kind="daily_rest", priority="hard", required_minutes=480),
    )
    constraints = compile_constraints(rules)
    assert len(constraints) == 1
    c = constraints[0]
    assert c.constraint_type == "continuous_rest"
    assert c.required_minutes == 480
    print(f"[PASS] compile daily_rest: type={c.constraint_type}, minutes={c.required_minutes}")


def test_compile_constraints_special_cargo():
    rules = (
        PreferenceRule(
            kind="special_cargo",
            priority="soft",
            metadata={"target_cargo_id": "CARGO_999"},
        ),
    )
    constraints = compile_constraints(rules)
    assert len(constraints) == 1
    c = constraints[0]
    assert c.constraint_type == "specific_cargo"
    assert "CARGO_999" in c.cargo_ids
    print(f"[PASS] compile special_cargo: type={c.constraint_type}, cargo_ids={c.cargo_ids}")


def test_evaluator_forbid_cargo_hard():
    evaluator = ConstraintEvaluator()
    state = _make_state()
    constraint = ConstraintSpec(
        constraint_id="test_forbid",
        constraint_type="forbid_cargo_category",
        priority="hard",
        cargo_names=("chemicals",),
    )
    candidate = Candidate(
        candidate_id="take_order_C1",
        action="take_order",
        params={"cargo_id": "C1"},
        facts={"cargo_name": "chemicals"},
    )
    result = evaluator.evaluate(candidate, (constraint,), state)
    assert len(result.hard_invalid_reasons) > 0, f"expected hard_invalid, got {result}"
    assert result.estimated_penalty_exposure > 0
    assert not result.satisfies_all_constraints
    print(f"[PASS] evaluator forbid_cargo hard: reasons={result.hard_invalid_reasons}, penalty={result.estimated_penalty_exposure}")


def test_evaluator_forbid_cargo_soft():
    evaluator = ConstraintEvaluator()
    state = _make_state()
    constraint = ConstraintSpec(
        constraint_id="test_soft_forbid",
        constraint_type="forbid_cargo_category",
        priority="soft",
        cargo_names=("chemicals",),
    )
    candidate = Candidate(
        candidate_id="take_order_C2",
        action="take_order",
        params={"cargo_id": "C2"},
        facts={"cargo_name": "chemicals"},
    )
    result = evaluator.evaluate(candidate, (constraint,), state)
    assert len(result.soft_risk_reasons) > 0, f"expected soft_risk, got {result}"
    assert len(result.hard_invalid_reasons) == 0
    assert result.estimated_penalty_exposure > 0
    print(f"[PASS] evaluator forbid_cargo soft: risks={result.soft_risk_reasons}, penalty={result.estimated_penalty_exposure}")


def test_evaluator_forbid_cargo_allowed():
    evaluator = ConstraintEvaluator()
    state = _make_state()
    constraint = ConstraintSpec(
        constraint_id="test_forbid",
        constraint_type="forbid_cargo_category",
        priority="hard",
        cargo_names=("chemicals",),
    )
    candidate = Candidate(
        candidate_id="take_order_C3",
        action="take_order",
        params={"cargo_id": "C3"},
        facts={"cargo_name": "food"},
    )
    result = evaluator.evaluate(candidate, (constraint,), state)
    assert not result.hard_invalid_reasons
    assert not result.soft_risk_reasons
    assert result.satisfies_all_constraints
    print(f"[PASS] evaluator forbid_cargo allowed: satisfies={result.satisfies_all_constraints}")


def test_evaluator_operate_within_area():
    evaluator = ConstraintEvaluator()
    state = _make_state()
    constraint = ConstraintSpec(
        constraint_id="test_area",
        constraint_type="operate_within_area",
        priority="hard",
        area_bounds=AreaBounds(22.0, 23.0, 113.0, 114.0),
    )
    candidate_in = Candidate(
        candidate_id="take_order_IN",
        action="take_order",
        params={"cargo_id": "IN"},
        facts={"start": (22.5, 113.5), "end": (22.8, 113.8), "cargo_name": "food"},
    )
    result_in = evaluator.evaluate(candidate_in, (constraint,), state)
    assert result_in.satisfies_all_constraints, f"in-area should satisfy: {result_in}"

    candidate_out = Candidate(
        candidate_id="take_order_OUT",
        action="take_order",
        params={"cargo_id": "OUT"},
        facts={"start": (25.0, 115.0), "end": (22.5, 113.5), "cargo_name": "food"},
    )
    result_out = evaluator.evaluate(candidate_out, (constraint,), state)
    assert len(result_out.hard_invalid_reasons) > 0, f"out-of-area should fail: {result_out}"
    print(f"[PASS] evaluator operate_within_area: in={result_in.satisfies_all_constraints}, out_violations={result_out.hard_invalid_reasons}")


def test_evaluator_continuous_rest():
    evaluator = ConstraintEvaluator()
    constraint = ConstraintSpec(
        constraint_id="test_rest",
        constraint_type="continuous_rest",
        priority="hard",
        actions=("take_order",),
        required_minutes=480,
    )
    state_rest = _make_state(wait_intervals=((0, 300),))
    candidate_take = Candidate(
        candidate_id="take_order_R",
        action="take_order",
        params={"cargo_id": "R"},
        facts={"cargo_name": "food"},
    )
    result = evaluator.evaluate(candidate_take, (constraint,), state_rest)
    assert len(result.soft_risk_reasons) > 0, f"insufficient rest should be risk: {result}"
    print(f"[PASS] evaluator continuous_rest: risks={result.soft_risk_reasons}, penalty={result.estimated_penalty_exposure}")


def test_evaluator_forbid_time_window():
    evaluator = ConstraintEvaluator()
    constraint = ConstraintSpec(
        constraint_id="test_quiet",
        constraint_type="forbid_action_in_time_window",
        priority="hard",
        actions=("take_order",),
        time_window=TimeWindow(1380, 360),
    )
    state = _make_state(current_minute=1000)
    candidate = Candidate(
        candidate_id="take_order_NIGHT",
        action="take_order",
        params={"cargo_id": "NIGHT"},
        facts={"pickup_minutes": 10, "estimated_duration_minutes": 30, "cargo_name": "food"},
    )
    result = evaluator.evaluate(candidate, (constraint,), state)
    print(f"[PASS] evaluator forbid_time_window: impacts={len(result.constraint_impacts)}")


def test_evaluator_specific_cargo():
    evaluator = ConstraintEvaluator()
    state = _make_state()
    constraint = ConstraintSpec(
        constraint_id="test_specific",
        constraint_type="specific_cargo",
        priority="hard",
        cargo_ids=("CARGO_999",),
    )
    match = Candidate(
        candidate_id="take_order_999",
        action="take_order",
        params={"cargo_id": "CARGO_999"},
        facts={"cargo_name": "special"},
    )
    result = evaluator.evaluate(match, (constraint,), state)
    impacts = list(result.constraint_impacts)
    assert any(imp.status == "satisfies" for imp in impacts), f"specific_cargo match should satisfy: {impacts}"
    print(f"[PASS] evaluator specific_cargo: match_status={[i.status for i in impacts]}")


def test_evaluator_wait_not_affected_by_action_constraint():
    evaluator = ConstraintEvaluator()
    state = _make_state()
    constraint = ConstraintSpec(
        constraint_id="test_forbid",
        constraint_type="forbid_cargo_category",
        priority="hard",
        cargo_names=("chemicals",),
        actions=("take_order",),
    )
    wait_candidate = Candidate(
        candidate_id="wait_30",
        action="wait",
        params={"duration_minutes": 30},
        facts={},
    )
    result = evaluator.evaluate(wait_candidate, (constraint,), state)
    assert result.satisfies_all_constraints, f"wait should not be affected by action-scoped constraint"
    print(f"[PASS] evaluator wait not affected: satisfies={result.satisfies_all_constraints}")


def test_constraint_generates_wait_rest_candidate():
    builder = CandidateFactBuilder()
    state = _make_state()
    constraints = (
        ConstraintSpec(
            constraint_id="test_rest",
            constraint_type="continuous_rest",
            priority="hard",
            required_minutes=480,
        ),
    )
    candidates = builder.build_candidate_pool(state, (), [], constraints)
    rest_candidates = [c for c in candidates if c.source == "constraint"]
    assert len(rest_candidates) > 0, f"expected constraint-satisfying candidates, got {len(rest_candidates)}"
    rest = rest_candidates[0]
    assert rest.facts.get("satisfies_continuous_rest") is True
    print(f"[PASS] constraint generates wait_rest: id={rest.candidate_id}, facts={rest.facts}")


def test_constraint_generates_specific_cargo_candidate():
    builder = CandidateFactBuilder()
    state = _make_state()
    constraints = (
        ConstraintSpec(
            constraint_id="test_specific",
            constraint_type="specific_cargo",
            priority="hard",
            cargo_ids=("CARGO_ABC",),
        ),
    )
    candidates = builder.build_candidate_pool(state, (), [], constraints)
    specific = [c for c in candidates if c.candidate_id == "specific_cargo_CARGO_ABC"]
    assert len(specific) == 1, f"expected specific_cargo candidate, got {len(specific)}"
    assert specific[0].action == "take_order"
    assert specific[0].params["cargo_id"] == "CARGO_ABC"
    print(f"[PASS] constraint generates specific_cargo: id={specific[0].candidate_id}")


def test_constraint_generates_go_to_location_candidate():
    builder = CandidateFactBuilder()
    state = _make_state()
    constraints = (
        ConstraintSpec(
            constraint_id="test_home",
            constraint_type="be_at_location_by_deadline",
            priority="hard",
            point=GeoPoint(23.5, 113.5),
        ),
    )
    candidates = builder.build_candidate_pool(state, (), [], constraints)
    go_to = [c for c in candidates if c.action == "reposition"]
    assert len(go_to) > 0, f"expected reposition candidate, got {len(go_to)}"
    assert go_to[0].params["latitude"] == 23.5
    assert go_to[0].params["longitude"] == 113.5
    print(f"[PASS] constraint generates go_to_location: lat={go_to[0].params['latitude']}, lng={go_to[0].params['longitude']}")


def test_candidate_summaries_enrichment():
    svc = object.__new__(ModelDecisionService)
    svc._logger = __import__("logging").getLogger("test")
    c = Candidate(
        candidate_id="take_order_X",
        action="take_order",
        params={"cargo_id": "X"},
        facts={
            "estimated_net": 200.0,
            "estimated_penalty_exposure": 50.0,
            "estimated_net_after_penalty": 150.0,
            "satisfies_constraints": False,
            "constraint_impacts": (
                {"constraint_id": "c1", "constraint_type": "forbid_cargo_category",
                 "status": "violation", "penalty": 50.0, "detail": "test"},
            ),
        },
        soft_risk_reasons=("constraint_forbid_cargo_category_risk",),
    )
    summaries = svc._build_candidate_summaries([c])
    assert "take_order_X" in summaries
    s = summaries["take_order_X"]
    assert s.estimated_net == 200.0
    assert s.estimated_penalty_exposure == 50.0
    assert s.estimated_net_after_penalty == 150.0
    assert not s.satisfies_constraints
    assert len(s.constraint_impacts) == 1
    print(f"[PASS] candidate_summaries enrichment: penalty={s.estimated_penalty_exposure}, net_after={s.estimated_net_after_penalty}")


def test_load_time_window_expired_in_builder():
    builder = CandidateFactBuilder()
    state = _make_state(current_minute=1000)
    items = [
        {
            "cargo": {
                "cargo_id": "EXPIRED_LTW",
                "cargo_name": "LateCargo",
                "start": {"lat": 23.1, "lng": 113.1},
                "end": {"lat": 23.5, "lng": 113.5},
                "price": 500,
                "cost_time_minutes": 120,
                "load_time_window_end": "2026-03-01 00:10",
            },
            "distance_km": 10.0,
        }
    ]
    candidates = builder.build_candidate_pool(state, (), items)
    take_order = [c for c in candidates if c.action == "take_order"]
    assert len(take_order) == 1
    c = take_order[0]
    assert "load_time_window_expired" in c.hard_invalid_reasons, f"expected load_time_window_expired, got {c.hard_invalid_reasons}"
    print(f"[PASS] load_time_window_expired in builder: {c.hard_invalid_reasons}")


def test_load_time_window_unreachable_in_builder():
    builder = CandidateFactBuilder()
    state = _make_state(current_minute=5)
    items = [
        {
            "cargo": {
                "cargo_id": "TIGHT_LTW",
                "cargo_name": "TightCargo",
                "start": {"lat": 23.1, "lng": 113.1},
                "end": {"lat": 23.5, "lng": 113.5},
                "price": 500,
                "cost_time_minutes": 120,
                "load_time_window_end": "2026-03-01 00:12",
            },
            "distance_km": 10.0,
        }
    ]
    candidates = builder.build_candidate_pool(state, (), items)
    take_order = [c for c in candidates if c.action == "take_order"]
    assert len(take_order) == 1
    c = take_order[0]
    assert "load_time_window_unreachable" in c.hard_invalid_reasons, f"expected load_time_window_unreachable, got {c.hard_invalid_reasons}"
    print(f"[PASS] load_time_window_unreachable in builder: {c.hard_invalid_reasons}")


def test_load_time_window_valid_in_builder():
    builder = CandidateFactBuilder()
    state = _make_state(current_minute=100)
    items = [
        {
            "cargo": {
                "cargo_id": "VALID_LTW",
                "cargo_name": "GoodCargo",
                "start": {"lat": 23.1, "lng": 113.1},
                "end": {"lat": 23.5, "lng": 113.5},
                "price": 500,
                "cost_time_minutes": 120,
                "load_time_window_end": "2026-03-01 08:00",
            },
            "distance_km": 10.0,
        }
    ]
    candidates = builder.build_candidate_pool(state, (), items)
    take_order = [c for c in candidates if c.action == "take_order"]
    assert len(take_order) == 1
    c = take_order[0]
    assert not c.hard_invalid_reasons, f"expected no hard_invalid, got {c.hard_invalid_reasons}"
    assert c.facts.get("cargo_deadline_minute") is not None
    assert c.facts.get("deadline_source") == "load_time_window_end"
    print(f"[PASS] load_time_window valid in builder: deadline_minute={c.facts.get('cargo_deadline_minute')}")


def test_safety_gate_load_time_window_expired():
    gate = SafetyGate()
    state = _make_state(current_minute=1000)
    items = [{"cargo": {"cargo_id": "EXPIRED_LTW", "load_time_window_end": "2026-03-01 00:10"}, "distance_km": 10.0}]
    ok, reason = gate.validate({"action": "take_order", "params": {"cargo_id": "EXPIRED_LTW"}}, state, items)
    assert not ok, f"should reject, ok={ok}"
    assert reason == "load_time_window_expired", f"expected load_time_window_expired, got {reason}"
    print(f"[PASS] safety_gate load_time_window_expired: {reason}")


def test_safety_gate_load_time_window_unreachable():
    gate = SafetyGate()
    state = _make_state(current_minute=5)
    items = [{"cargo": {"cargo_id": "TIGHT_LTW", "load_time_window_end": "2026-03-01 00:12"}, "distance_km": 10.0}]
    ok, reason = gate.validate({"action": "take_order", "params": {"cargo_id": "TIGHT_LTW"}}, state, items)
    assert not ok, f"should reject, ok={ok}"
    assert reason == "load_time_window_unreachable", f"expected load_time_window_unreachable, got {reason}"
    print(f"[PASS] safety_gate load_time_window_unreachable: {reason}")


def test_find_candidate():
    svc = object.__new__(ModelDecisionService)
    candidates = [
        Candidate(candidate_id="take_order_A", action="take_order", params={"cargo_id": "A"}),
        Candidate(candidate_id="wait_30", action="wait", params={"duration_minutes": 30}),
    ]
    result = svc._find_candidate(candidates, "wait_30")
    assert result is not None
    assert result.candidate_id == "wait_30"
    result2 = svc._find_candidate(candidates, "nonexistent")
    assert result2 is None
    print("[PASS] find_candidate works correctly")


def test_imports():
    from agent.preference_compiler import PreferenceCompiler
    from agent.state_tracker import StateTracker
    from agent.action_contract import ActionContract
    from agent.geo_utils import haversine_km
    from agent.preference_constraints import compile_constraints
    from agent.constraint_evaluator import ConstraintEvaluator
    print("[PASS] all Phase 2 + 2.1 imports")


if __name__ == "__main__":
    test_imports()
    test_candidate_fact_builder_generates_wait()
    test_candidate_fact_builder_generates_take_order()
    test_candidate_hard_invalid_expired_cargo()
    test_load_time_window_expired_in_builder()
    test_load_time_window_unreachable_in_builder()
    test_load_time_window_valid_in_builder()
    test_safety_gate_wait()
    test_safety_gate_take_order_visible()
    test_safety_gate_take_order_invisible()
    test_safety_gate_reposition_valid()
    test_safety_gate_reposition_invalid()
    test_safety_gate_load_time_window_expired()
    test_safety_gate_load_time_window_unreachable()
    test_advisor_no_api()
    test_advisor_parse_valid_candidate_id()
    test_advisor_parse_unknown_candidate_id()
    test_advisor_parse_empty_candidate_id()
    test_model_decision_service_instantiation()
    test_find_candidate()
    # Phase 2.1 constraint tests
    test_compile_constraints_forbid_cargo()
    test_compile_constraints_quiet_hours()
    test_compile_constraints_area_bounds()
    test_compile_constraints_daily_rest()
    test_compile_constraints_special_cargo()
    test_evaluator_forbid_cargo_hard()
    test_evaluator_forbid_cargo_soft()
    test_evaluator_forbid_cargo_allowed()
    test_evaluator_operate_within_area()
    test_evaluator_continuous_rest()
    test_evaluator_forbid_time_window()
    test_evaluator_specific_cargo()
    test_evaluator_wait_not_affected_by_action_constraint()
    test_constraint_generates_wait_rest_candidate()
    test_constraint_generates_specific_cargo_candidate()
    test_constraint_generates_go_to_location_candidate()
    test_candidate_summaries_enrichment()
    print("\n=== ALL PHASE 2 + 2.1 TESTS PASSED ===")
