# Phase 3.4.5 Validation Report

## Run Summary
- drivers: 10
- total decisions: 1243
- total graph events: 53449
- node_start: 14916
- node_end: 14916
- node_error: 0
- fallback count: 5
- safety reject count: 10
- final_action missing: 0
- selected_vs_best_valid_net_gap avg: -11.97
- selected_vs_best_valid_net_gap max: 302.0
- day_plan_created_count: 291
- day_plan_reused_count: 952
- decisions_with_day_plan: 1243
- decisions_missing_day_plan: 0
- planner_fallback_plan_count: 11
- day_plan_guidance_present_rate: 100.00%
- day_plan_risk_focus_present_rate: 100.00%
- decisions_with_goal_candidates: 516
- selected_goal_candidate_count: 409
- decisions_with_reflection_hints: 339
- decisions_with_opportunity_facts: 1243
- high_cost_wait_selected_count: 59
- advisor_ignored_best_long_term_count: 129
- advisor_unknown_candidate_count: 0
- unknown_candidate_recovery_count: 0
- unknown_candidate_direct_wait_count: 0
- fallback_with_profitable_order_count: 0

## Node Errors
- none

## Driver Action Distribution
| driver | take_order | wait | reposition | fallback |
|---|---:|---:|---:|---:|
| D001 | 56 | 181 | 0 | 0 |
| D002 | 40 | 15 | 0 | 1 |
| D003 | 58 | 28 | 0 | 0 |
| D004 | 36 | 33 | 0 | 1 |
| D005 | 65 | 69 | 0 | 1 |
| D006 | 52 | 26 | 0 | 0 |
| D007 | 55 | 82 | 0 | 1 |
| D008 | 64 | 128 | 0 | 1 |
| D009 | 41 | 137 | 11 | 0 |
| D010 | 40 | 17 | 9 | 0 |

## Diagnostic Warnings
| driver | warning | count |
|---|---|---:|
| D001 | only_wait_candidates_available | 1 |
| D002 | only_wait_candidates_available | 4 |
| D002 | safety_rejected_advisor_choice | 1 |
| D003 | only_wait_candidates_available | 4 |
| D003 | profitable_valid_order_but_selected_wait | 1 |
| D004 | only_wait_candidates_available | 2 |
| D004 | profitable_valid_order_but_selected_wait | 17 |
| D004 | safety_rejected_advisor_choice | 1 |
| D005 | only_wait_candidates_available | 8 |
| D005 | profitable_valid_order_but_selected_wait | 6 |
| D005 | safety_rejected_advisor_choice | 1 |
| D006 | only_wait_candidates_available | 1 |
| D007 | only_wait_candidates_available | 5 |
| D007 | profitable_valid_order_but_selected_wait | 2 |
| D007 | safety_rejected_advisor_choice | 1 |
| D008 | only_wait_candidates_available | 8 |
| D008 | profitable_valid_order_but_selected_wait | 3 |
| D008 | safety_rejected_advisor_choice | 1 |
| D009 | only_wait_candidates_available | 1 |
| D009 | profitable_valid_order_but_selected_wait | 3 |

## Opportunity / Future Value
| metric | value |
|---|---:|
| decisions_with_opportunity_facts | 1243 |
| candidate_count_with_future_value_total | 59693 |
| wait_opportunity_cost_sum | 523779.77 |
| high_cost_wait_count_total | 676 |
| high_cost_wait_selected_count | 59 |
| used_opportunity_signal_count | 787 |
| future_value_used_in_reason_count | 415 |
| advisor_ignored_best_long_term_count | 129 |
| target_cargo_unavailable_but_high_wait_cost_count | 0 |
| advisor_unknown_candidate_count | 0 |
| unknown_candidate_recovery_count | 0 |
| unknown_candidate_direct_wait_count | 0 |
| fallback_with_profitable_order_count | 0 |
| recovery_used_count | 0 |
| non_selectable_candidate_id_exposed_count | 0 |
| profitable_hard_invalid_order_count_total | 57503 |
| profitable_hard_invalid_order_net_sum | 12269753.3 |
| hard_soft_boundary_reclassification_count | 104110 |

### Wait Reason Categories
| category | count |
|---|---:|
| no_valid_order | 295 |
| forbid_window_wait | 232 |
| rest_required_wait | 152 |
| profitable_order_but_wait | 32 |
| fallback_wait | 5 |
| critical_goal_wait | 2 |

### Wait Purposes
| purpose | count |
|---|---:|
| market_wait | 325 |
| forbid_window_wait | 232 |
| rest_progress_wait | 152 |
| fallback_wait | 5 |
| goal_wait | 1 |
| goal_hold_wait | 1 |

### Hard Invalid Audit Classes
| class | count |
|---|---:|
| true_hard | 1834 |

## Reflection Memory
| metric | value |
|---|---:|
| decisions_with_reflection_hints | 339 |
| active_reflection_hint_count_total | 425 |
| reflection_new_failure_count | 71 |
| reflection_new_hint_count | 58 |
| reflection_filtered_illegal_fields | 0 |

### Reflection Failure Types
| failure_type | count |
|---|---:|
| goal_overuse | 323 |
| profitable_order_but_wait | 103 |
| specific_cargo_unavailable | 47 |
| ordered_step_regression | 10 |

## Goal Candidate Layer
| metric | value |
|---|---:|
| decisions_with_active_goals | 1243 |
| decisions_with_goal_candidates | 516 |
| selected_goal_candidate_count | 409 |
| avg_active_goal_count | 1.24 |
| avg_goal_candidate_count | 0.48 |
| goal_materialization_failure_decisions | 11 |
| stuck_goal_decisions | 627 |
| selected_goal_must_do_now_count | 371 |
| selected_low_medium_goal_count | 38 |
| profitable_valid_order_but_selected_rest_count | 0 |
| rest_opportunity_cost_sum | 0.0 |
| hold_candidate_generated_count | 2 |
| ordered_steps_regression_count | 1 |
| rest_not_urgent_count | 405 |

### Selected Goal By Urgency
| urgency | count |
|---|---:|
| critical | 357 |
| medium | 28 |
| high | 14 |
| low | 10 |

### Goal Materialization Failures
| reason | count |
|---|---:|
| target_cargo_not_visible | 11 |

## DayPlan Quality
| metric | value |
|---|---:|
| decisions_with_day_plan | 1243 |
| day_plan_empty_guidance_count | 0 |
| day_plan_guidance_present_rate | 100.00% |
| day_plan_empty_risk_focus_count | 0 |
| day_plan_risk_focus_present_rate | 100.00% |
| day_plan_fallback_count | 11 |
| day_plan_language_mismatch_count | 0 |
| decisions_with_day_plan_guidance | 1243 |
| decisions_missing_day_plan_guidance | 0 |

## Advisor Wait Despite Profit
| driver | count |
|---|---:|
| D003 | 1 |
| D004 | 17 |
| D005 | 6 |
| D007 | 2 |
| D008 | 3 |
| D009 | 3 |

## DayPlan Summary
| driver | created | reused | missing | fallback_plan |
|---|---:|---:|---:|---:|
| D001 | 31 | 206 | 0 | 11 |
| D002 | 28 | 27 | 0 | 0 |
| D003 | 31 | 55 | 0 | 0 |
| D004 | 23 | 46 | 0 | 0 |
| D005 | 29 | 105 | 0 | 0 |
| D006 | 29 | 49 | 0 | 0 |
| D007 | 30 | 107 | 0 | 0 |
| D008 | 31 | 161 | 0 | 0 |
| D009 | 29 | 160 | 0 | 0 |
| D010 | 30 | 36 | 0 | 0 |

## Blocking Constraint Summary
| driver | reason | count |
|---|---|---:|
| D001 | load_time_window_expired | 12701 |
| D009 | load_time_window_expired | 9366 |
| D008 | load_time_window_expired | 9272 |
| D007 | load_time_window_expired | 6750 |
| D005 | load_time_window_expired | 6698 |
| D003 | load_time_window_expired | 3916 |
| D006 | load_time_window_expired | 3602 |
| D004 | load_time_window_expired | 3036 |
| D010 | load_time_window_expired | 3033 |
| D002 | load_time_window_expired | 2576 |
| D008 | end_month_unreachable | 873 |
| D005 | end_month_unreachable | 628 |
| D001 | load_time_window_unreachable | 511 |
| D008 | load_time_window_unreachable | 477 |
| D003 | end_month_unreachable | 400 |
| D007 | end_month_unreachable | 355 |
| D007 | load_time_window_unreachable | 348 |
| D009 | load_time_window_unreachable | 307 |
| D004 | load_time_window_unreachable | 260 |
| D004 | end_month_unreachable | 254 |
| D002 | end_month_unreachable | 244 |
| D009 | end_month_unreachable | 239 |
| D002 | load_time_window_unreachable | 202 |
| D003 | load_time_window_unreachable | 196 |
| D010 | load_time_window_unreachable | 180 |
| D005 | load_time_window_unreachable | 172 |
| D006 | load_time_window_unreachable | 141 |
| D006 | end_month_unreachable | 78 |
| D010 | end_month_unreachable | 25 |

## Phase 3.4.5 Acceptance
- graph events present: pass
- decision summaries present: pass
- tool summaries present: pass
- diagnosis present: pass
- no blocking node errors: pass
- final action present: pass
- planning node executed: pass
- day plan present in decisions: pass
- day plan events present: pass
- day plan guidance present rate >= 0.95: pass
- day plan risk focus present rate >= 0.90: pass
- day plan language is zh: pass
- goal layer fields present: pass
- reflection fields present: pass
- opportunity fields present: pass
- future value fields present: pass
- advisor summary does not expose non-selectable candidates: pass
- unknown candidate recovery fields present: pass
- unknown candidate direct wait count is zero: pass
- wait purpose fields present for waits: fail
- hard invalid audit fields present: pass
- hard/soft boundary reclassification field present: pass
- ready for next phase: no
