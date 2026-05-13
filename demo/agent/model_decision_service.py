from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from agent.agent_models import Candidate, DecisionState
from agent.constraint_evaluator import ConstraintEvaluator, ConstraintImpact, EvaluationResult
from agent.constraint_runtime import compute_constraint_runtime_state, ConstraintRuntimeState
from agent.llm_decision_advisor import AdvisorContext, AdvisorDecision, CandidateSummary, LlmDecisionAdvisor
from agent.planner import CandidateFactBuilder, estimate_scan_cost
from agent.preference_compiler import PreferenceCompiler
from agent.preference_constraints import ConstraintSpec, compile_constraints
from agent.safety_gate import SafetyGate
from agent.state_tracker import StateTracker
from simkit.ports import SimulationApiPort


class ModelDecisionService:
    def __init__(self, api: SimulationApiPort) -> None:
        self._api = api
        self._logger = logging.getLogger("agent.decision_service")
        self._preference_compiler = PreferenceCompiler(api)
        self._state_tracker = StateTracker()
        self._planner = CandidateFactBuilder()
        self._advisor = LlmDecisionAdvisor(api)
        self._safety_gate = SafetyGate()
        self._constraint_evaluator = ConstraintEvaluator()
        self._last_decision_day: dict[str, int] = {}

    def decide(self, driver_id: str) -> dict[str, Any]:
        status = self._api.get_driver_status(driver_id)
        latitude = float(status["current_lat"])
        longitude = float(status["current_lng"])

        cargo_response = self._api.query_cargo(driver_id=driver_id, latitude=latitude, longitude=longitude)
        items = cargo_response.get("items", [])
        if not isinstance(items, list):
            items = []

        history = self._api.query_decision_history(driver_id, -1)
        preferences = list(status.get("preferences") or [])
        rules = self._preference_compiler.compile(preferences)
        constraints = compile_constraints(rules)
        state = self._state_tracker.build(
            driver_id=driver_id,
            status=status,
            history_payload=history,
            scan_cost_minutes=estimate_scan_cost(len(items)),
            empty_query=len(items) == 0,
        )

        visible_cargo_ids: set[str] = set()
        for item in items:
            cargo = item.get("cargo") if isinstance(item.get("cargo"), dict) else {}
            cid = str(cargo.get("cargo_id") or "").strip()
            if cid:
                visible_cargo_ids.add(cid)

        runtime = compute_constraint_runtime_state(
            state.history_records, state.current_minute, constraints, visible_cargo_ids
        )

        log_entry: dict[str, Any] = {"driver_id": driver_id, "step": len(state.history_records)}
        try:
            all_candidates = self._planner.build_candidate_pool(state, rules, items, constraints, runtime)
            all_candidates = self._evaluate_constraints(all_candidates, constraints, state, runtime)

            valid_candidates = [c for c in all_candidates if not c.hard_invalid_reasons and not c.soft_risk_reasons]
            soft_risk_candidates = [c for c in all_candidates if not c.hard_invalid_reasons and c.soft_risk_reasons]
            hard_invalid_candidates = [c for c in all_candidates if c.hard_invalid_reasons]
            satisfy_candidates = [c for c in all_candidates if c.source == "constraint_satisfy"]

            log_entry.update({
                "day": state.current_day,
                "minute": state.minute_of_day,
                "visible_cargo_count": len(items),
                "candidate_count": len(all_candidates),
                "valid_count": len(valid_candidates),
                "soft_risk_count": len(soft_risk_candidates),
                "hard_invalid_count": len(hard_invalid_candidates),
                "satisfy_candidate_count": len(satisfy_candidates),
                "satisfy_candidate_types": list({
                    str(c.facts.get("satisfies_constraint_type") or c.facts.get("constraint_type") or "")
                    for c in satisfy_candidates
                }),
                "rest_state": {
                    "current_rest_streak": runtime.rest.current_rest_streak_minutes,
                    "max_rest_streak_today": runtime.rest.max_rest_streak_today,
                } if runtime else {},
            })

            executable = valid_candidates + soft_risk_candidates
            if not executable:
                action = self._fallback_wait(state, "no_candidates_available")
                self._log_fallback(log_entry, "no_candidates_available", action)
                return action

            recent_actions = self._recent_actions(state)
            raw_preferences = [self._preference_text(p) for p in preferences]
            candidate_summaries = self._build_candidate_summaries(all_candidates)

            advisor_result = self._advisor.advise(
                AdvisorContext(
                    state=state,
                    rules=rules,
                    valid_candidates=valid_candidates,
                    soft_risk_candidates=soft_risk_candidates,
                    raw_preferences=raw_preferences,
                    recent_actions=recent_actions,
                    trigger_reason="normal_candidate_decision",
                    candidate_summaries=candidate_summaries,
                )
            )

            if advisor_result is None:
                action = self._fallback_wait(state, "llm_api_failed")
                self._log_fallback(log_entry, "llm_api_failed", action)
                return action

            selected = self._find_candidate(executable, advisor_result.selected_candidate_id)
            if selected is None:
                action = self._fallback_wait(state, "advisor_invalid_candidate")
                self._log_fallback(log_entry, "advisor_invalid_candidate", action)
                return action

            proposed_action = {"action": selected.action, "params": dict(selected.params)}

            accepted, rejection_reason = self._safety_gate.validate(proposed_action, state, items)
            log_entry["safety_accepted"] = accepted
            if not accepted:
                log_entry["safety_rejection"] = rejection_reason
                action = self._fallback_wait(state, "safety_rejection_retry_failed")
                self._log_fallback(log_entry, "safety_rejection_retry_failed", action)
                return action

            log_entry.update({
                "advisor_called": True,
                "selected_candidate_id": selected.candidate_id,
                "selected_action": selected.action,
                "fallback_used": False,
                "reason": advisor_result.reason,
            })
            self._write_log_safe(log_entry)
            return self._normalize_action(proposed_action)

        except Exception as exc:
            self._logger.exception("decision failed for driver_id=%s: %s", driver_id, exc)
            action = self._fallback_wait(state, "unexpected_exception")
            try:
                self._log_fallback(log_entry, "unexpected_exception", action)
            except Exception:
                pass
            return action

    def _find_candidate(self, candidates: list[Candidate], candidate_id: str) -> Candidate | None:
        for c in candidates:
            if c.candidate_id == candidate_id:
                return c
        return None

    def _evaluate_constraints(
        self,
        candidates: list[Candidate],
        constraints: tuple[ConstraintSpec, ...],
        state: DecisionState,
        runtime: Any | None = None,
    ) -> list[Candidate]:
        if not constraints:
            return candidates
        evaluated: list[Candidate] = []
        for c in candidates:
            result = self._constraint_evaluator.evaluate(c, constraints, state, runtime)
            merged_hard = c.hard_invalid_reasons + result.hard_invalid_reasons
            merged_soft = c.soft_risk_reasons + result.soft_risk_reasons
            penalty = result.estimated_penalty_exposure
            enriched_facts = dict(c.facts)
            enriched_facts["constraint_impacts"] = tuple(
                {"constraint_id": imp.constraint_id, "constraint_type": imp.constraint_type,
                 "status": imp.status, "penalty": imp.penalty, "detail": imp.detail}
                for imp in result.constraint_impacts
            )
            enriched_facts["estimated_penalty_exposure"] = penalty
            net = float(enriched_facts.get("estimated_net", 0) or 0)
            enriched_facts["estimated_net_after_penalty"] = round(net - penalty, 2)
            enriched_facts["satisfies_constraints"] = result.satisfies_all_constraints
            evaluated.append(Candidate(
                candidate_id=c.candidate_id,
                action=c.action,
                params=c.params,
                source=c.source,
                facts=enriched_facts,
                hard_invalid_reasons=merged_hard,
                soft_risk_reasons=merged_soft,
            ))
        return evaluated

    def _build_candidate_summaries(
        self,
        candidates: list[Candidate],
    ) -> dict[str, CandidateSummary]:
        summaries: dict[str, CandidateSummary] = {}
        for c in candidates:
            impacts_raw = c.facts.get("constraint_impacts", ())
            impacts_list: list[dict[str, Any]] = []
            if isinstance(impacts_raw, tuple):
                for imp in impacts_raw:
                    if isinstance(imp, dict):
                        impacts_list.append(imp)
            summaries[c.candidate_id] = CandidateSummary(
                candidate_id=c.candidate_id,
                action=c.action,
                estimated_net=float(c.facts.get("estimated_net", 0) or 0),
                estimated_penalty_exposure=float(c.facts.get("estimated_penalty_exposure", 0) or 0),
                estimated_net_after_penalty=float(c.facts.get("estimated_net_after_penalty", 0) or 0),
                satisfies_constraints=bool(c.facts.get("satisfies_constraints", True)),
                soft_risk_reasons=c.soft_risk_reasons,
                constraint_impacts=tuple(impacts_list),
            )
        return summaries

    def _fallback_wait(self, state: DecisionState, reason: str) -> dict[str, Any]:
        duration = max(1, min(60, state.remaining_minutes or 60))
        return {"action": "wait", "params": {"duration_minutes": duration}}

    def _normalize_action(self, action: dict[str, Any]) -> dict[str, Any]:
        action_name = str(action.get("action", "")).strip().lower()
        params = action.get("params") if isinstance(action.get("params"), dict) else {}
        if action_name == "take_order":
            cargo_id = str(params.get("cargo_id", "")).strip()
            if cargo_id:
                return {"action": "take_order", "params": {"cargo_id": cargo_id}}
        if action_name == "wait":
            try:
                duration = max(1, int(params.get("duration_minutes", 60)))
            except (TypeError, ValueError):
                duration = 60
            return {"action": "wait", "params": {"duration_minutes": duration}}
        if action_name == "reposition":
            try:
                return {
                    "action": "reposition",
                    "params": {
                        "latitude": float(params.get("latitude", 0)),
                        "longitude": float(params.get("longitude", 0)),
                    },
                }
            except (TypeError, ValueError):
                pass
        return action

    def _recent_actions(self, state: DecisionState) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for record in state.history_records[-5:]:
            action = record.get("action") or record.get("action_name") or ""
            results.append({
                "action": str(action),
                "minute": record.get("minute") or record.get("simulation_minute"),
                "params": record.get("params") or {},
            })
        return results

    def _preference_text(self, pref: Any) -> str:
        if isinstance(pref, str):
            return pref
        if isinstance(pref, dict):
            return pref.get("text") or pref.get("raw_text") or json.dumps(pref, ensure_ascii=False)
        return str(pref)

    def _log_fallback(self, log_entry: dict[str, Any], reason: str, action: dict[str, Any]) -> None:
        log_entry.update({
            "advisor_called": False,
            "fallback_used": True,
            "fallback_reason": reason,
            "final_action": self._final_action_summary(action),
        })
        self._write_log_safe(log_entry)

    def _final_action_summary(self, action: dict[str, Any]) -> dict[str, Any]:
        action_name = str(action.get("action", "")).strip().lower()
        params = action.get("params") if isinstance(action.get("params"), dict) else {}
        if action_name == "take_order":
            return {"type": "take_order", "cargo_id": str(params.get("cargo_id", ""))}
        if action_name == "wait":
            return {"type": "wait", "duration_minutes": params.get("duration_minutes", 0)}
        if action_name == "reposition":
            return {"type": "reposition", "latitude": params.get("latitude"), "longitude": params.get("longitude")}
        return {"type": action_name}

    def _write_log_safe(self, entry: dict[str, Any]) -> None:
        try:
            log_dir = Path(__file__).resolve().parent.parent / "results" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "agent_decisions.jsonl"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except Exception as log_exc:
            self._logger.warning("failed to write decision log: %s", log_exc)
