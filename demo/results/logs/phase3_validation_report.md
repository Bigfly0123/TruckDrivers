# Phase 3.0.5 Validation Report

## Run Summary
- drivers: 5
- total decisions: 556
- total graph events: 14472
- node_start: 4454
- node_end: 4453
- node_error: 0
- fallback count: 2
- safety reject count: 2
- final_action missing: 0
- selected_vs_best_valid_net_gap avg: -2.65
- selected_vs_best_valid_net_gap max: 291.6

## Node Errors
- none

## Driver Action Distribution
| driver | take_order | wait | reposition | fallback |
|---|---:|---:|---:|---:|
| D001 | 43 | 162 | 18 | 0 |
| D002 | 32 | 8 | 0 | 0 |
| D003 | 61 | 40 | 0 | 1 |
| D004 | 38 | 38 | 0 | 1 |
| D005 | 36 | 80 | 0 | 0 |

## Diagnostic Warnings
| driver | warning | count |
|---|---|---:|
| D001 | profitable_valid_order_but_selected_wait | 5 |
| D002 | only_wait_candidates_available | 1 |
| D003 | only_wait_candidates_available | 40 |
| D003 | safety_rejected_advisor_choice | 1 |
| D004 | only_wait_candidates_available | 38 |
| D004 | safety_rejected_advisor_choice | 1 |
| D005 | only_wait_candidates_available | 80 |

## Blocking Constraint Summary
| driver | reason | count |
|---|---|---:|
| D001 | constraint_operate_within_area | 16495 |
| D005 | constraint_max_distance | 12387 |
| D001 | load_time_window_expired | 11838 |
| D005 | constraint_forbid_action_in_time_window | 8941 |
| D005 | load_time_window_expired | 5731 |
| D003 | load_time_window_expired | 5051 |
| D003 | constraint_max_distance | 4828 |
| D004 | constraint_forbid_action_in_time_window | 4221 |
| D004 | load_time_window_expired | 3316 |
| D003 | constraint_forbid_action_in_time_window | 3260 |
| D001 | constraint_forbid_cargo_category | 1802 |
| D002 | load_time_window_expired | 1759 |
| D003 | constraint_avoid_zone | 793 |
| D001 | load_time_window_unreachable | 543 |
| D004 | load_time_window_unreachable | 354 |
| D003 | end_month_unreachable | 291 |
| D005 | load_time_window_unreachable | 146 |
| D003 | load_time_window_unreachable | 130 |
| D002 | constraint_forbid_cargo_category | 122 |
| D002 | load_time_window_unreachable | 112 |
| D004 | end_month_unreachable | 50 |
| D002 | end_month_unreachable | 11 |

## Phase 3.0.5 Acceptance
- graph events present: pass
- decision summaries present: pass
- tool summaries present: pass
- diagnosis present: pass
- no blocking node errors: pass
- final action present: pass
- ready for Phase 3.1: yes
