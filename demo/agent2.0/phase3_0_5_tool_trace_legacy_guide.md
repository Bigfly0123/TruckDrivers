# TruckDrivers Phase 3.0.5 指导方案：Tool Layer + Diagnostic Trace + Legacy Boundary

## 0. 本阶段定位

Phase 3.0 已经完成第一刀：把旧的 `ModelDecisionService.decide()` 主流程迁移到：

```text
AgentState
-> GraphRunner
-> graph_nodes
-> adapters
-> old modules
-> TraceLogger
```

这说明主流程已经从“大函数式决策”变成了“graph workflow skeleton”。

但是当前系统仍然存在一个核心问题：

```text
Phase 3.0 只是把旧策略逻辑放进了新 graph 外壳。
旧策略 bug 还在，收益不一定提升。
```

Phase 3.0.5 的目标不是修 D001、D004、continuous_rest、time window、收益下降等局部策略问题，而是完成 Phase 3.0 的架构收口，让项目真正具备进入 Phase 3.1 的条件。

本阶段只做三件事：

```text
1. 显式化 Python deterministic Tool Layer
2. 增强 Diagnostic Trace / Validation Report
3. 整理 Legacy 模块边界
```

本阶段完成后，项目结构应更接近主流 Agent 框架：

```text
GraphRunner = workflow orchestration
AgentState = typed state
GraphNodes = workflow nodes
Tools = deterministic facts / calculations / validation
Adapters = legacy compatibility bridge
Agents = LLM reasoning / candidate_id selection
SafetyGate = final hard validation
TraceLogger = observability
```

---

## 1. 本阶段绝对不要做什么

为了避免重新陷入 Phase 2 后期那种“不断修小 bug、跳不出来”的状态，本阶段明确禁止以下事项。

### 1.1 不修局部策略 bug

不要修：

```text
D001 为什么先休息
D002 为什么 rest 多
D003 为什么某个订单没接
D004 为什么时间窗口导致 wait
continuous_rest 剩余判断
partial rest candidate 语义
load_time_window 过严
forbid_action_in_time_window 过严
某个 constraint penalty 数值
某个司机收益下降
```

这些问题后续由 Phase 3.1 / 3.2 / 3.3 的战略规划、反思记忆和机会价值模块解决。

Phase 3.0.5 只做架构收口，不做策略调参。

---

### 1.2 不新增 Phase 3.1 以后的 Agent

不要新增：

```text
StrategicPlannerAgent
DayPlan
MemoryStore
ReflectionAgent
OpportunityAnalyst
FutureValueEstimator
LookaheadSimulator
Multi-agent debate
Crew / AutoGen style role agents
```

这些都留到后续阶段。

---

### 1.3 不重写旧算法

不要重写：

```text
PreferenceCompiler
CandidateFactBuilder
ConstraintEvaluator
LlmDecisionAdvisor
SafetyGate
StateTracker
ConstraintRuntimeState
```

本阶段可以包装它们，但不要大改它们的行为。

---

### 1.4 不改变最终动作边界

必须保持：

```text
final action must come from selected_candidate_id
LLM cannot directly invent executable actions
SafetyGate remains final hard validation
fallback only returns safe wait
fallback cannot make profit-seeking decisions
```

---

## 2. Phase 3.0.5 的核心目标

### 2.1 目标 A：显式 Tool Layer

当前 Phase 3.0 大致是：

```text
graph_node -> adapter -> old_module
```

Phase 3.0.5 后应变为：

```text
graph_node -> tool -> adapter -> old_module
```

其中：

```text
tools = 长期稳定接口
adapters = 临时兼容旧代码
old modules = 现阶段复用的实现
```

Tool Layer 不一定立刻重写旧逻辑，但目录结构和调用边界必须先建立。

---

### 2.2 目标 B：诊断型 Trace

当前 trace 能看到 node 执行情况，但还不够回答：

```text
为什么没接单？
为什么选择 wait？
为什么 fallback？
为什么 SafetyGate reject？
是没有合法订单，还是 Advisor 选了保守动作？
best valid order 和 selected candidate 差多少？
dominant hard invalid reason 是什么？
```

Phase 3.0.5 后，每一步决策至少应能回答：

```text
1. 当前有多少候选？
2. 有多少 valid order？
3. 有多少 profitable valid order？
4. best valid order 是什么？
5. selected candidate 是什么？
6. selected candidate 是否为 best valid order？
7. 如果选择 wait，是因为没有 profitable order，还是因为约束阻塞？
8. 如果 fallback，是哪个节点导致的？
9. 如果 SafetyGate reject，原 selected_candidate 是什么？
```

---

### 2.3 目标 C：Legacy Boundary

旧模块不要一删了之，但必须明确身份。

需要区分：

```text
still-used legacy tools:
    被 phase3/tools 或 adapters 调用，继续保留

legacy main-control modules:
    不再被 Phase 3 graph 调用，只作为参考或回退
```

旧主控模块需要移动到 `demo/agent/legacy/`，或加清晰的 `LEGACY MODULE` 注释。

---

## 3. 推荐目录结构

Phase 3.0.5 后，建议目录结构如下：

```text
demo/agent/
  model_decision_service.py

  phase3/
    __init__.py

    agent_state.py
    graph_runner.py
    trace_logger.py
    schemas.py

    graph_nodes/
      __init__.py
      observe_node.py
      preference_node.py
      runtime_node.py
      candidate_node.py
      constraint_node.py
      advisor_node.py
      safety_node.py
      emit_node.py

    tools/
      __init__.py
      simulation_tool.py
      state_tool.py
      preference_tool.py
      candidate_tool.py
      constraint_tool.py
      advisor_tool.py
      safety_tool.py
      diagnostic_tool.py

    adapters/
      __init__.py
      legacy_preference_adapter.py
      legacy_runtime_adapter.py
      legacy_candidate_adapter.py
      legacy_constraint_adapter.py
      legacy_advisor_adapter.py
      legacy_safety_adapter.py

    utils/
      __init__.py
      json_cleaner.py
      candidate_summary.py

    validation/
      __init__.py
      validate_phase3_run.py

  legacy/
    __init__.py
    candidate_safety_filter.py
    llm_mission_planner.py
    mission_executor.py
    mission_models.py
    mission_replanner.py
```

如果暂时不想移动旧文件，可以先在旧文件顶部加入：

```python
"""
LEGACY MODULE.

This module is not used by the Phase 3 graph workflow.
Kept only for rollback, comparison, or historical reference.
Do not reintroduce it as a decision-control component.
"""
```

但长期建议移动到 `demo/agent/legacy/`。

---

## 4. Tool Layer 设计

### 4.1 Tool Layer 的职责边界

Tools 负责：

```text
Simulation API 调用
deterministic state transformation
schema validation
candidate materialization
candidate fact calculation
constraint evaluation
candidate splitting
advisor input preparation
SafetyGate validation
diagnostic summary generation
```

Tools 不负责：

```text
自然语言偏好理解
战略规划
反思
长期收益预测
多 Agent debate
自由生成 action
```

---

### 4.2 Tool 和 Adapter 的区别

必须写进代码注释里：

```text
Tool = Phase 3 long-term stable interface
Adapter = temporary bridge to legacy implementation
```

示例：

```python
class CandidateTool:
    """
    Phase 3 deterministic candidate tool.

    This is the stable interface used by graph nodes.
    Internally it may call LegacyCandidateAdapter during Phase 3.0.5.
    Future phases can replace the adapter without changing graph nodes.
    """
```

---

## 5. 具体文件要求

## 5.1 `tools/simulation_tool.py`

职责：

```text
封装 SimulationApiPort 调用
获取 driver_status
获取 visible_cargo
获取 decision_history
```

建议接口：

```python
class SimulationTool:
    def __init__(self, api):
        self.api = api

    def observe(self, driver_id: str) -> dict:
        ...
```

输出建议包含：

```python
{
    "driver_status": ...,
    "current_location": ...,
    "current_time": ...,
    "current_day": ...,
    "visible_cargo": ...,
    "decision_history": ...
}
```

注意：

```text
不要在 SimulationTool 中做策略选择。
不要过滤 cargo，除非是 API 本身要求。
```

---

## 5.2 `tools/preference_tool.py`

职责：

```text
包装当前 legacy preference adapter
生成 preference_rules / constraints
做基础 schema 检查
```

建议接口：

```python
class PreferenceTool:
    def __init__(self, legacy_preference_adapter):
        self.legacy = legacy_preference_adapter

    def build_constraints(self, state: AgentState) -> AgentState:
        ...
```

注意：

```text
Phase 3.0.5 不引入 LLM PreferenceInterpreter。
PreferenceCompiler 继续作为 temporary adapter / normalizer 使用。
不要把 keyword if/else 规则继续扩张。
```

代码注释里应明确：

```text
This is a temporary Phase 3.0.5 tool.
In Phase 3.1+, this may be preceded or replaced by PreferenceInterpreterAgent.
```

---

## 5.3 `tools/state_tool.py`

职责：

```text
构造 runtime state
维护当前时间、位置、day、history summaries
包装 StateTracker / ConstraintRuntimeState
```

建议接口：

```python
class StateTool:
    def __init__(self, legacy_runtime_adapter):
        self.legacy = legacy_runtime_adapter

    def build_runtime_state(self, state: AgentState) -> AgentState:
        ...
```

输出字段写回：

```text
state.runtime_state
state.debug["runtime_summary"]
```

---

## 5.4 `tools/candidate_tool.py`

职责：

```text
生成基础 executable candidates
包装 CandidateFactBuilder
提供候选统计摘要
```

建议接口：

```python
class CandidateTool:
    def __init__(self, legacy_candidate_adapter):
        self.legacy = legacy_candidate_adapter

    def build_candidates(self, state: AgentState) -> AgentState:
        ...

    def summarize_raw_candidates(self, candidates: list) -> dict:
        ...
```

候选摘要至少包括：

```text
raw_candidate_count
take_order_candidate_count
wait_candidate_count
reposition_candidate_count
constraint_satisfy_candidate_count
candidate_source_counts
```

注意：

```text
本阶段不改变候选生成逻辑。
不新增 future value。
不调整 rest candidate。
```

---

## 5.5 `tools/constraint_tool.py`

职责：

```text
包装 ConstraintEvaluator
评估 candidates
拆分 valid / soft_risk / hard_invalid
统计 hard invalid reason
统计 valid/soft_risk order 质量
```

建议接口：

```python
class ConstraintTool:
    def __init__(self, legacy_constraint_adapter):
        self.legacy = legacy_constraint_adapter

    def evaluate_candidates(self, state: AgentState) -> AgentState:
        ...

    def summarize_constraints(self, state: AgentState) -> dict:
        ...
```

写回字段：

```text
state.evaluated_candidates
state.valid_candidates
state.soft_risk_candidates
state.hard_invalid_candidates
state.debug["constraint_summary"]
```

summary 至少包括：

```text
candidate_count
valid_count
soft_risk_count
hard_invalid_count

valid_order_count
valid_profitable_order_count
soft_risk_order_count
soft_risk_profitable_order_count

best_valid_order_id
best_valid_order_net
best_soft_risk_order_id
best_soft_risk_order_net_after_penalty

hard_invalid_reason_counts
dominant_hard_invalid_reason
```

注意：

```text
本阶段不要改变 constraint evaluator 的判定逻辑。
只增强 summary。
```

---

## 5.6 `tools/advisor_tool.py`

职责：

```text
准备 Advisor 输入
调用 legacy LlmDecisionAdvisor
解析 selected_candidate_id
生成 advisor summary
```

建议接口：

```python
class AdvisorTool:
    def __init__(self, legacy_advisor_adapter):
        self.legacy = legacy_advisor_adapter

    def decide(self, state: AgentState) -> AgentState:
        ...

    def summarize_advisor_result(self, state: AgentState) -> dict:
        ...
```

summary 至少包括：

```text
selected_candidate_id
selected_candidate_source
selected_candidate_action
selected_candidate_estimated_net
selected_candidate_penalty_exposure
selected_candidate_estimated_net_after_penalty
advisor_reason
advisor_confidence 如果有
candidate_pool_size_sent_to_advisor
```

注意：

```text
LLM 仍只能选择 candidate_id。
不要让 LLM 输出自由 action。
不要在 AdvisorTool 里做 fallback 赚钱策略。
```

---

## 5.7 `tools/safety_tool.py`

职责：

```text
包装 SafetyGate
最终 hard validation
如果 SafetyGate reject，记录 reject reason
必要时 fallback safe wait
```

建议接口：

```python
class SafetyTool:
    def __init__(self, legacy_safety_adapter):
        self.legacy = legacy_safety_adapter

    def validate(self, state: AgentState) -> AgentState:
        ...
```

summary 至少包括：

```text
safety_checked
safety_passed
safety_rejected
safety_reject_reason
candidate_before_safety
final_candidate_after_safety
fallback_used
fallback_reason
```

注意：

```text
SafetyGate 不负责赚钱。
SafetyGate 不重新选择收益更高订单。
fallback 只做 safe wait。
```

---

## 5.8 `tools/diagnostic_tool.py`

职责：

```text
把当前一步决策总结成诊断信息
解释为什么选了当前 candidate
帮助后续 Phase 3.1 / 3.3 判断是否需要 planner / future value
```

建议接口：

```python
class DiagnosticTool:
    def build_decision_diagnosis(self, state: AgentState) -> dict:
        ...
```

诊断字段建议：

```text
decision_type
selected_is_order
selected_is_wait
selected_is_reposition

why_no_order_selected
why_wait_selected
why_fallback_used

has_valid_profitable_order
best_valid_order_id
best_valid_order_net
selected_candidate_id
selected_candidate_net
selected_vs_best_valid_net_gap

dominant_hard_invalid_reason
hard_invalid_reason_counts

advisor_chose_wait_despite_profitable_order
safety_rejected_advisor_choice
candidate_pool_empty
only_wait_candidates_available
```

规则只做诊断，不做决策。

例如：

```python
advisor_chose_wait_despite_profitable_order = (
    selected_action == "wait"
    and valid_profitable_order_count > 0
)
```

这不是修 bug，只是让日志显示：

```text
Advisor 在有赚钱订单时仍选择 wait。
```

---

## 6. graph_nodes 改造要求

Phase 3.0 当前 node 可能直接依赖 adapters。Phase 3.0.5 后应改成优先依赖 tools。

### 6.1 改造前

```text
CandidateNode -> LegacyCandidateAdapter -> CandidateFactBuilder
```

### 6.2 改造后

```text
CandidateNode -> CandidateTool -> LegacyCandidateAdapter -> CandidateFactBuilder
```

同理：

```text
PreferenceNode -> PreferenceTool -> LegacyPreferenceAdapter
RuntimeNode -> StateTool -> LegacyRuntimeAdapter
ConstraintNode -> ConstraintTool -> LegacyConstraintAdapter
AdvisorNode -> AdvisorTool -> LegacyAdvisorAdapter
SafetyNode -> SafetyTool -> LegacySafetyAdapter
EmitNode -> DiagnosticTool / TraceLogger
```

### 6.3 node 的职责

node 只负责：

```text
从 AgentState 读输入
调用对应 Tool
把 Tool 输出写回 AgentState
记录 node-level trace
```

node 不应该直接写复杂业务逻辑。

---

## 7. AgentState 需要补充的字段

如果当前 `AgentState` 还没有这些字段，建议补充：

```python
tool_summaries: dict = field(default_factory=dict)
diagnostics: dict = field(default_factory=dict)
run_id: str | None = None
step_id: str | None = None
node_errors: list = field(default_factory=list)
fallback_used: bool = False
fallback_reason: str | None = None
```

或者使用已有 `debug` 字段承载也可以，但要统一命名。

建议结构：

```text
state.debug["candidate_summary"]
state.debug["constraint_summary"]
state.debug["advisor_summary"]
state.debug["safety_summary"]
state.debug["decision_diagnosis"]
```

不要让 summary 分散在多个不统一字段里。

---

## 8. TraceLogger 增强要求

TraceLogger 应至少支持以下 event：

```text
node_start
node_end
node_error
tool_summary
decision_diagnosis
final_action_summary
run_summary
```

### 8.1 node_start

字段：

```text
event
run_id
driver_id
node
timestamp
current_day
current_time
```

### 8.2 node_end

字段：

```text
event
run_id
driver_id
node
timestamp
duration_ms
summary
```

### 8.3 tool_summary

字段：

```text
event
run_id
driver_id
tool
timestamp
summary
```

### 8.4 decision_diagnosis

字段：

```text
event
run_id
driver_id
timestamp
diagnosis
```

### 8.5 final_action_summary

字段：

```text
event
run_id
driver_id
timestamp
selected_candidate_id
final_action
fallback_used
safety_passed
diagnosis
```

---

## 9. 兼容旧 `agent_decisions.jsonl`

当前可能已有：

```text
agent_graph_trace.jsonl
agent_decisions.jsonl
```

Phase 3.0.5 不需要改变这个设计。

但 `agent_decisions.jsonl` 的每条记录应更偏“每一步最终决策摘要”，包含：

```text
driver_id
current_day
current_time
current_location

visible_cargo_count
candidate_count
valid_count
soft_risk_count
hard_invalid_count

valid_order_count
valid_profitable_order_count
best_valid_order_id
best_valid_order_net

selected_candidate_id
selected_candidate_source
selected_candidate_action
selected_candidate_estimated_net
selected_candidate_penalty_exposure
selected_candidate_estimated_net_after_penalty

dominant_hard_invalid_reason
hard_invalid_reason_counts

fallback_used
fallback_reason
safety_rejected
safety_reject_reason

advisor_reason
diagnosis
```

这会让后续分析不必打开完整 graph trace。

---

## 10. Validation Report

新增：

```text
demo/agent/phase3/validation/validate_phase3_run.py
```

或者放在：

```text
demo/scripts/validate_phase3_run.py
```

二选一即可，但建议放在 `phase3/validation/`，体现它服务 Phase 3。

### 10.1 输入

默认读取：

```text
demo/results/logs/agent_graph_trace.jsonl
demo/results/logs/agent_decisions.jsonl
demo/results/logs/server_runtime.log
```

如果路径不同，可通过 CLI 参数传入。

### 10.2 输出

输出 markdown 报告：

```text
demo/results/logs/phase3_validation_report.md
```

### 10.3 报告内容

报告至少包含：

```text
1. 总事件数
2. driver 数量
3. node_start / node_end / node_error 数量
4. 每个 node 的 error count
5. fallback_used 次数
6. safety_rejected 次数
7. final_action missing 次数
8. 每个 driver 的 action 分布
9. 每个 driver 的 wait / take_order / reposition 比例
10. 每个 driver 的 dominant_hard_invalid_reason top 10
11. 有 profitable valid order 但选择 wait 的次数
12. candidate_pool_empty 次数
13. only_wait_candidates_available 次数
14. selected_vs_best_valid_net_gap 的均值/最大值
15. 是否满足 Phase 3.0.5 验收标准
```

示例报告结构：

```markdown
# Phase 3.0.5 Validation Report

## Run Summary
- drivers:
- total decisions:
- node errors:
- fallback count:
- safety reject count:

## Driver Action Distribution
| driver | take_order | wait | reposition | fallback |

## Diagnostic Warnings
| driver | warning | count |

## Blocking Constraint Summary
| driver | reason | count |

## Phase 3.0.5 Acceptance
- graph runnable: pass/fail
- tool layer active: pass/fail
- trace summaries present: pass/fail
- no blocking node errors: pass/fail
- ready for Phase 3.1: yes/no
```

注意：validation report 只诊断，不修策略。

---

## 11. Legacy 整理要求

### 11.1 识别 legacy-only 文件

重点检查以下文件是否仍被 Phase 3 graph / tools / adapters 调用：

```text
candidate_safety_filter.py
llm_mission_planner.py
mission_executor.py
mission_models.py
mission_replanner.py
```

如果没有被调用，则：

方案 A：移动到

```text
demo/agent/legacy/
```

方案 B：加 LEGACY 注释。

推荐方案 A，但如果担心 import 路径风险，可以先用方案 B。

---

### 11.2 禁止误移仍在用的工具模块

不要移动：

```text
preference_compiler.py
preference_constraints.py
constraint_evaluator.py
constraint_runtime.py
planner.py
state_tracker.py
llm_decision_advisor.py
safety_gate.py
geo_utils.py
agent_models.py
action_contract.py
```

这些虽然是旧文件，但仍然是当前 tools/adapters 的底层实现。

它们不是 legacy main-control，它们是 still-used deterministic / reasoning components。

---

## 12. ModelDecisionService 清理建议

如果当前 `ModelDecisionService` 中仍保留大量 legacy 初始化，只为 `_decide_legacy()` 服务，可以做轻量整理。

目标：

```text
ModelDecisionService 默认只代表 Phase 3 graph entrypoint。
legacy decide 不应污染默认入口。
```

可以选择：

### 12.1 保守方案

保留 `_decide_legacy()`，但加注释：

```python
"""
Legacy fallback path.
Not used by default Phase 3 graph workflow.
Kept only for rollback/comparison.
"""
```

并确保 `decide()` 默认只走 graph。

### 12.2 更清晰方案

新建：

```text
demo/agent/legacy_decision_service.py
```

把 `_decide_legacy()` 和相关 legacy 初始化移过去。

`model_decision_service.py` 只保留：

```text
__init__:
    self._graph_runner = build_default_graph(api)

decide:
    state = AgentState(...)
    final_state = self._graph_runner.run(state)
    return final_state.final_action
```

如果移动风险太大，本阶段可以先不做，只加注释。

---

## 13. 验收标准

Phase 3.0.5 通过的最低标准：

```text
1. demo/server/main.py 能运行；
2. calc_monthly_income.py 能运行；
3. graph_nodes 不再直接调用 legacy adapters，而是通过 tools；
4. tools 层存在且职责清晰；
5. adapters 仍可存在，但被标注为 compatibility bridge；
6. trace 中有 candidate_summary / constraint_summary / advisor_summary / safety_summary / decision_diagnosis；
7. agent_decisions.jsonl 中有每一步最终决策摘要；
8. validation report 能生成；
9. 不出现大量 node_error；
10. 不出现 final_action missing；
11. fallback 只用于 safe wait；
12. final_action 仍来自 selected_candidate_id 或 safe fallback；
13. 没有新增 StrategicPlannerAgent / MemoryStore / ReflectionAgent / OpportunityAnalyst；
14. 没有修改 continuous_rest / D001 / D004 等局部策略；
15. 后续 Phase 3.1 可以自然插入 StrategicPlannerAgent + DayPlan。
```

---

## 14. 本阶段完成后应如何判断是否进入 Phase 3.1

可以进入 Phase 3.1 的条件：

```text
1. Phase 3 graph 能完整跑；
2. Tool Layer 分层清楚；
3. Diagnostic Trace 能解释每一步；
4. Validation Report 能自动生成；
5. Legacy 边界清楚；
6. 没有框架级阻塞 bug；
7. 收入下降可以接受，只要不是 graph 崩溃导致。
```

不能进入 Phase 3.1 的情况：

```text
1. GraphRunner 经常 node_error；
2. final_action 经常为空；
3. SafetyGate 接口不稳定；
4. fallback 大量触发且原因不明；
5. trace 缺少 selected_candidate / candidate summary；
6. tools 层没有建立，StrategicPlannerAgent 无法稳定读取 facts；
7. 旧主控模块又被重新接回主流程。
```

---

## 15. 给代码 Agent 的完整执行提示词

可以直接复制以下提示词给代码 Agent。

```text
现在进入 TruckDrivers Phase 3.0.5。目标不是修收益，不是修 D001/D004/continuous_rest 等局部策略 bug，也不是新增多 Agent，而是对 Phase 3.0 graph skeleton 做架构收口，为 Phase 3.1 StrategicPlannerAgent + DayPlan 做准备。

本阶段只做三件事：
1. 显式化 Python deterministic Tool Layer；
2. 增强 Diagnostic Trace / Validation Report；
3. 整理 Legacy 模块边界。

请严格遵守：
- 不新增 StrategicPlannerAgent；
- 不新增 DayPlan；
- 不新增 MemoryStore / ReflectionAgent；
- 不新增 OpportunityAnalyst / FutureValueEstimator；
- 不重写旧策略算法；
- 不修改 continuous_rest / D001 / D004 等局部策略；
- 不让 LLM 自由生成 action；
- final action 必须来自 selected_candidate_id 或 safe fallback；
- SafetyGate 仍是最终 hard validation；
- fallback 只能 safe wait，不能负责赚钱。

请新增目录：

demo/agent/phase3/tools/
  __init__.py
  simulation_tool.py
  state_tool.py
  preference_tool.py
  candidate_tool.py
  constraint_tool.py
  advisor_tool.py
  safety_tool.py
  diagnostic_tool.py

tools 是 Phase 3 的长期稳定接口，adapters 是临时 legacy compatibility bridge。graph_nodes 应优先调用 tools，而不是直接调用 legacy adapters。tools 内部可以暂时调用 adapters 或旧模块，保持行为不变。

请增强 trace summary：
- candidate_summary
- constraint_summary
- advisor_summary
- safety_summary
- decision_diagnosis

agent_decisions.jsonl 每一步最终摘要应包含：
- driver_id
- current_day/current_time/current_location
- visible_cargo_count
- candidate_count
- valid_count
- soft_risk_count
- hard_invalid_count
- valid_order_count
- valid_profitable_order_count
- best_valid_order_id
- best_valid_order_net
- best_soft_risk_order_id
- best_soft_risk_order_net_after_penalty
- selected_candidate_id
- selected_candidate_source
- selected_candidate_action
- selected_candidate_estimated_net
- selected_candidate_penalty_exposure
- selected_candidate_estimated_net_after_penalty
- dominant_hard_invalid_reason
- hard_invalid_reason_counts
- fallback_used
- fallback_reason
- safety_rejected
- safety_reject_reason
- advisor_reason
- diagnosis

请新增 validation report：
demo/agent/phase3/validation/validate_phase3_run.py
或 demo/scripts/validate_phase3_run.py

它读取 agent_graph_trace.jsonl / agent_decisions.jsonl / server_runtime.log，输出 phase3_validation_report.md，统计：
- total decisions
- node error counts
- fallback count
- safety reject count
- final_action missing count
- per-driver action distribution
- per-driver dominant hard invalid reasons
- profitable valid order but selected wait count
- selected_vs_best_valid_net_gap
- acceptance checklist

Legacy 整理：
- 检查 candidate_safety_filter.py、llm_mission_planner.py、mission_executor.py、mission_models.py、mission_replanner.py 是否仍被 Phase 3 graph/tools/adapters 调用。
- 如果不再被调用，移动到 demo/agent/legacy/ 或加 LEGACY MODULE 注释。
- 不要移动仍被 tools/adapters 调用的核心旧模块，例如 PreferenceCompiler、CandidateFactBuilder、ConstraintEvaluator、LlmDecisionAdvisor、SafetyGate。

验收：
1. demo/server/main.py 可运行；
2. calc_monthly_income.py 可运行；
3. tools 层存在，graph_nodes 通过 tools 调用底层能力；
4. trace 中有 diagnostic summaries；
5. validation report 可生成；
6. 没有大量 node_error；
7. final action 不缺失；
8. 没有引入 Phase 3.1+ 的功能；
9. 没有回到 Phase 2 的局部 bug 修复路线。
```

---

## 16. Phase 3.0.5 完成后的预期状态

完成后，系统仍然可能收入不高，D001 仍然可能休息过多，D004 仍然可能 wait 很多。

这是允许的。

Phase 3.0.5 的成功标志不是收入提升，而是：

```text
架构分层清楚；
工具接口清楚；
trace 诊断清楚；
legacy 边界清楚；
后续可以稳健进入 Phase 3.1。
```

Phase 3.1 才开始真正增强 agentic intelligence：

```text
StrategicPlannerAgent
DayPlan
day-level rest/profit strategy
planner context injected into Advisor
```

Phase 3.0.5 不要提前做这些。
