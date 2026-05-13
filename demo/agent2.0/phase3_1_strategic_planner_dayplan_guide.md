# TruckDrivers Phase 3.1 指导方案：StrategicPlannerAgent + DayPlan

## 0. 本阶段定位

Phase 3.0 已经完成：

```text
ModelDecisionService.decide()
-> AgentState
-> GraphRunner
-> graph_nodes
-> TraceLogger
```

Phase 3.0.5 已经完成或接近完成：

```text
graph_node -> tool -> adapter -> old_module
DiagnosticTool
Validation Report
Legacy boundary
```

现在进入 Phase 3.1。

Phase 3.1 的目标不是修局部策略 bug，也不是做长期收益模型，而是给当前 graph workflow 增加第一个真正的 agentic planning 能力：

```text
StrategicPlannerAgent + DayPlan
```

也就是让系统从：

```text
当前状态 -> 当前候选 -> Advisor 单步选择
```

升级为：

```text
当前状态 -> 今日策略计划 DayPlan -> 当前候选 -> Advisor 在 DayPlan 指导下选择
```

Phase 3.1 的核心是：

```text
在不破坏现有 Tool Layer / SafetyGate / candidate_id 边界的前提下，
让 LLM Agent 先生成 day-level strategy，
再把 day_plan 注入 Advisor 决策上下文。
```

---

## 1. 本阶段要解决什么问题

当前 Phase 3.0.5 后，系统已经有 graph、tools、trace，但仍然本质上是：

```text
旧算法 + 新接口
```

因此仍会出现：

```text
D001 先休息太多
D004 时间窗口附近 wait 多
Advisor 只看当前 step
没有日级策略
没有“今天应该什么时候赚钱、什么时候休息”的计划
```

这些问题不能继续靠局部修补解决。Phase 3.1 要做的是：

```text
给每一天建立一个轻量战略计划 DayPlan，
让 Advisor 的当前动作选择不再完全孤立。
```

注意：Phase 3.1 不直接实现 FutureValueEstimator，不做复杂 lookahead，不做 memory/reflection。它只加入“今日策略指导”。

---

## 2. Phase 3.1 必须先合并的 Phase 3.0.5 收尾检查

进入 Phase 3.1 前，代码 Agent 应先检查 Phase 3.0.5 是否真的收口。如果没有完成，请和 Phase 3.1 一起补上。

### 2.1 检查 RuntimeNode 是否通过 StateTool

期望结构：

```text
RuntimeNode -> StateTool -> runtime adapter / compute_constraint_runtime_state
```

不应再是：

```text
RuntimeNode -> compute_constraint_runtime_state
```

检查命令：

```bash
grep -R "compute_constraint_runtime_state" demo/agent/phase3/graph_nodes
```

如果有命中，请改为通过 `StateTool`。

---

### 2.2 检查 SafetyNode 是否通过 SafetyTool

期望结构：

```text
SafetyNode -> SafetyTool -> LegacySafetyAdapter / SafetyGate
```

不应再是：

```text
SafetyNode -> LegacySafetyAdapter
SafetyNode -> fallback_wait
SafetyNode -> action_from_candidate
```

检查命令：

```bash
grep -R "LegacySafetyAdapter\|fallback_wait\|action_from_candidate" demo/agent/phase3/graph_nodes
```

如果有命中，请改为通过 `SafetyTool`。

---

### 2.3 检查 graph_nodes 是否绕过 tools 直接调用 adapters

期望：

```text
graph_nodes -> tools -> adapters -> old_module
```

检查命令：

```bash
grep -R "phase3.adapters" demo/agent/phase3/graph_nodes
```

理想结果：无输出。

如果有输出，请把对应 node 改成调用 tool。

---

### 2.4 确认 validation report 可生成

要求能运行：

```bash
python demo/agent/phase3/validation/validate_phase3_run.py
```

或者项目当前实际路径对应的命令。

应生成：

```text
demo/results/logs/phase3_validation_report.md
```

如果 validation report 还未生成，请在 Phase 3.1 开发前先修复。

---

## 3. Phase 3.1 绝对不要做什么

为了避免再次陷入 Phase 2 式局部补丁，本阶段明确禁止：

### 3.1 不修局部 bug

不要修：

```text
D001 continuous_rest
D004 time window / lunch break
load_time_window
partial rest candidate
forbid_action_in_time_window
某个司机某个订单没接
某个 penalty 数值
某个 hard/soft constraint 调参
```

这些不是 Phase 3.1 的目标。

---

### 3.2 不做 Phase 3.2 / 3.3 功能

不要新增：

```text
MemoryStore
ReflectionAgent
OpportunityAnalyst
FutureValueEstimator
LookaheadSimulator
Beam Search
Multi-agent Debate
CrewAI-style multi-agent collaboration
```

这些留到后续阶段。

---

### 3.3 不改变最终动作边界

必须保持：

```text
final action must come from candidate_id
LLM cannot invent executable action
SafetyGate remains final hard validation
fallback only safe wait
```

StrategicPlannerAgent 只能输出 strategy / guidance / priorities，不能直接输出最终 action。

---

## 4. Phase 3.1 的核心设计

### 4.1 新增核心概念：DayPlan

DayPlan 是“当天策略计划”，不是最终动作。

它回答：

```text
今天应该优先什么？
今天要避免什么？
今天的主要约束风险是什么？
今天什么时候适合休息？
今天是否应该先赚钱、先补约束，还是保持位置？
当前司机有没有明显风险，例如过度 wait？
```

DayPlan 不回答：

```text
现在具体接哪个订单？
现在具体执行哪个 action？
```

最终动作仍由 Advisor 从 candidate_id 中选择。

---

### 4.2 新增 StrategicPlannerAgent

StrategicPlannerAgent 是 Phase 3.1 的第一个新增 LLM Agent。

它负责：

```text
基于当前 AgentState、司机偏好、runtime state、候选统计、历史摘要，
生成 day-level strategy。
```

它不负责：

```text
计算距离
计算收益
判断硬约束是否违反
生成最终 action
绕过候选池
绕过 SafetyGate
```

---

### 4.3 DayPlan 生成频率

Phase 3.1 不需要每一步都重新生成完整 DayPlan。

建议：

```text
每天第一次决策时生成 DayPlan；
当 day 变化时重新生成；
当出现重大异常时可重新生成，但 Phase 3.1 可以先不做。
```

最小实现：

```text
if state.current_day != last_planned_day[driver_id]:
    generate new DayPlan
else:
    reuse existing DayPlan
```

DayPlan 可以存在内存里，暂不需要 MemoryStore。MemoryStore 是 Phase 3.2。

---

## 5. 新增文件建议

建议新增：

```text
demo/agent/phase3/planning/
  __init__.py
  day_plan.py
  day_plan_store.py

demo/agent/phase3/agents/
  __init__.py
  strategic_planner_agent.py

demo/agent/phase3/graph_nodes/planning_node.py
```

如果当前还没有 `agents/` 目录，请新增。

---

## 6. DayPlan Schema 设计

### 6.1 `planning/day_plan.py`

建议使用 dataclass 或 pydantic。为保持项目轻量，可以先用 dataclass。

示例：

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class DayPlan:
    driver_id: str
    day: int

    strategy_summary: str
    primary_goal: str
    secondary_goals: list[str] = field(default_factory=list)

    risk_focus: list[str] = field(default_factory=list)
    constraint_priorities: list[str] = field(default_factory=list)

    rest_strategy: str | None = None
    work_window_strategy: str | None = None
    location_strategy: str | None = None
    cargo_strategy: str | None = None

    avoid_behaviors: list[str] = field(default_factory=list)
    advisor_guidance: list[str] = field(default_factory=list)

    confidence: float | None = None
    reason: str | None = None

    raw_response: dict[str, Any] | None = None
```

### 6.2 字段含义

#### `strategy_summary`

一句话总结今日策略，例如：

```text
Prefer profitable in-area short orders before committing to long rest, while preserving enough time for required rest later.
```

#### `primary_goal`

今日最重要目标，例如：

```text
maximize_income_within_hard_constraints
```

可选值建议：

```text
maximize_income
satisfy_hard_constraints
balance_income_and_rest
avoid_penalty
recover_from_low_opportunity
maintain_location
```

不要让代码强依赖这些枚举，先作为文本即可。

#### `risk_focus`

今天最需要关注的风险，例如：

```text
["continuous_rest", "operate_within_area", "time_window"]
```

#### `rest_strategy`

例如：

```text
Do not take partial rest early if profitable valid orders exist and rest can still be completed later.
```

注意：这不是修 continuous_rest 逻辑，而是给 Advisor 的策略 guidance。

#### `advisor_guidance`

这是最重要字段，会注入 Advisor context。示例：

```text
- Prefer profitable valid orders over partial rest if rest remains feasible later.
- Choose wait only when no profitable valid/acceptable order exists or hard constraints block actions.
- Do not sacrifice hard constraints for income.
```

---

## 7. DayPlanStore 设计

### 7.1 `planning/day_plan_store.py`

Phase 3.1 可以使用简单内存 store，不引入持久化 MemoryStore。

```python
class DayPlanStore:
    def __init__(self):
        self._plans = {}

    def get(self, driver_id: str, day: int):
        return self._plans.get((driver_id, day))

    def set(self, plan):
        self._plans[(plan.driver_id, plan.day)] = plan

    def clear_driver(self, driver_id: str):
        ...
```

注意：

```text
DayPlanStore 不是 Phase 3.2 MemoryStore。
它只保存当前 run 内的 day plan。
不要跨实验持久化。
```

---

## 8. StrategicPlannerAgent 设计

### 8.1 `agents/strategic_planner_agent.py`

职责：

```text
输入 AgentState summary
输出 DayPlan JSON
```

它不能直接访问环境执行动作。

建议类：

```python
class StrategicPlannerAgent:
    def __init__(self, api=None):
        self.api = api

    def plan_day(self, state: AgentState) -> DayPlan:
        ...
```

如果现有 LLM API 调用方式在 `LlmDecisionAdvisor` 中，可以复用其 API 调用接口，但不要复制太多旧 Advisor 逻辑。

---

### 8.2 输入摘要

不要把全部 raw cargo 都丢给 planner。DayPlan 是日级策略，只需要 summary。

输入建议包含：

```text
driver_id
current_day
current_time
current_location

preference_summary
constraint_summary
runtime_summary

recent_action_summary
candidate_summary:
  visible_cargo_count
  raw_candidate_count
  valid_count
  soft_risk_count
  hard_invalid_count
  valid_order_count
  valid_profitable_order_count
  best_valid_order_net
  dominant_hard_invalid_reason

diagnostic_summary:
  advisor_chose_wait_despite_profitable_order
  candidate_pool_empty
  only_wait_candidates_available
```

不要传过多 full candidates，避免 planner 变成另一个 Advisor。

---

### 8.3 输出必须是结构化 JSON

StrategicPlannerAgent 应输出 JSON，例如：

```json
{
  "strategy_summary": "Prefer profitable legal orders during high-opportunity periods and schedule rest later if feasible.",
  "primary_goal": "balance_income_and_rest",
  "secondary_goals": ["avoid_hard_constraint_violation", "reduce_unnecessary_wait"],
  "risk_focus": ["continuous_rest", "time_window"],
  "constraint_priorities": ["hard_constraints_first", "avoid_penalty_when_action_would_make_recovery_impossible"],
  "rest_strategy": "Partial rest should not be prioritized over profitable valid orders if required rest can still be completed later.",
  "work_window_strategy": "Avoid starting actions that would enter prohibited work windows.",
  "location_strategy": "Prefer orders that remain within required operating area.",
  "cargo_strategy": "Prefer profitable valid cargo over idle wait.",
  "avoid_behaviors": ["unnecessary_partial_rest", "waiting_when_profitable_valid_orders_exist"],
  "advisor_guidance": [
    "If a profitable valid order exists and hard constraints remain feasible, prefer the order over partial rest.",
    "Choose wait only if no profitable valid/acceptable order exists or if action would make required constraints impossible.",
    "Never violate hard constraints for income."
  ],
  "confidence": 0.75,
  "reason": "Current diagnostics show wait/rest can dominate even when profitable valid orders exist."
}
```

必须做 JSON parse 和 fallback。

如果 LLM 输出失败，应返回 safe default plan：

```text
Follow hard constraints, prefer profitable valid orders, choose wait only when no safe profitable candidate exists.
```

---

## 9. 新增 PlanningNode

在 `graph_nodes/` 中新增：

```text
planning_node.py
```

流程：

```text
ObserveNode
-> PreferenceNode
-> RuntimeNode
-> CandidateNode
-> ConstraintNode
-> PlanningNode
-> AdvisorNode
-> SafetyNode
-> EmitNode
```

为什么 PlanningNode 放在 ConstraintNode 后？

因为 DayPlan 需要看到当天候选和约束诊断 summary，例如：

```text
当前是否有 profitable valid order
当前是否只有 wait
dominant hard invalid reason
```

如果放在 Candidate/Constraint 前，planner 看不到当前机会质量。

Phase 3.1 最小版可以每天第一次完整评估后生成 plan；当天后续 step 复用 plan。

---

## 10. AgentState 需要新增字段

在 `AgentState` 中新增：

```python
day_plan: Any | None = None
day_plan_context: dict = field(default_factory=dict)
```

或者强类型：

```python
day_plan: DayPlan | None = None
```

如果担心循环 import，可以用 `Any`，但建议尽量清晰。

还可以新增：

```python
planning_summary: dict = field(default_factory=dict)
```

或统一放入：

```python
state.debug["planning_summary"]
```

---

## 11. GraphRunner 改造

### 11.1 新增 PlanningNode 到默认 graph

当前 graph 顺序可能是：

```text
observe
preference
runtime
candidate
constraint
advisor
safety
emit
```

改为：

```text
observe
preference
runtime
candidate
constraint
planning
advisor
safety
emit
```

注意：

```text
PlanningNode 不能改变 candidates；
PlanningNode 不能改变 selected_candidate_id；
PlanningNode 只写 state.day_plan / state.debug["planning_summary"]。
```

---

## 12. AdvisorNode / AdvisorTool 改造

Advisor 需要接收 DayPlan。

### 12.1 Advisor input 增加 day_plan

在 `AdvisorTool` 或 legacy advisor context 中加入：

```python
advisor_context["day_plan"] = {
    "strategy_summary": state.day_plan.strategy_summary,
    "primary_goal": state.day_plan.primary_goal,
    "risk_focus": state.day_plan.risk_focus,
    "rest_strategy": state.day_plan.rest_strategy,
    "work_window_strategy": state.day_plan.work_window_strategy,
    "location_strategy": state.day_plan.location_strategy,
    "advisor_guidance": state.day_plan.advisor_guidance,
}
```

### 12.2 Advisor prompt 增强

不要大改 Advisor prompt，只加入 DayPlan section：

```text
DAY PLAN GUIDANCE:
The following day-level plan was generated by the StrategicPlannerAgent.
Use it as strategic guidance when choosing among candidate_id options.
It does not override hard constraints or SafetyGate.
It does not authorize actions outside the candidate list.

{day_plan}
```

必须强调：

```text
DayPlan is guidance, not an executable action.
Final choice must be one candidate_id from the provided candidates.
Hard constraints and SafetyGate override DayPlan.
```

---

## 13. DayPlan 与 candidate_id 边界

必须保证：

```text
StrategicPlannerAgent 输出 day plan
Advisor 输出 selected_candidate_id
SafetyGate 输出 final hard validation
```

禁止：

```text
StrategicPlannerAgent 直接输出 take_order_123
StrategicPlannerAgent 直接返回 final action
PlanningNode 修改 final_action
PlanningNode 删除 candidates
PlanningNode hard filter candidates
```

DayPlan 最多影响 Advisor 的 reasoning context。

---

## 14. Trace 增强

新增 trace event：

```text
day_plan_created
day_plan_reused
planning_summary
```

### 14.1 day_plan_created

字段：

```text
event
driver_id
day
timestamp
strategy_summary
primary_goal
risk_focus
advisor_guidance
confidence
reason
```

### 14.2 day_plan_reused

字段：

```text
event
driver_id
day
timestamp
strategy_summary
```

### 14.3 agent_decisions.jsonl 增加字段

每步 summary 增加：

```text
day_plan_summary
day_plan_primary_goal
day_plan_risk_focus
day_plan_rest_strategy
day_plan_advisor_guidance
day_plan_generated_this_step
```

不需要把完整 raw_response 放进每步 summary，避免日志过大。

---

## 15. Validation Report 增强

`validate_phase3_run.py` 需要增加 Phase 3.1 检查项：

```text
day_plan_created_count
day_plan_reused_count
drivers_with_day_plan
decisions_with_day_plan
decisions_missing_day_plan
planner_parse_error_count
planner_fallback_plan_count
```

报告中新增：

```markdown
## DayPlan Summary
| driver | day_plan_created | reused | missing | fallback_plan |

## Phase 3.1 Acceptance
- planning node executed: pass/fail
- day plan present in advisor context: pass/fail
- no final action generated by planner: pass/fail
- no Phase 3.2+ modules introduced: pass/fail
```

---

## 16. 测试策略

Phase 3.1 会改变 Advisor 输入，因此可能改变收益和行为。需要比 Phase 3.0.5 更认真测试，但仍不需要一开始全量。

### 16.1 第一层：单司机短测

先测 D001 或一个最能暴露 rest 问题的司机。

目标：

```text
PlanningNode 是否执行
DayPlan 是否生成
Advisor 是否收到 DayPlan
final_action 是否正常
SafetyGate 是否通过
```

### 16.2 第二层：四司机短测

使用之前的四个司机：

```text
D001
D002
D003
D004
```

目标：

```text
不同偏好类型都能生成 day plan
没有 node_error
没有 planner parse 大量失败
fallback 不异常
```

### 16.3 第三层：可选完整实验

如果四司机短测通过，再决定是否完整跑全量。

Phase 3.1 是策略输入变化，建议最终跑一次完整实验，但不要求开发完成后立刻反复跑。

---

## 17. 验收标准

Phase 3.1 通过的最低标准：

```text
1. Phase 3.0.5 收尾完成：
   - RuntimeNode -> StateTool
   - SafetyNode -> SafetyTool
   - graph_nodes 不直接调用 adapters

2. 新增 StrategicPlannerAgent；
3. 新增 DayPlan schema；
4. 新增 DayPlanStore；
5. 新增 PlanningNode；
6. GraphRunner 中 PlanningNode 位于 ConstraintNode 和 AdvisorNode 之间；
7. DayPlan 注入 Advisor context；
8. Advisor 仍只输出 selected_candidate_id；
9. StrategicPlannerAgent 不输出 final action；
10. SafetyGate 仍最终 hard validation；
11. Trace 中能看到 day_plan_created / day_plan_reused；
12. agent_decisions.jsonl 中能看到 day_plan summary；
13. validate_phase3_run.py 能统计 DayPlan 指标；
14. 四司机短测无框架级错误；
15. 没有新增 MemoryStore / ReflectionAgent / OpportunityAnalyst / FutureValueEstimator；
16. 没有修 D001/rest/time window 等局部策略 bug；
17. 没有回退到 legacy 主控模块。
```

---

## 18. 允许的行为变化

Phase 3.1 加了 DayPlan 后，行为变化是允许的。

可能出现：

```text
D001 不再那么早连续 partial rest
D004 在时间窗口前后更谨慎
某些司机 wait/take_order 比例变化
总收入上升或下降
```

不要因为某个司机收入下降就立刻修策略 bug。

Phase 3.1 首先验证：

```text
Planner 是否正确进入决策链
DayPlan 是否对 Advisor 产生上下文影响
Safety / candidate_id 边界是否仍然稳定
```

收益优化需要结合 Phase 3.2 / 3.3 进一步做。

---

## 19. 不要把 DayPlan 做成新规则系统

这是最重要的风险。

禁止代码写成：

```python
if day_plan.primary_goal == "avoid_penalty":
    return wait
```

或者：

```python
if "rest" in day_plan.rest_strategy:
    filter_orders()
```

DayPlan 只能是 Advisor 的上下文，不能变成 Python 规则主控。

正确方式：

```text
DayPlan -> Advisor context -> Advisor chooses candidate_id -> SafetyGate validates
```

---

## 20. 给代码 Agent 的完整执行提示词

可以直接复制以下提示词给代码 Agent。

```text
现在进入 TruckDrivers Phase 3.1。目标是新增 StrategicPlannerAgent + DayPlan，让系统具备 day-level strategy planning 能力。不要修 D001/rest/time window 等局部策略 bug，不要新增 Memory/Reflection/FutureValue，不要做 Phase 3.2/3.3 内容。

第一步先检查并补齐 Phase 3.0.5 收尾：
1. RuntimeNode 必须通过 StateTool，不要直接调用 compute_constraint_runtime_state。
2. SafetyNode 必须通过 SafetyTool，不要直接调用 LegacySafetyAdapter / fallback_wait / action_from_candidate。
3. graph_nodes 不应直接 import phase3.adapters。
4. validate_phase3_run.py 能生成 phase3_validation_report.md。

然后实现 Phase 3.1：

新增：
demo/agent/phase3/planning/
  __init__.py
  day_plan.py
  day_plan_store.py

demo/agent/phase3/agents/
  __init__.py
  strategic_planner_agent.py

demo/agent/phase3/graph_nodes/planning_node.py

要求：
1. DayPlan 是结构化 schema，包含：
   - driver_id
   - day
   - strategy_summary
   - primary_goal
   - secondary_goals
   - risk_focus
   - constraint_priorities
   - rest_strategy
   - work_window_strategy
   - location_strategy
   - cargo_strategy
   - avoid_behaviors
   - advisor_guidance
   - confidence
   - reason

2. StrategicPlannerAgent 输入 AgentState 的摘要，输出 DayPlan JSON。
   它只能生成 day-level strategy，不能生成 final action，不能直接选择 order。

3. DayPlanStore 只做当前 run 内存缓存：
   - 每个 driver/day 一个 DayPlan
   - day 变化时重新生成
   - 不做跨 run 持久化，MemoryStore 留到 Phase 3.2

4. 新增 PlanningNode，放在 ConstraintNode 和 AdvisorNode 之间：
   observe -> preference -> runtime -> candidate -> constraint -> planning -> advisor -> safety -> emit

5. PlanningNode 只能写：
   - state.day_plan
   - state.debug["planning_summary"]
   不能修改 candidates，不能修改 selected_candidate_id，不能修改 final_action。

6. AdvisorTool / AdvisorNode 要把 DayPlan 注入 Advisor context。
   Advisor prompt 增加 DAY PLAN GUIDANCE section：
   - DayPlan 是战略指导，不是 executable action；
   - final choice must be one candidate_id；
   - hard constraints and SafetyGate override DayPlan；
   - LLM 不能自由生成 action。

7. TraceLogger 增加：
   - day_plan_created
   - day_plan_reused
   - planning_summary

8. agent_decisions.jsonl 增加：
   - day_plan_summary
   - day_plan_primary_goal
   - day_plan_risk_focus
   - day_plan_rest_strategy
   - day_plan_advisor_guidance
   - day_plan_generated_this_step

9. validate_phase3_run.py 增加：
   - day_plan_created_count
   - day_plan_reused_count
   - decisions_with_day_plan
   - decisions_missing_day_plan
   - planner_parse_error_count
   - planner_fallback_plan_count

禁止：
- 不新增 MemoryStore / ReflectionAgent；
- 不新增 OpportunityAnalyst / FutureValueEstimator；
- 不做 lookahead / beam search；
- 不修 continuous_rest / D001 / D004 / time window；
- 不重写 CandidateFactBuilder / ConstraintEvaluator；
- 不让 DayPlan 变成 Python 规则系统；
- 不让 StrategicPlannerAgent 输出 final action；
- 不让 fallback 负责赚钱。

验收：
1. syntax ok；
2. Phase 3.1+ 禁止项除 StrategicPlannerAgent / DayPlan 外无命中；
3. demo/server/main.py 可跑；
4. 四司机短测通过；
5. PlanningNode 执行；
6. DayPlan 能生成或 fallback；
7. Advisor context 包含 day_plan；
8. final action 仍来自 candidate_id；
9. SafetyGate 仍最终 hard validation；
10. validation report 能统计 day plan 指标。
```

---

## 21. Phase 3.1 完成后如何判断是否进入 Phase 3.2

可以进入 Phase 3.2 的条件：

```text
1. DayPlan 稳定生成；
2. Advisor 能收到 DayPlan；
3. DayPlan 没有绕过 candidate_id / SafetyGate；
4. 四司机短测没有框架级错误；
5. validation report 能显示 planner metrics；
6. trace 能看出某一步 Advisor 是否受 DayPlan 指导；
7. 没有把 DayPlan 写成 Python 规则系统。
```

不能进入 Phase 3.2 的情况：

```text
1. DayPlan 经常 parse 失败；
2. Planner 输出 final action；
3. Advisor 绕过 candidate_id；
4. PlanningNode 修改 candidates 或 final_action；
5. SafetyGate 被绕过；
6. graph_nodes 又直接调用 adapters；
7. validation report 无法生成；
8. DayPlan 完全没有进入 advisor context。
```

---

## 22. 总结

Phase 3.1 是 TruckDrivers 从“新框架包旧算法”走向“真正 agentic decision system”的第一步。

本阶段的成功标志不是总收入立刻提高，而是：

```text
系统开始具备 day-level strategic planning；
Advisor 不再完全孤立地做单步候选选择；
DayPlan 能稳定注入决策上下文；
candidate_id / SafetyGate 边界仍然牢固；
后续 Memory / Reflection / FutureValue 可以自然接入。
```

Phase 3.1 做完后，下一步 Phase 3.2 才加入：

```text
MemoryStore + ReflectionAgent
```

不要在 Phase 3.1 提前做。
