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
    diagnostics = build_phase3_4_5_diagnostics(graph_events, decisions)
    diagnostics_path = repo_demo / "results" / "phase3_4_5_diagnostics.json"
    diagnostics_path.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
    driver_summary_path = repo_demo / "results" / "phase3_4_5_driver_summary.md"
    driver_summary_path.write_text(build_driver_summary(decisions), encoding="utf-8")
    print(f"wrote {output_path}")
    print(f"wrote {diagnostics_path}")
    print(f"wrote {driver_summary_path}")


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
    opportunity_stats = _opportunity_stats(decisions)

    lines = [
        "# Phase 3.4.5 Validation Report",
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
        f"- decisions_with_opportunity_facts: {opportunity_stats['decisions_with_opportunity_facts']}",
        f"- high_cost_wait_selected_count: {opportunity_stats['high_cost_wait_selected_count']}",
        f"- advisor_ignored_best_long_term_count: {opportunity_stats['advisor_ignored_best_long_term_count']}",
        f"- advisor_unknown_candidate_count: {opportunity_stats['advisor_unknown_candidate_count']}",
        f"- unknown_candidate_recovery_count: {opportunity_stats['unknown_candidate_recovery_count']}",
        f"- unknown_candidate_direct_wait_count: {opportunity_stats['unknown_candidate_direct_wait_count']}",
        f"- fallback_with_profitable_order_count: {opportunity_stats['fallback_with_profitable_order_count']}",
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
        "## Opportunity / Future Value",
        "| metric | value |",
        "|---|---:|",
        f"| decisions_with_opportunity_facts | {opportunity_stats['decisions_with_opportunity_facts']} |",
        f"| candidate_count_with_future_value_total | {opportunity_stats['candidate_count_with_future_value_total']} |",
        f"| wait_opportunity_cost_sum | {opportunity_stats['wait_opportunity_cost_sum']} |",
        f"| high_cost_wait_count_total | {opportunity_stats['high_cost_wait_count_total']} |",
        f"| high_cost_wait_selected_count | {opportunity_stats['high_cost_wait_selected_count']} |",
        f"| used_opportunity_signal_count | {opportunity_stats['used_opportunity_signal_count']} |",
        f"| future_value_used_in_reason_count | {opportunity_stats['future_value_used_in_reason_count']} |",
        f"| advisor_ignored_best_long_term_count | {opportunity_stats['advisor_ignored_best_long_term_count']} |",
        f"| target_cargo_unavailable_but_high_wait_cost_count | {opportunity_stats['target_cargo_unavailable_but_high_wait_cost_count']} |",
        f"| advisor_unknown_candidate_count | {opportunity_stats['advisor_unknown_candidate_count']} |",
        f"| unknown_candidate_recovery_count | {opportunity_stats['unknown_candidate_recovery_count']} |",
        f"| unknown_candidate_direct_wait_count | {opportunity_stats['unknown_candidate_direct_wait_count']} |",
        f"| fallback_with_profitable_order_count | {opportunity_stats['fallback_with_profitable_order_count']} |",
        f"| recovery_used_count | {opportunity_stats['recovery_used_count']} |",
        f"| non_selectable_candidate_id_exposed_count | {opportunity_stats['non_selectable_candidate_id_exposed_count']} |",
        f"| profitable_hard_invalid_order_count_total | {opportunity_stats['profitable_hard_invalid_order_count_total']} |",
        f"| profitable_hard_invalid_order_net_sum | {opportunity_stats['profitable_hard_invalid_order_net_sum']} |",
        f"| hard_soft_boundary_reclassification_count | {opportunity_stats['hard_soft_boundary_reclassification_count']} |",
        "",
        "### Wait Reason Categories",
        "| category | count |",
        "|---|---:|",
    ])
    if opportunity_stats["wait_reason_categories"]:
        for category, count in opportunity_stats["wait_reason_categories"].most_common():
            lines.append(f"| {category} | {count} |")
    else:
        lines.append("| none | 0 |")

    lines.extend([
        "",
        "### Wait Purposes",
        "| purpose | count |",
        "|---|---:|",
    ])
    if opportunity_stats["wait_purposes"]:
        for purpose, count in opportunity_stats["wait_purposes"].most_common():
            lines.append(f"| {purpose} | {count} |")
    else:
        lines.append("| none | 0 |")

    lines.extend([
        "",
        "### Hard Invalid Audit Classes",
        "| class | count |",
        "|---|---:|",
    ])
    if opportunity_stats["hard_invalid_audit_classes"]:
        for audit_class, count in opportunity_stats["hard_invalid_audit_classes"].most_common():
            lines.append(f"| {audit_class} | {count} |")
    else:
        lines.append("| none | 0 |")

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

    lines.extend(["", "## Phase 3.4.5 Acceptance"])
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
        "opportunity fields present": bool(decisions) and all("opportunity_facts_count" in d for d in decisions),
        "future value fields present": bool(decisions) and all("candidate_count_with_future_value" in d for d in decisions),
        "advisor summary does not expose non-selectable candidates": opportunity_stats["non_selectable_candidate_id_exposed_count"] == 0,
        "unknown candidate recovery fields present": bool(decisions) and all("advisor_unknown_candidate" in d for d in decisions),
        "unknown candidate direct wait count is zero": opportunity_stats["unknown_candidate_direct_wait_count"] == 0,
        "wait purpose fields present for waits": opportunity_stats["wait_missing_purpose_count"] == 0,
        "hard invalid audit fields present": bool(decisions) and all("hard_invalid_reason_classification" in d for d in decisions),
        "hard/soft boundary reclassification field present": bool(decisions) and all("hard_soft_boundary_reclassification_count" in d for d in decisions),
    }
    for name, passed in checks.items():
        lines.append(f"- {name}: {'pass' if passed else 'fail'}")
    ready = all(checks.values())
    lines.append(f"- ready for next phase: {'yes' if ready else 'no'}")
    lines.append("")
    return "\n".join(lines)


def build_phase3_4_5_diagnostics(
    graph_events: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    action_distribution = _action_distribution(decisions)
    opportunity_stats = _opportunity_stats(decisions)
    goal_stats = _goal_layer_stats(decisions)
    hard_counts = Counter()
    valid_counts: list[int] = []
    soft_counts: list[int] = []
    hard_invalid_counts: list[int] = []
    for decision in decisions:
        valid_counts.append(_safe_int(decision.get("valid_count")))
        soft_counts.append(_safe_int(decision.get("soft_risk_count")))
        hard_invalid_counts.append(_safe_int(decision.get("hard_invalid_count")))
        reasons = decision.get("hard_invalid_reason_counts")
        if isinstance(reasons, dict):
            for reason, count in reasons.items():
                hard_counts[str(reason)] += _safe_int(count)
    total_actions = Counter()
    for counts in action_distribution.values():
        total_actions.update(counts)
    return {
        "total_decisions": len(decisions),
        "total_graph_events": len(graph_events),
        "take_order_count": total_actions.get("take_order", 0),
        "wait_count": total_actions.get("wait", 0),
        "reposition_count": total_actions.get("reposition", 0),
        "fallback_wait_count": sum(1 for d in decisions if d.get("fallback_used")),
        "unknown_wait_count": opportunity_stats["wait_purposes"].get("unknown_wait", 0),
        "goal_purpose_wait_count": sum(
            opportunity_stats["wait_purposes"].get(key, 0)
            for key in ("goal_wait", "goal_hold_wait", "home_window_wait", "forbid_window_wait", "rest_progress_wait")
        ),
        "advisor_unknown_candidate_count": opportunity_stats["advisor_unknown_candidate_count"],
        "unknown_candidate_recovery_count": opportunity_stats["unknown_candidate_recovery_count"],
        "unknown_candidate_direct_wait_count": opportunity_stats["unknown_candidate_direct_wait_count"],
        "fallback_with_profitable_order_count": opportunity_stats["fallback_with_profitable_order_count"],
        "hard_invalid_profitable_order_count": opportunity_stats["profitable_hard_invalid_order_count_total"],
        "hard_invalid_profitable_order_net_sum": opportunity_stats["profitable_hard_invalid_order_net_sum"],
        "hard_soft_boundary_reclassification_count": sum(_safe_int(d.get("hard_soft_boundary_reclassification_count")) for d in decisions),
        "avg_executable_candidate_count": _avg_ints([v + s for v, s in zip(valid_counts, soft_counts)]),
        "avg_valid_order_count": _avg_field(decisions, "valid_order_count"),
        "avg_soft_risk_order_count": _avg_field(decisions, "soft_risk_order_count"),
        "avg_hard_invalid_count": _avg_ints(hard_invalid_counts),
        "wait_purpose_counts": dict(opportunity_stats["wait_purposes"].most_common()),
        "hard_invalid_reason_counts": dict(hard_counts.most_common(20)),
        "hard_invalid_audit_classes": dict(opportunity_stats["hard_invalid_audit_classes"].most_common()),
        "goal_stats": {
            "profitable_valid_order_but_selected_rest_count": goal_stats["profitable_valid_order_but_selected_rest_count"],
            "rest_opportunity_cost_sum": goal_stats["rest_opportunity_cost_sum"],
        },
    }


def build_driver_summary(decisions: list[dict[str, Any]]) -> str:
    drivers = sorted({str(d.get("driver_id") or "") for d in decisions if d.get("driver_id")})
    action_distribution = _action_distribution(decisions)
    lines = [
        "# Phase 3.4.5 Driver Summary",
        "",
        "| driver | decisions | take_order | wait | reposition | fallback | unknown_candidate | recovery | fallback_with_profit | hard_invalid_top | wait_purpose_top |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for driver in drivers:
        rows = [d for d in decisions if str(d.get("driver_id") or "") == driver]
        counts = action_distribution[driver]
        hard_counts: Counter[str] = Counter()
        wait_purposes: Counter[str] = Counter()
        unknown = 0
        recovery = 0
        fallback_with_profit = 0
        for decision in rows:
            if decision.get("advisor_unknown_candidate"):
                unknown += 1
            if decision.get("recovery_used"):
                recovery += 1
            diagnosis = decision.get("diagnosis") if isinstance(decision.get("diagnosis"), dict) else {}
            if diagnosis.get("fallback_with_profitable_order"):
                fallback_with_profit += 1
            reasons = decision.get("hard_invalid_reason_counts")
            if isinstance(reasons, dict):
                for reason, count in reasons.items():
                    hard_counts[str(reason)] += _safe_int(count)
            purpose = decision.get("selected_candidate_wait_purpose") or diagnosis.get("selected_candidate_wait_purpose")
            if purpose:
                wait_purposes[str(purpose)] += 1
        lines.append(
            f"| {driver} | {len(rows)} | {counts.get('take_order', 0)} | {counts.get('wait', 0)} | "
            f"{counts.get('reposition', 0)} | {counts.get('fallback', 0)} | {unknown} | {recovery} | "
            f"{fallback_with_profit} | {_top_counter_label(hard_counts)} | {_top_counter_label(wait_purposes)} |"
        )
    if not drivers:
        lines.append("| all | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | none | none |")
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
        if diagnosis.get("advisor_unknown_candidate") or decision.get("advisor_unknown_candidate"):
            counts[(driver, "advisor_unknown_candidate")] += 1
        if diagnosis.get("unknown_candidate_direct_wait"):
            counts[(driver, "unknown_candidate_direct_wait")] += 1
        if diagnosis.get("fallback_with_profitable_order"):
            counts[(driver, "fallback_with_profitable_order")] += 1
        if decision.get("recovery_used") or diagnosis.get("recovery_used"):
            counts[(driver, "recovery_used")] += 1
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


def _opportunity_stats(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    wait_reason_categories: Counter[str] = Counter()
    wait_purposes: Counter[str] = Counter()
    hard_invalid_audit_classes: Counter[str] = Counter()
    decisions_with_opportunity_facts = 0
    candidate_count_with_future_value_total = 0
    wait_opportunity_cost_sum = 0.0
    high_cost_wait_count_total = 0
    high_cost_wait_selected_count = 0
    used_opportunity_signal_count = 0
    future_value_used_in_reason_count = 0
    advisor_ignored_best_long_term_count = 0
    target_cargo_unavailable_but_high_wait_cost_count = 0
    advisor_unknown_candidate_count = 0
    unknown_candidate_recovery_count = 0
    unknown_candidate_direct_wait_count = 0
    fallback_with_profitable_order_count = 0
    recovery_used_count = 0
    non_selectable_candidate_id_exposed_count = 0
    profitable_hard_invalid_order_count_total = 0
    profitable_hard_invalid_order_net_sum = 0.0
    wait_missing_purpose_count = 0
    hard_soft_boundary_reclassification_count = 0
    for decision in decisions:
        if _safe_int(decision.get("opportunity_facts_count")) > 0:
            decisions_with_opportunity_facts += 1
        candidate_count_with_future_value_total += _safe_int(decision.get("candidate_count_with_future_value"))
        try:
            wait_opportunity_cost_sum += float(decision.get("wait_opportunity_cost_sum") or 0.0)
        except (TypeError, ValueError):
            pass
        high_cost_wait_count_total += _safe_int(decision.get("high_cost_wait_count"))
        if decision.get("used_opportunity_signal"):
            used_opportunity_signal_count += 1
        reason_text = " ".join(
            str(decision.get(key) or "")
            for key in ("advisor_reason", "opportunity_reason", "why_not_best_long_term_candidate")
        ).lower()
        if "opportunity" in reason_text or "future" in reason_text or "long_term" in reason_text:
            future_value_used_in_reason_count += 1
        diagnosis = decision.get("diagnosis") if isinstance(decision.get("diagnosis"), dict) else {}
        category = diagnosis.get("wait_reason_category")
        if category:
            wait_reason_categories[str(category)] += 1
        final_action = decision.get("final_action") if isinstance(decision.get("final_action"), dict) else {}
        selected_is_wait = final_action.get("action") == "wait" or decision.get("selected_candidate_action") == "wait"
        purpose = decision.get("selected_candidate_wait_purpose") or diagnosis.get("selected_candidate_wait_purpose")
        if selected_is_wait:
            if purpose:
                wait_purposes[str(purpose)] += 1
            else:
                wait_missing_purpose_count += 1
        if diagnosis.get("high_cost_wait_selected"):
            high_cost_wait_selected_count += 1
        if diagnosis.get("advisor_ignored_best_long_term"):
            advisor_ignored_best_long_term_count += 1
        if diagnosis.get("target_cargo_unavailable_but_high_wait_cost"):
            target_cargo_unavailable_but_high_wait_cost_count += 1
        advisor_unknown = bool(decision.get("advisor_unknown_candidate") or diagnosis.get("advisor_unknown_candidate"))
        recovery_used = bool(decision.get("recovery_used") or diagnosis.get("recovery_used"))
        if advisor_unknown:
            advisor_unknown_candidate_count += 1
            if recovery_used:
                unknown_candidate_recovery_count += 1
        if diagnosis.get("unknown_candidate_direct_wait"):
            unknown_candidate_direct_wait_count += 1
        if diagnosis.get("fallback_with_profitable_order"):
            fallback_with_profitable_order_count += 1
        if recovery_used:
            recovery_used_count += 1
        for key in ("opportunity_summary", "advisor_opportunity_summary"):
            summary = decision.get(key) if isinstance(decision.get(key), dict) else {}
            if summary.get("non_selectable_candidate_id_exposed_to_advisor"):
                non_selectable_candidate_id_exposed_count += 1
                break
        profitable_hard_invalid_order_count_total += _safe_int(decision.get("profitable_hard_invalid_order_count"))
        hard_soft_boundary_reclassification_count += _safe_int(decision.get("hard_soft_boundary_reclassification_count"))
        try:
            profitable_hard_invalid_order_net_sum += float(decision.get("profitable_hard_invalid_order_net_sum") or 0.0)
        except (TypeError, ValueError):
            pass
        classification = decision.get("hard_invalid_reason_classification")
        if isinstance(classification, dict):
            for audit_class in classification.values():
                hard_invalid_audit_classes[str(audit_class)] += 1
    return {
        "wait_reason_categories": wait_reason_categories,
        "wait_purposes": wait_purposes,
        "hard_invalid_audit_classes": hard_invalid_audit_classes,
        "decisions_with_opportunity_facts": decisions_with_opportunity_facts,
        "candidate_count_with_future_value_total": candidate_count_with_future_value_total,
        "wait_opportunity_cost_sum": round(wait_opportunity_cost_sum, 2),
        "high_cost_wait_count_total": high_cost_wait_count_total,
        "high_cost_wait_selected_count": high_cost_wait_selected_count,
        "used_opportunity_signal_count": used_opportunity_signal_count,
        "future_value_used_in_reason_count": future_value_used_in_reason_count,
        "advisor_ignored_best_long_term_count": advisor_ignored_best_long_term_count,
        "target_cargo_unavailable_but_high_wait_cost_count": target_cargo_unavailable_but_high_wait_cost_count,
        "advisor_unknown_candidate_count": advisor_unknown_candidate_count,
        "unknown_candidate_recovery_count": unknown_candidate_recovery_count,
        "unknown_candidate_direct_wait_count": unknown_candidate_direct_wait_count,
        "fallback_with_profitable_order_count": fallback_with_profitable_order_count,
        "recovery_used_count": recovery_used_count,
        "non_selectable_candidate_id_exposed_count": non_selectable_candidate_id_exposed_count,
        "profitable_hard_invalid_order_count_total": profitable_hard_invalid_order_count_total,
        "profitable_hard_invalid_order_net_sum": round(profitable_hard_invalid_order_net_sum, 2),
        "wait_missing_purpose_count": wait_missing_purpose_count,
        "hard_soft_boundary_reclassification_count": hard_soft_boundary_reclassification_count,
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


def _avg_ints(values: list[int]) -> float:
    return round(mean(values), 2) if values else 0.0


def _avg_field(decisions: list[dict[str, Any]], key: str) -> float:
    return _avg_ints([_safe_int(d.get(key)) for d in decisions])


def _top_counter_label(counts: Counter[str]) -> str:
    if not counts:
        return "none"
    key, count = counts.most_common(1)[0]
    return f"{key}:{count}"


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    main()
