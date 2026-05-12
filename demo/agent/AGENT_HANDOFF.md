# Driver Cargo Agent Handoff

Last updated: 2026-05-10

## Current Constraints

- Competition submission should only rely on files under `demo/agent/`.
- Do not modify or depend on custom changes in `server`, `simkit`, or public data files for the final submission.
- The agent must not read `server/data/cargo_dataset.jsonl`, `drivers.json`, or any `server/data` file at runtime.
- Runtime decisions should use the provided APIs: `get_driver_status`, `query_cargo`, `query_decision_history`, and `model_chat_completion`.
- Avoid data hardcoding: no `driver_id == ...`, no fixed public cargo IDs, no public-data coordinates or routes in code or prompts.
- Regex is allowed only as generic parsing fallback or engineering aid. It must not become a public-dataset-specific strategy engine.
- Official guidance says hidden driver preferences and rules may change. The implementation should prefer general agent capability over dataset-specific parsing.

## Current Architecture

The current agent is a hybrid LLM-assisted planner:

- `model_decision_service.py`
  - Main entry point: `ModelDecisionService.decide(driver_id)`.
  - Observes driver status, nearby cargo, decision history, preferences, missions, candidates, and then chooses an action.
  - Important bug fixed on 2026-05-10: `trigger = None` must be initialized before mission-complete trigger checks. Without this, all drivers fall into fallback waits.
- `llm_preference_agent.py`
  - LLM-first preference parser.
  - Converts natural-language preferences into structured `PreferenceRule` objects.
- `preference_compiler.py`
  - Caches preference parsing.
  - Provides conservative fallback when LLM parsing fails.
- `llm_mission_planner.py`
  - Creates `MissionPlan` for complex, high-penalty, time-sensitive tasks.
  - Should not create missions for simple ordinary rules such as daily rest, forbidden cargo, or normal quiet hours.
- `mission_executor.py`
  - Executes generic mission steps such as `go_to_point`, `wait_until`, `wait_duration`, `take_specific_cargo`, and `stay_within_radius`.
- `mission_replanner.py`
  - Attempts LLM replanning when a mission is stuck or at risk.
- `planner.py`
  - Programmatic candidate generator and scorer.
  - Still contains most ordinary cargo scoring, filters, and risk calculations.
- `llm_decision_advisor.py`
  - LLM arbitration for selected decision points.
  - Should be used only for meaningful conflicts, finite-penalty tradeoffs, mission conflicts, unknown high-penalty preferences, and deadlocks with actionable candidates.
- `safety_gate.py`
  - Final action validation.
  - Needs to be the single place where hard windows and hard mission constraints are protected from both planner and LLM decisions.

## Latest Observed Result

Latest full local run after fixing the `trigger` initialization issue:

```text
total_net_income_all_drivers = 184083.41
gross_income = 306822.43
total_cost = 101750.25
total_preference_penalty = 20988.8
total_token_usage = 314738
failed_driver_count = 0
```

Historical better local run:

```text
total_net_income_all_drivers = 192484.30
gross_income = 298280.96
total_cost = 94581.66
total_preference_penalty = 11215
total_token_usage = 59461
failed_driver_count = 0
```

Interpretation:

- The current run earns more gross income, but loses the gain through higher cost, higher preference penalties, and much higher token usage.
- The system is no longer globally broken, but it is too aggressive around hard preferences and too chatty with the advisor.
- The next work should not be broad tuning. It should first restore hard preference safety and make advisor calls more meaningful.

## Driver-Level Observations

Current largest regressions versus the historical better run:

- D009:
  - Net income is negative.
  - Nightly home penalty increased to `7200`.
  - Special-cargo handling must not be regressed, but nightly-home safety now needs priority.
- D007:
  - Night quiet-hours penalty increased to `2500`.
  - Generic quiet-hours crossing checks are not strict enough.
- D002:
  - Lower gross income plus additional rest penalty.
  - Needs daily rest planning, but only after hard-window safety is stable.
- D003:
  - Improved from the old deadlock, but still weak.
  - Current behavior: only a few orders, many waits, high token usage.
  - Needs finite-penalty tradeoff recovery, not more repeated advisor calls.
- D010:
  - The fixed 9000 family-task penalty remains avoided.
  - Still has minute-based family-window penalty and daily-rest penalty.
  - Do not break the sequence fix while improving revenue.

## Important Lessons

1. More LLM calls do not automatically make the agent better.
   - Advisor calls must receive actionable safe/risky candidates, risk details, and opportunity costs.
   - Do not call the advisor when candidates are unchanged or only `wait`.

2. LLM should reason inside safety boundaries.
   - It may choose between finite-penalty and profit tradeoffs.
   - It must not override hard windows such as quiet hours, nightly home, hard stay, or urgent mission deadlines.

3. Hard preference safety must be centralized.
   - Planner, mission executor, deadlock recovery, and advisor decisions should all pass through the same safety gate.

4. Public-data improvements are useful only when they generalize.
   - Use current D007/D009/D010 failures as symptoms of generic rule classes.
   - Do not solve them with driver IDs, fixed cargo IDs, fixed coordinates, or fixed dates.

## Must Preserve

- `trigger = None` initialization in `model_decision_service.py`.
- D010 family sequence:
  - spouse pickup before home arrival,
  - no early departure after arrival,
  - fixed 9000 penalty remains avoided.
- D009 special-cargo mission behavior:
  - recognize special cargo,
  - move/wait near target when appropriate,
  - do not lose the task while restoring ordinary revenue.
- Mission lifecycle:
  - completed/expired missions should release locks and wait trackers.
- `history_action_name` helper:
  - history parsing must handle the current action record shape.

## Next Optimization Direction

Work in this order:

1. Centralize hard-window safety.
   - Cover `quiet_hours`, `home_nightly`, `hard_stay`, and urgent mission deadlines.
   - Ensure planner and advisor cannot execute actions that break these hard constraints.

2. Make advisor output pass safety validation.
   - Validate `choose_candidate`, override `take_order`, override `reposition`, and override `wait`.
   - If rejected, fall back to a hard-window-safe action.

3. Reduce advisor calls.
   - Do not call with only wait candidates.
   - Do not call when risky candidates are empty and there is no mission/unknown-rule conflict.
   - Add same-day same-reason limits, unchanged-candidate hashing, wait-result breakers, and safety-rejection breakers.

4. Classify candidate risk.
   - `safe`
   - `soft_risk`
   - `finite_budget_risk`
   - `hard_window_risk`
   - `illegal`
   - Only `soft_risk` and `finite_budget_risk` should be negotiable by the LLM.

5. Revisit D003-style finite budget deadlocks.
   - The LLM should compare expected profit, estimated penalty, remaining days, and opportunity cost.
   - The result must be an executable action, not another explanation.

6. Improve daily rest planning.
   - Plan rest earlier in the day.
   - Use quiet/home windows when possible.
   - Avoid last-minute rescue waits as the main mechanism.

## Useful Validation Commands

Run a full simulation:

```powershell
cd E:\its4learning\car-demo-2.0\demo\server
python main.py config/config.json
cd ..
python calc_monthly_income.py
```

Static hardcoding scan:

```powershell
rg -n "cargo_dataset|drivers\.json|server/data|driver_id\s*==|D00[0-9]|240646" demo\agent -g "*.py"
```

Syntax check:

```powershell
python -c "import pathlib; [compile(p.read_text(encoding='utf-8'), str(p), 'exec') for p in pathlib.Path('demo/agent').glob('*.py')]; print('syntax ok')"
```

## Target Metrics

Immediate target:

```text
failed_driver_count = 0
validation_error = null
total_net_income_all_drivers > 192484
total_preference_penalty < 15000
total_token_usage < 120000
```

Driver-level observation targets:

```text
D007 quiet-hours penalty <= 500
D009 nightly-home penalty <= 2700 and net income > 0
D010 fixed 9000 penalty remains 0
D003 net income > 8000 with token usage < 30000
```
