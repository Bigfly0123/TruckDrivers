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

    lines = [
        "# Phase 3.0.5 Validation Report",
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

    lines.extend(["", "## Blocking Constraint Summary", "| driver | reason | count |", "|---|---|---:|"])
    if hard_reason_counts:
        for (driver, reason), count in sorted(hard_reason_counts.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"| {driver} | {reason} | {count} |")
    else:
        lines.append("| all | none | 0 |")

    lines.extend(["", "## Phase 3.0.5 Acceptance"])
    checks = {
        "graph events present": bool(graph_events),
        "decision summaries present": bool(decisions),
        "tool summaries present": event_counts.get("tool_summary", 0) > 0,
        "diagnosis present": any(isinstance(d.get("diagnosis"), dict) and d.get("diagnosis") for d in decisions),
        "no blocking node errors": event_counts.get("node_error", 0) == 0,
        "final action present": final_missing_count == 0,
    }
    for name, passed in checks.items():
        lines.append(f"- {name}: {'pass' if passed else 'fail'}")
    ready = all(checks.values())
    lines.append(f"- ready for Phase 3.1: {'yes' if ready else 'no'}")
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


if __name__ == "__main__":
    main()
