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

from agent.agent_models import Candidate, DecisionState, PreferenceRule
from agent.planner import CandidateFactBuilder
from agent.llm_decision_advisor import LlmDecisionAdvisor, AdvisorContext, AdvisorDecision
from agent.model_decision_service import ModelDecisionService
from agent.safety_gate import SafetyGate


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
    items = [{"cargo": {"cargo_id": "X"}}]
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
    svc._last_decision_day = {}
    print("[PASS] model_decision_service instantiation")


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
    print("[PASS] all Phase 2 imports")


if __name__ == "__main__":
    test_imports()
    test_candidate_fact_builder_generates_wait()
    test_candidate_fact_builder_generates_take_order()
    test_candidate_hard_invalid_expired_cargo()
    test_safety_gate_wait()
    test_safety_gate_take_order_visible()
    test_safety_gate_take_order_invisible()
    test_safety_gate_reposition_valid()
    test_safety_gate_reposition_invalid()
    test_advisor_no_api()
    test_advisor_parse_valid_candidate_id()
    test_advisor_parse_unknown_candidate_id()
    test_advisor_parse_empty_candidate_id()
    test_model_decision_service_instantiation()
    test_find_candidate()
    print("\n=== ALL PHASE 2 TESTS PASSED ===")
