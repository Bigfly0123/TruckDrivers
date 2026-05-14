from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a Phase 3 validation report.")
    parser.add_argument("--logs-dir", default=None, help="Directory containing agent graph logs.")
    parser.add_argument("--output", default=None, help="Markdown report output path.")
    args = parser.parse_args()

    repo_demo = Path(__file__).resolve().parents[3]
    logs_dir = Path(args.logs_dir) if args.logs_dir else repo_demo / "results" / "logs"
    graph_path = logs_dir / "agent_graph_trace.jsonl"
    decisions_path = logs_dir / "agent_decisions.jsonl"
    output_path = Path(args.output) if args.output else logs_dir / "phase3_validation_report.md"

    graph_events = _read_jsonl(graph_path)
    decisions = _read_jsonl(decisions_path)
    report = build_report(graph_events, decisions)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"wrote {output_path}")


def build_report(graph_events: list[dict[str, Any]], decisions: list[dict[str, Any]]) -> str:
    event_counts = Counter(str(e.get("event") or "") for e in graph_events)
    node_errors = Counter(str(e.get("node") or "") for e in graph_events if e.get("event") == "node_error")
    drivers = sorted({str(d.get("driver_id") or "") for d in decisions if d.get("driver_id")})
    fallback_count = sum(1 for d in decisions if d.get("fallback_used"))
    safety_reject_count = sum(1 for d in decisions if d.get("safety_rejected"))
    final_missing_count = sum(1 for d in decisions if not d.get("final_action"))
    action_distribution = _action_distribution(decisions)
    warning_counts = _warning_counts(decisions)
    hard_reason_counts = _hard_reason_counts(decisions)
    gaps = [
        float(d["diagnosis"]["selected_vs_best_valid_net_gap"])
        for d in decisions
        if isinstance(d.get("diagnosis"), dict)
        and d["diagnosis"].get("selected_vs_best_valid_net_gap") is not None
    ]

    day_plan_stats = _day_plan_stats(graph_events, decisions)
    goal_stats = _goal_layer_stats(decisions)
    reflection_stats = _reflection_stats(decisions)

    lines = [
        "# Phase 3.3 Validation Report",
        "",
        "## Run Summary",
        f"- drivers: {len(drivers)}",
        f"- total decisions: {len(decisions)}",
        f"- total graph events: {len(graph_events)}",
        f"- node_start: {event_counts.get('node_start', 0)}",
        f"- node_end: {event_counts.get('node_end', 0)}",
        f"- node_error: {event_counts.get('node_error', 0)}",
        f"- fallback count: {fallback_count}",
        f"- safety reject count: {safety_reject_count}",
        f"- final_action missing: {final_missing_count}",
        f"- selected_vs_best_valid_net_gap avg: {round(mean(gaps), 2) if gaps else 'n/a'}",
        f"- selected_vs_best_valid_net_gap max: {round(max(gaps), 2) if gaps else 'n/a'}",
        f"- day_plan_created_count: {day_plan_stats['created_count']}",
        f"- day_plan_reused_count: {day_plan_stats['reused_count']}",
        f"- decisions_with_day_plan: {day_plan_stats['decisions_with_day_plan']}",
        f"- decisions_missing_day_plan: {day_plan_stats['decisions_missing_day_plan']}",
        f"- planner_fallback_plan_count: {day_plan_stats['fallback_plan_count']}",
        f"- day_plan_guidance_present_rate: {day_plan_stats['guidance_present_rate']}",
        f"- day_plan_risk_focus_present_rate: {day_plan_stats['risk_focus_present_rate']}",
        f"- decisions_with_goal_candidates: {goal_stats['decisions_with_goal_candidates']}",
        f"- selected_goal_candidate_count: {goal_stats['selected_goal_candidate_count']}",
        f"- decisions_with_reflection_hints: {reflection_stats['decisions_with_reflection_hints']}",
        "",
        "## Node Errors",
    ]
    if node_errors:
        lines.extend(f"- {node}: {count}" for node, count in node_errors.most_common())
    else:
        lines.append("- none")

    lines.extend(["", "## Driver Action Distribution", "| driver | take_order | wait | reposition | fallback |", "|---|---:|---:|---:|---:|"])
    for driver in drivers:
        counts = action_distribution[driver]
        lines.append(
            f"| {driver} | {counts.get('take_order', 0)} | {counts.get('wait', 0)} | "
            f"{counts.get('reposition', 0)} | {counts.get('fallback', 0)} |"
        )

    lines.extend(["", "## Diagnostic Warnings", "| driver | warning | count |", "|---|---|---:|"])
    if warning_counts:
        for (driver, warning), count in sorted(warning_counts.items()):
            lines.append(f"| {driver} | {warning} | {count} |")
    else:
        lines.append("| all | none | 0 |")

    lines.extend([
        "",
        "## Reflection Memory",
        "| metric | value |",
        "|---|---:|",
        f"| decisions_with_reflection_hints | {reflection_stats['decisions_with_reflection_hints']} |",
        f"| active_reflection_hint_count_total | {reflection_stats['active_hint_count_total']} |",
        f"| reflection_new_failure_count | {reflection_stats['new_failure_count']} |",
        f"| reflection_new_hint_count | {reflection_stats['new_hint_count']} |",
        f"| reflection_filtered_illegal_fields | {reflection_stats['filtered_illegal_fields']} |",
        "",
        "### Reflection Failure Types",
        "| failure_type | count |",
        "|---|---:|",
    ])
    if reflection_stats["failure_types"]:
        for failure_type, count in reflection_stats["failure_types"].most_common():
            lines.append(f"| {failure_type} | {count} |")
    else:
        lines.append("| none | 0 |")

    lines.extend([
        "",
        "## Goal Candidate Layer",
        "| metric | value |",
        "|---|---:|",
        f"| decisions_with_active_goals | {goal_stats['decisions_with_active_goals']} |",
        f"| decisions_with_goal_candidates | {goal_stats['decisions_with_goal_candidates']} |",
        f"| selected_goal_candidate_count | {goal_stats['selected_goal_candidate_count']} |",
        f"| avg_active_goal_count | {goal_stats['avg_active_goal_count']} |",
        f"| avg_goal_candidate_count | {goal_stats['avg_goal_candidate_count']} |",
        f"| goal_materialization_failure_decisions | {goal_stats['failure_decisions']} |",
        f"| stuck_goal_decisions | {goal_stats['stuck_goal_decisions']} |",
        f"| selected_goal_must_do_now_count | {goal_stats['selected_must_do_now_count']} |",
        f"| selected_low_medium_goal_count | {goal_stats['selected_low_medium_goal_count']} |",
        f"| profitable_valid_order_but_selected_rest_count | {goal_stats['profitable_valid_order_but_selected_rest_count']} |",
        f"| rest_opportunity_cost_sum | {goal_stats['rest_opportunity_cost_sum']} |",
        f"| hold_candidate_generated_count | {goal_stats['hold_candidate_generated_count']} |",
        f"| ordered_steps_regression_count | {goal_stats['ordered_steps_regression_count']} |",
        f"| rest_not_urgent_count | {goal_stats['rest_not_urgent_count']} |",
        "",
        "### Selected Goal By Urgency",
        "| urgency | count |",
        "|---|---:|",
    ])
    if goal_stats["selected_goal_by_urgency"]:
        for urgency, count in goal_stats["selected_goal_by_urgency"].most_common():
            lines.append(f"| {urgency} | {count} |")
    else:
        lines.append("| none | 0 |")

    lines.extend([
        "",
        "### Goal Materialization Failures",
        "| reason | count |",
        "|---|---:|",
    ])
    if goal_stats["failure_counts"]:
        for reason, count in goal_stats["failure_counts"].most_common():
            lines.append(f"| {reason} | {count} |")
    else:
        lines.append("| none | 0 |")

    lines.extend([
        "",
        "## DayPlan Quality",
        "| metric | value |",
        "|---|---:|",
        f"| decisions_with_day_plan | {day_plan_stats['decisions_with_day_plan']} |",
        f"| day_plan_empty_guidance_count | {day_plan_stats['empty_guidance_count']} |",
        f"| day_plan_guidance_present_rate | {day_plan_stats['guidance_present_rate']} |",
        f"| day_plan_empty_risk_focus_count | {day_plan_stats['empty_risk_focus_count']} |",
        f"| day_plan_risk_focus_present_rate | {day_plan_stats['risk_focus_present_rate']} |",
        f"| day_plan_fallback_count | {day_plan_stats['fallback_plan_count']} |",
        f"| day_plan_language_mismatch_count | {day_plan_stats['language_mismatch_count']} |",
        f"| decisions_with_day_plan_guidance | {day_plan_stats['decisions_with_guidance']} |",
        f"| decisions_missing_day_plan_guidance | {day_plan_stats['empty_guidance_count']} |",
    ])

    lines.extend(["", "## Advisor Wait Despite Profit", "| driver | count |", "|---|---:|"])
    wait_profit_counts = {
        driver: count
        for (driver, warning), count in warning_counts.items()
        if warning == "profitable_valid_order_but_selected_wait"
    }
    if wait_profit_counts:
        for driver, count in sorted(wait_profit_counts.items()):
            lines.append(f"| {driver} | {count} |")
    else:
        lines.append("| all | 0 |")

    lines.extend(["", "## DayPlan Summary", "| driver | created | reused | missing | fallback_plan |", "|---|---:|---:|---:|---:|"])
    for driver in drivers:
        created = day_plan_stats["created_by_driver"].get(driver, 0)
        reused = day_plan_stats["reused_by_driver"].get(driver, 0)
        missing = day_plan_stats["missing_by_driver"].get(driver, 0)
        fallback = day_plan_stats["fallback_by_driver"].get(driver, 0)
        lines.append(f"| {driver} | {created} | {reused} | {missing} | {fallback} |")

    lines.extend(["", "## Blocking Constraint Summary", "| driver | reason | count |", "|---|---|---:|"])
    if hard_reason_counts:
        for (driver, reason), count in sorted(hard_reason_counts.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"| {driver} | {reason} | {count} |")
    else:
        lines.append("| all | none | 0 |")

    lines.extend(["", "## Phase 3.3 Acceptance"])
    checks = {
        "graph events present": bool(graph_events),
        "decision summaries present": bool(decisions),
        "tool summaries present": event_counts.get("tool_summary", 0) > 0,
        "diagnosis present": any(isinstance(d.get("diagnosis"), dict) and d.get("diagnosis") for d in decisions),
        "no blocking node errors": event_counts.get("node_error", 0) == 0,
        "final action present": final_missing_count == 0,
        "planning node executed": event_counts.get("planning_summary", 0) > 0,
        "day plan present in decisions": bool(decisions) and day_plan_stats["decisions_missing_day_plan"] == 0,
        "day plan events present": day_plan_stats["created_count"] > 0 or day_plan_stats["reused_count"] > 0,
        "day plan guidance present rate >= 0.95": day_plan_stats["guidance_present_rate_value"] >= 0.95,
        "day plan risk focus present rate >= 0.90": day_plan_stats["risk_focus_present_rate_value"] >= 0.90,
        "day plan language is zh": day_plan_stats["language_mismatch_count"] == 0,
        "goal layer fields present": bool(decisions) and all("goal_candidate_count" in d for d in decisions),
        "reflection fields present": bool(decisions) and all("active_reflection_hint_count" in d for d in decisions),
    }
    for name, passed in checks.items():
        lines.append(f"- {name}: {'pass' if passed else 'fail'}")
    ready = all(checks.values())
    lines.append(f"- ready for next phase: {'yes' if ready else 'no'}")
    lines.append("")
    return "\n".join(lines)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            records.append({"_invalid_json": True, "line": line_no, "error": str(exc)})
            continue
        if isinstance(data, dict):
            records.append(data)
    return records


def _action_distribution(decisions: list[dict[str, Any]]) -> dict[str, Counter[str]]:
    result: dict[str, Counter[str]] = defaultdict(Counter)
    for decision in decisions:
        driver = str(decision.get("driver_id") or "unknown")
        final_action = decision.get("final_action") if isinstance(decision.get("final_action"), dict) else {}
        action = str(final_action.get("action") or decision.get("selected_candidate_action") or "unknown")
        result[driver][action] += 1
        if decision.get("fallback_used"):
            result[driver]["fallback"] += 1
    return result


def _warning_counts(decisions: list[dict[str, Any]]) -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    for decision in decisions:
        driver = str(decision.get("driver_id") or "unknown")
        diagnosis = decision.get("diagnosis") if isinstance(decision.get("diagnosis"), dict) else {}
        if diagnosis.get("advisor_chose_wait_despite_profitable_order"):
            counts[(driver, "profitable_valid_order_but_selected_wait")] += 1
        if diagnosis.get("candidate_pool_empty"):
            counts[(driver, "candidate_pool_empty")] += 1
        if diagnosis.get("only_wait_candidates_available"):
            counts[(driver, "only_wait_candidates_available")] += 1
        if diagnosis.get("safety_rejected_advisor_choice"):
            counts[(driver, "safety_rejected_advisor_choice")] += 1
    return counts


def _hard_reason_counts(decisions: list[dict[str, Any]]) -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    for decision in decisions:
        driver = str(decision.get("driver_id") or "unknown")
        reasons = decision.get("hard_invalid_reason_counts")
        if not isinstance(reasons, dict):
            continue
        for reason, count in reasons.items():
            try:
                counts[(driver, str(reason))] += int(count)
            except (TypeError, ValueError):
                continue
    return counts


def _day_plan_stats(graph_events: list[dict[str, Any]], decisions: list[dict[str, Any]]) -> dict[str, Any]:
    created_by_driver: Counter[str] = Counter()
    reused_by_driver: Counter[str] = Counter()
    fallback_by_driver: Counter[str] = Counter()
    missing_by_driver: Counter[str] = Counter()
    empty_guidance_count = 0
    empty_risk_focus_count = 0
    fallback_decision_count = 0
    language_mismatch_count = 0
    decisions_with_guidance = 0
    for event in graph_events:
        event_name = event.get("event")
        driver = str(event.get("driver_id") or "unknown")
        summary = event.get("summary") if isinstance(event.get("summary"), dict) else {}
        if event_name == "day_plan_created":
            created_by_driver[driver] += 1
        if event_name == "day_plan_reused":
            reused_by_driver[driver] += 1
        if event_name in {"day_plan_created", "day_plan_reused"} and summary.get("fallback_used"):
            fallback_by_driver[driver] += 1
    decisions_with_day_plan = 0
    for decision in decisions:
        driver = str(decision.get("driver_id") or "unknown")
        if decision.get("day_plan_summary"):
            decisions_with_day_plan += 1
        else:
            missing_by_driver[driver] += 1
        guidance_count = _count_field(decision, "day_plan_guidance_count", "day_plan_advisor_guidance")
        risk_focus_count = _count_field(decision, "day_plan_risk_focus_count", "day_plan_risk_focus")
        if guidance_count > 0:
            decisions_with_guidance += 1
        else:
            empty_guidance_count += 1
        if risk_focus_count <= 0:
            empty_risk_focus_count += 1
        if decision.get("day_plan_fallback_used"):
            fallback_decision_count += 1
        language = decision.get("day_plan_language")
        if language is not None and language != "zh":
            language_mismatch_count += 1
        if language is None and decision.get("day_plan_summary"):
            language_mismatch_count += 1
    total_decisions = len(decisions)
    guidance_rate = (decisions_with_guidance / total_decisions) if total_decisions else 0.0
    risk_rate = ((total_decisions - empty_risk_focus_count) / total_decisions) if total_decisions else 0.0
    fallback_event_count = sum(fallback_by_driver.values())
    return {
        "created_count": sum(created_by_driver.values()),
        "reused_count": sum(reused_by_driver.values()),
        "decisions_with_day_plan": decisions_with_day_plan,
        "decisions_missing_day_plan": sum(missing_by_driver.values()),
        "fallback_plan_count": fallback_event_count if fallback_event_count else fallback_decision_count,
        "empty_guidance_count": empty_guidance_count,
        "empty_risk_focus_count": empty_risk_focus_count,
        "guidance_present_rate_value": guidance_rate,
        "risk_focus_present_rate_value": risk_rate,
        "guidance_present_rate": f"{guidance_rate:.2%}",
        "risk_focus_present_rate": f"{risk_rate:.2%}",
        "language_mismatch_count": language_mismatch_count,
        "decisions_with_guidance": decisions_with_guidance,
        "created_by_driver": created_by_driver,
        "reused_by_driver": reused_by_driver,
        "missing_by_driver": missing_by_driver,
        "fallback_by_driver": fallback_by_driver,
    }


def _goal_layer_stats(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    active_counts: list[int] = []
    candidate_counts: list[int] = []
    failure_counts: Counter[str] = Counter()
    selected_goal_candidate_count = 0
    selected_must_do_now_count = 0
    selected_low_medium_goal_count = 0
    profitable_valid_order_but_selected_rest_count = 0
    rest_opportunity_cost_sum = 0.0
    hold_candidate_generated_count = 0
    ordered_steps_regression_count = 0
    rest_not_urgent_count = 0
    selected_goal_by_urgency: Counter[str] = Counter()
    stuck_goal_decisions = 0
    failure_decisions = 0
    decisions_with_active_goals = 0
    decisions_with_goal_candidates = 0

    for decision in decisions:
        active = _safe_int(decision.get("active_goal_count"))
        goal_candidates = _safe_int(decision.get("goal_candidate_count"))
        active_counts.append(active)
        candidate_counts.append(goal_candidates)
        if active > 0:
            decisions_with_active_goals += 1
        if goal_candidates > 0:
            decisions_with_goal_candidates += 1
        if decision.get("selected_candidate_goal_id"):
            selected_goal_candidate_count += 1
            urgency = str(decision.get("selected_candidate_goal_urgency") or "unknown")
            selected_goal_by_urgency[urgency] += 1
            if decision.get("selected_candidate_must_do_now"):
                selected_must_do_now_count += 1
            if urgency in {"low", "medium"}:
                selected_low_medium_goal_count += 1
        stuck = _safe_int(decision.get("goal_stuck_suspected_count"))
        if stuck > 0:
            stuck_goal_decisions += 1
        diagnosis = decision.get("diagnosis") if isinstance(decision.get("diagnosis"), dict) else {}
        if diagnosis.get("profitable_valid_order_but_selected_rest"):
            profitable_valid_order_but_selected_rest_count += 1
            try:
                rest_opportunity_cost_sum += float(diagnosis.get("rest_opportunity_cost") or 0.0)
            except (TypeError, ValueError):
                pass
        hold_candidate_generated_count += _safe_int(decision.get("hold_candidate_generated_count"))
        ordered_steps_regression_count += _safe_int(decision.get("ordered_steps_regression_count"))
        rest_not_urgent_count += _safe_int(decision.get("rest_not_urgent_count"))
        failures = decision.get("goal_materialization_failures")
        if isinstance(failures, dict) and failures:
            failure_decisions += 1
            for reason, count in failures.items():
                failure_counts[str(reason)] += _safe_int(count)

    return {
        "decisions_with_active_goals": decisions_with_active_goals,
        "decisions_with_goal_candidates": decisions_with_goal_candidates,
        "selected_goal_candidate_count": selected_goal_candidate_count,
        "avg_active_goal_count": round(mean(active_counts), 2) if active_counts else "n/a",
        "avg_goal_candidate_count": round(mean(candidate_counts), 2) if candidate_counts else "n/a",
        "failure_counts": failure_counts,
        "failure_decisions": failure_decisions,
        "stuck_goal_decisions": stuck_goal_decisions,
        "selected_goal_by_urgency": selected_goal_by_urgency,
        "selected_must_do_now_count": selected_must_do_now_count,
        "selected_low_medium_goal_count": selected_low_medium_goal_count,
        "profitable_valid_order_but_selected_rest_count": profitable_valid_order_but_selected_rest_count,
        "rest_opportunity_cost_sum": round(rest_opportunity_cost_sum, 2),
        "hold_candidate_generated_count": hold_candidate_generated_count,
        "ordered_steps_regression_count": ordered_steps_regression_count,
        "rest_not_urgent_count": rest_not_urgent_count,
    }


def _reflection_stats(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    failure_types: Counter[str] = Counter()
    decisions_with_reflection_hints = 0
    active_hint_count_total = 0
    new_failure_count = 0
    new_hint_count = 0
    filtered_illegal_fields = 0
    for decision in decisions:
        active_count = _safe_int(decision.get("active_reflection_hint_count"))
        active_hint_count_total += active_count
        if active_count > 0:
            decisions_with_reflection_hints += 1
        new_failure_count += _safe_int(decision.get("reflection_new_failure_count"))
        new_hint_count += _safe_int(decision.get("reflection_new_hint_count"))
        filtered_illegal_fields += _safe_int(decision.get("reflection_filtered_illegal_fields"))
        raw_types = decision.get("reflection_failure_types")
        if isinstance(raw_types, dict):
            for failure_type, count in raw_types.items():
                failure_types[str(failure_type)] += _safe_int(count)
    return {
        "decisions_with_reflection_hints": decisions_with_reflection_hints,
        "active_hint_count_total": active_hint_count_total,
        "new_failure_count": new_failure_count,
        "new_hint_count": new_hint_count,
        "filtered_illegal_fields": filtered_illegal_fields,
        "failure_types": failure_types,
    }


def _count_field(decision: dict[str, Any], count_key: str, list_key: str) -> int:
    value = decision.get(count_key)
    try:
        if value is not None:
            return int(value)
    except (TypeError, ValueError):
        pass
    list_value = decision.get(list_key)
    if isinstance(list_value, list):
        return len(list_value)
    return 0


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    main()
