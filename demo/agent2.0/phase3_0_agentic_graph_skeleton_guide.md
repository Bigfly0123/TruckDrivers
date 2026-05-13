# TruckDrivers Phase 3.0：Agentic Graph Skeleton 重构实施指南

## 0. 本文档目标

本文档只针对 **Phase 3.0**。

Phase 3.0 的目标不是修复某一个局部 bug，也不是立刻引入多个 Agent、Memory、Reflection 或 FutureValueEstimator，而是把当前 TruckDrivers agent 的主流程从一个较大的线性 `ModelDecisionService.decide()` 函数，重构为具有主流 Agent 框架风格的 **Typed State + Graph Nodes + Trace Logger** 架构。

Phase 3.0 的核心目标：

```text
现有可运行能力不丢失
+
主流程拆成清晰 graph nodes
+
AgentState 类型化
+
每个节点可观测、可追踪、可回放
+
后续 Phase 3.1 / 3.2 / 3.3 可以自然插入新 Agent 能力
```

Phase 3.0 **不追求立即提高收益**。它的主要价值是重构架构地基，让项目从“LLM 辅助的单体贪婪决策器”升级为“可扩展的 Agentic Workflow”。

---

## 1. Phase 3.0 的边界

### 1.1 本阶段要做什么

Phase 3.0 要做：

1. 新建 `demo/agent/phase3/` 架构目录；
2. 定义 typed `AgentState`；
3. 定义轻量 `GraphRunner`；
4. 定义统一 `TraceLogger`；
5. 将当前 `ModelDecisionService.decide()` 中的流程拆成 graph nodes；
6. 让每个 node 输入 `AgentState`，输出更新后的 `AgentState`；
7. 保留并复用当前已有能力模块；
8. 让 `ModelDecisionService.decide()` 变薄，只负责初始化 state、运行 graph、返回 final action；
9. 保证 `final_action` 必须来自 `selected_candidate_id`；
10. 保证 `SafetyGate` 仍然是最终 hard validation；
11. 保证 JSONL trace 一行一个合法 JSON；
12. 保证原有 `demo/server/main.py` 和 `demo/calc_monthly_income.py` 能继续运行。

---

### 1.2 本阶段不做什么

Phase 3.0 **不要做**：

1. 不要新增多个 Agent 角色；
2. 不要新增 `StrategicPlannerAgent`；
3. 不要新增 `DayPlan`；
4. 不要新增 `MemoryStore`；
5. 不要新增 `ReflectionAgent`；
6. 不要新增 `OpportunityAnalyst`；
7. 不要新增 `FutureValueEstimator`；
8. 不要做 beam search；
9. 不要把偏好解析完全改成 LLM；
10. 不要大规模重写 `PreferenceCompiler`、`CandidateFactBuilder`、`ConstraintEvaluator`；
11. 不要恢复 `MissionExecutor`、`MissionReplanner`、`CandidateSafetyFilter` 等旧主控模块；
12. 不要让 fallback 负责赚钱决策；
13. 不要让 LLM 自由编造 action；
14. 不要在本阶段追求收益显著提升。

本阶段最重要的是：**主流程骨架重构，不是策略算法大改。**

---

## 2. 总体设计原则

### 2.1 混合架构边界

Phase 3.0 采用 Agent + Tool + Guardrail 的混合架构。

```text
LLM Agent = strategy / reasoning / synthesis
Python = deterministic tools / schema validation / candidate materialization / constraint execution / trace
SafetyGate = final hard validation
Final Action = must come from candidate_id
```

更具体地说：

LLM 负责：

```text
1. 当前候选之间的多目标权衡；
2. 对收益、风险、约束、偏好之间的解释；
3. 输出结构化 decision result；
4. 给出简短 reason。
```

Python 负责：

```text
1. 调用仿真 API；
2. 读取司机状态、货源、历史；
3. 管理 typed AgentState；
4. 复用现有 preference / constraint / candidate 模块；
5. 计算时间、距离、收入、候选 facts；
6. 执行结构化约束；
7. 执行 SafetyGate；
8. 记录 trace；
9. 保证 final action 可执行。
```

重要边界：

```text
LLM 可以选择 candidate_id。
LLM 不可以直接生成未验证 action。
LLM 不可以绕过 SafetyGate。
SafetyGate 不负责赚钱，只负责硬合法校验。
Fallback 只能保命，不能主动赚钱。
```

---

### 2.2 旧模块的定位

Phase 3.0 不是从零重写。

现有模块继续保留，但角色要重新定位为 graph workflow 中的工具节点依赖。

| 旧模块 | Phase 3.0 定位 |
|---|---|
| `PreferenceCompiler` | temporary adapter / ConstraintSpec normalizer / validator |
| `compile_constraints` | structured constraints builder，暂时复用 |
| `StateTracker` | state observation and history adapter |
| `ConstraintRuntimeState` | runtime constraint facts builder |
| `CandidateFactBuilder` | executable base candidate and candidate facts builder |
| `ConstraintEvaluator` | deterministic structured constraint executor |
| `LlmDecisionAdvisor` | current Decision Agent / Advisor node backend |
| `SafetyGate` | final hard validation guardrail |
| `SimulationApiPort` | environment tool interface |

不要把这些模块理解为最终的 Agent 架构本身。它们在 Phase 3.0 中是工具和适配层。

---

### 2.3 为什么先不直接引入 LangGraph

Phase 3.0 采用 **LangGraph-style**，但不强依赖真实 LangGraph 包。

原因：

1. 当前比赛仿真环境特殊，final action 必须来自 candidate_id；
2. 现有代码已有大量领域模块，直接迁移到外部框架风险较高；
3. 现在真正需要的是 node/state/trace 的最小能力；
4. 自研 skeleton 更容易保持兼容；
5. 后续如果需要，可以把这些 node 平滑迁移到 LangGraph。

因此 Phase 3.0 要写成：

```text
LangGraph-compatible structure
but no hard dependency on LangGraph
```

---

## 3. 推荐目录结构

新增目录：

```text
demo/agent/phase3/
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

  adapters/
    __init__.py
    legacy_preference_adapter.py
    legacy_candidate_adapter.py
    legacy_constraint_adapter.py
    legacy_advisor_adapter.py
    legacy_safety_adapter.py

  utils/
    __init__.py
    json_cleaner.py
    summaries.py
```

可选目录，Phase 3.0 可以先建空包，不实现复杂逻辑：

```text
demo/agent/phase3/agents/
  __init__.py
  # Phase 3.1 再加入 strategic_planner_agent.py

 demo/agent/phase3/memory/
  __init__.py
  # Phase 3.2 再加入 memory_store.py

 demo/agent/phase3/evaluation/
  __init__.py
  # Phase 3.3 再加入 future_value_estimator.py
```

旧的主控类暂时不要删除。`ModelDecisionService` 仍然作为外部入口存在，但内部调用 Phase 3 graph。

---

## 4. AgentState 设计

### 4.1 文件位置

```text
demo/agent/phase3/agent_state.py
```

### 4.2 推荐实现方式

优先使用 Python `dataclass`。

如果项目已经稳定使用 Pydantic，也可以用 Pydantic。但为了减少依赖和迁移风险，Phase 3.0 建议先用 `dataclass`。

### 4.3 AgentState 字段建议

```python
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class AgentState:
    # identity
    driver_id: str
    request_id: str = ""
    step_id: Optional[int] = None

    # raw observation
    driver_status: Dict[str, Any] = field(default_factory=dict)
    current_time: Optional[int] = None
    current_day: Optional[int] = None
    current_location: Optional[Dict[str, Any]] = None
    visible_cargo: List[Dict[str, Any]] = field(default_factory=list)
    decision_history: List[Dict[str, Any]] = field(default_factory=list)

    # preference / constraints
    raw_preferences: Any = None
    preference_rules: List[Any] = field(default_factory=list)
    constraints: List[Any] = field(default_factory=list)
    constraint_runtime_state: Any = None

    # candidates
    raw_candidates: List[Any] = field(default_factory=list)
    evaluated_candidates: List[Any] = field(default_factory=list)
    valid_candidates: List[Any] = field(default_factory=list)
    soft_risk_candidates: List[Any] = field(default_factory=list)
    hard_invalid_candidates: List[Any] = field(default_factory=list)

    # advisor
    advisor_context: Dict[str, Any] = field(default_factory=dict)
    advisor_result: Dict[str, Any] = field(default_factory=dict)
    selected_candidate_id: Optional[str] = None
    selected_candidate: Any = None

    # safety / final action
    safety_result: Dict[str, Any] = field(default_factory=dict)
    final_action: Optional[Dict[str, Any]] = None
    fallback_used: bool = False
    fallback_reason: Optional[str] = None

    # observability
    trace: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    debug: Dict[str, Any] = field(default_factory=dict)
```

### 4.4 AgentState 的原则

1. `AgentState` 是 graph nodes 之间唯一主要载体；
2. node 不应依赖大量隐式全局变量；
3. node 可以读取 state，也可以写入 state；
4. 每个 node 只负责自己的字段；
5. `final_action` 只能在 `emit_node` 或 safety fallback 中产生；
6. 所有 errors 都应写入 `state.errors`，并记录 trace。

---

## 5. GraphRunner 设计

### 5.1 文件位置

```text
demo/agent/phase3/graph_runner.py
```

### 5.2 GraphRunner 职责

`GraphRunner` 负责按固定顺序执行 nodes。

Phase 3.0 不需要复杂动态路由，先用确定性线性图即可。

### 5.3 推荐节点顺序

```text
observe_state
-> preference_node
-> runtime_node
-> candidate_node
-> constraint_node
-> advisor_node
-> safety_node
-> emit_node
```

### 5.4 示例实现结构

```python
from typing import Callable, List
from .agent_state import AgentState

GraphNode = Callable[[AgentState], AgentState]

class GraphRunner:
    def __init__(self, nodes: List[GraphNode], trace_logger=None):
        self.nodes = nodes
        self.trace_logger = trace_logger

    def run(self, state: AgentState) -> AgentState:
        for node in self.nodes:
            node_name = getattr(node, "__name__", node.__class__.__name__)
            if self.trace_logger:
                self.trace_logger.node_start(state, node_name)
            try:
                state = node(state)
                if self.trace_logger:
                    self.trace_logger.node_end(state, node_name)
            except Exception as exc:
                if self.trace_logger:
                    self.trace_logger.node_error(state, node_name, exc)
                state.errors.append({
                    "node": node_name,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                })
                raise
        return state
```

### 5.5 Phase 3.0 暂不做复杂 edge

暂时不要做：

```text
conditional edge
multi-agent routing
handoff
retry loop
reflection loop
beam expansion
```

这些留到后续 Phase。

---

## 6. TraceLogger 设计

### 6.1 文件位置

```text
demo/agent/phase3/trace_logger.py
```

### 6.2 TraceLogger 目标

TraceLogger 必须做到：

1. 每个 node 有 start/end/error trace；
2. 每一步决策有完整 summary；
3. JSONL 严格一行一个 JSON；
4. 清洗换行、多余空白、不可序列化对象；
5. 能帮助判断候选数量、约束过滤、Advisor 选择、安全校验；
6. 不泄露过长 prompt 或过大对象。

---

### 6.3 JSON 清洗工具

文件：

```text
demo/agent/phase3/utils/json_cleaner.py
```

建议实现：

```python
import dataclasses
from typing import Any


def clean_for_json(value: Any, max_str_len: int = 1000) -> Any:
    if dataclasses.is_dataclass(value):
        return clean_for_json(dataclasses.asdict(value), max_str_len=max_str_len)
    if isinstance(value, str):
        text = " ".join(value.split())
        return text[:max_str_len]
    if isinstance(value, dict):
        return {str(k): clean_for_json(v, max_str_len=max_str_len) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_for_json(v, max_str_len=max_str_len) for v in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:max_str_len]
```

---

### 6.4 Trace 事件建议

Trace event 通用格式：

```json
{
  "event": "node_end",
  "node": "candidate_node",
  "driver_id": "D001",
  "step_id": 12,
  "current_day": 0,
  "summary": {
    "raw_candidate_count": 104
  }
}
```

必须支持以下事件：

```text
node_start
node_end
node_error
candidate_summary
constraint_summary
advisor_summary
safety_summary
final_action_summary
```

---

### 6.5 写入位置

建议继续写入：

```text
demo/results/logs/agent_decisions.jsonl
```

也可以新增：

```text
demo/results/logs/agent_graph_trace.jsonl
```

推荐做法：

```text
agent_decisions.jsonl = 每步决策摘要，便于现有分析脚本兼容
agent_graph_trace.jsonl = 节点级 trace，便于 Phase 3 调试
```

---

## 7. Graph Nodes 设计

## 7.1 observe_node

### 文件

```text
demo/agent/phase3/graph_nodes/observe_node.py
```

### 职责

负责从仿真 API 和当前输入中读取事实。

写入字段：

```text
driver_status
current_time
current_day
current_location
visible_cargo
decision_history
raw_preferences
```

### 输入

```text
AgentState(driver_id)
SimulationApiPort
```

### 输出

更新后的 `AgentState`。

### 复用模块

```text
api.get_driver_status
api.query_cargo
api.query_decision_history
StateTracker 或当前已有状态解析逻辑
```

### Trace summary

```json
{
  "driver_id": "D001",
  "current_time": 1234,
  "current_day": 0,
  "visible_cargo_count": 52,
  "history_count": 10,
  "current_location": {"lat": 22.5, "lng": 114.0}
}
```

---

## 7.2 preference_node

### 文件

```text
demo/agent/phase3/graph_nodes/preference_node.py
```

### 职责

Phase 3.0 中暂时复用现有 `PreferenceCompiler` / `compile_constraints`。

但要在代码注释中明确：

```text
Phase 3.0 temporary adapter.
Future Phase 3.1 may replace semantic interpretation with PreferenceInterpreterAgent.
```

写入字段：

```text
preference_rules
constraints
```

### 本阶段不要做

不要在本阶段大改为 LLM PreferenceInterpreter。

### Trace summary

```json
{
  "preference_rule_count": 3,
  "constraint_count": 4,
  "constraint_types": ["operate_within_area", "continuous_rest"]
}
```

---

## 7.3 runtime_node

### 文件

```text
demo/agent/phase3/graph_nodes/runtime_node.py
```

### 职责

根据当前状态、历史和约束计算 runtime constraint state。

写入字段：

```text
constraint_runtime_state
```

### 复用模块

```text
compute_constraint_runtime_state
ConstraintRuntimeState
RestRuntimeState
SpecificCargoTracker
OrderedStep tracker
```

### Trace summary

```json
{
  "has_runtime_state": true,
  "rest_current_streak": 120,
  "rest_max_streak_today": 240,
  "runtime_constraint_count": 2
}
```

---

## 7.4 candidate_node

### 文件

```text
demo/agent/phase3/graph_nodes/candidate_node.py
```

### 职责

生成当前可执行候选。

写入字段：

```text
raw_candidates
```

### 复用模块

```text
CandidateFactBuilder.build_candidate_pool
```

### 本阶段边界

1. 继续复用现有候选生成逻辑；
2. 不新增 FutureValueEstimator；
3. 不新增复杂 strategy_intents；
4. 可以保留当前 wait / rest / take_order / reposition 候选；
5. 不让 LLM 直接生成最终 action。

### Trace summary

```json
{
  "raw_candidate_count": 104,
  "candidate_action_counts": {
    "take_order": 100,
    "wait": 2,
    "reposition": 2
  },
  "satisfy_candidate_types": ["continuous_rest"]
}
```

---

## 7.5 constraint_node

### 文件

```text
demo/agent/phase3/graph_nodes/constraint_node.py
```

### 职责

对候选执行结构化约束评估，拆分：

```text
valid_candidates
soft_risk_candidates
hard_invalid_candidates
```

写入字段：

```text
evaluated_candidates
valid_candidates
soft_risk_candidates
hard_invalid_candidates
debug.constraint_summary
```

### 复用模块

```text
ConstraintEvaluator.evaluate
```

### Trace summary

```json
{
  "candidate_count": 104,
  "valid_count": 7,
  "soft_risk_count": 4,
  "hard_invalid_count": 93,
  "hard_invalid_reason_counts": {
    "constraint_operate_within_area": 87,
    "load_time_window_expired": 17
  }
}
```

### 注意

本阶段可以顺便把 trace 做清楚，但不要在 Phase 3.0 中大规模重写约束逻辑。

---

## 7.6 advisor_node

### 文件

```text
demo/agent/phase3/graph_nodes/advisor_node.py
```

### 职责

准备 Advisor 输入，调用当前 `LlmDecisionAdvisor`，并解析结构化输出。

写入字段：

```text
advisor_context
advisor_result
selected_candidate_id
selected_candidate
```

### 复用模块

```text
LlmDecisionAdvisor.advise
```

### 输入候选

Advisor 只能看到：

```text
valid_candidates + soft_risk_candidates
```

不能看到 hard invalid 作为可选项。

### 输出要求

Advisor 必须输出：

```json
{
  "selected_candidate_id": "take_order_123",
  "reason": "..."
}
```

### 强约束

1. 如果 `selected_candidate_id` 不在 candidate pool 中，必须视为 advisor invalid output；
2. 不允许 LLM 自由生成 action；
3. reason 必须清洗换行；
4. 如果 advisor 失败，fallback 只能选择保命候选，例如 wait，不主动赚钱。

### Trace summary

```json
{
  "advisor_candidate_count": 11,
  "selected_candidate_id": "take_order_123",
  "selected_action": "take_order",
  "reason": "Profitable valid order with acceptable risk.",
  "fallback_used": false
}
```

---

## 7.7 safety_node

### 文件

```text
demo/agent/phase3/graph_nodes/safety_node.py
```

### 职责

对 Advisor 选择的 candidate 做最终 hard validation。

写入字段：

```text
safety_result
```

### 复用模块

```text
SafetyGate.validate
```

### 强约束

1. SafetyGate 只负责 hard validation；
2. SafetyGate 不负责重新选择赚钱订单；
3. 如果 selected candidate 不安全，fallback 只能保命；
4. 所有 safety failure 必须写入 trace。

### Trace summary

```json
{
  "selected_candidate_id": "take_order_123",
  "safety_passed": true,
  "safety_reasons": []
}
```

---

## 7.8 emit_node

### 文件

```text
demo/agent/phase3/graph_nodes/emit_node.py
```

### 职责

将通过 SafetyGate 的 selected candidate 转成最终 action。

写入字段：

```text
final_action
```

### 强约束

1. final action 必须来自 selected candidate；
2. 不允许 emit_node 自己发明新 action；
3. 如果没有合法 selected candidate，只能 fallback 到 safe wait；
4. fallback 必须写明 reason。

### Trace summary

```json
{
  "final_action_type": "take_order",
  "selected_candidate_id": "take_order_123",
  "fallback_used": false
}
```

---

## 8. Adapter 设计

为了减少侵入式改动，Phase 3.0 推荐使用 adapters 包装旧模块。

### 8.1 legacy_preference_adapter.py

职责：

```text
raw_preferences / driver_status -> preference_rules / constraints
```

内部调用现有：

```text
PreferenceCompiler
compile_constraints
```

---

### 8.2 legacy_candidate_adapter.py

职责：

```text
AgentState -> raw_candidates
```

内部调用现有：

```text
CandidateFactBuilder
```

---

### 8.3 legacy_constraint_adapter.py

职责：

```text
raw_candidates + constraints + runtime_state -> evaluated candidate groups
```

内部调用现有：

```text
ConstraintEvaluator
```

---

### 8.4 legacy_advisor_adapter.py

职责：

```text
valid + soft_risk candidates -> selected_candidate_id
```

内部调用现有：

```text
LlmDecisionAdvisor
```

---

### 8.5 legacy_safety_adapter.py

职责：

```text
selected_candidate -> safety_result
```

内部调用现有：

```text
SafetyGate
```

---

## 9. 修改 ModelDecisionService

### 9.1 当前问题

当前 `ModelDecisionService.decide()` 承担太多职责：

```text
观察状态
编译偏好
构造 runtime state
生成候选
评估约束
准备 advisor
调用 advisor
安全校验
写日志
fallback
返回 action
```

Phase 3.0 后，这些职责应转移到 graph nodes。

---

### 9.2 新职责

`ModelDecisionService.decide()` 只负责：

```text
1. 创建 AgentState；
2. 调用 GraphRunner；
3. 返回 final_state.final_action。
```

示例结构：

```python
def decide(self, driver_id: str, *args, **kwargs):
    state = AgentState(driver_id=driver_id)
    final_state = self.graph_runner.run(state)
    return final_state.final_action
```

如果现有 decide 接口需要传入更多对象，则把它们放入 `AgentState` 或 `GraphRunner` 初始化依赖中。

---

## 10. Fallback 策略

Phase 3.0 必须明确 fallback 边界。

### 10.1 fallback 可以做

```text
1. Advisor 输出无效 candidate_id 时，选择 safe wait；
2. SafetyGate 拒绝 selected candidate 时，选择 safe wait；
3. 没有 valid/soft_risk candidates 时，选择 safe wait；
4. 系统异常时，返回最安全 wait action。
```

### 10.2 fallback 不可以做

```text
1. 不可以主动选择赚钱订单；
2. 不可以绕过 Advisor 做策略选择；
3. 不可以绕过 SafetyGate；
4. 不可以恢复旧 MissionExecutor 逻辑。
```

Fallback reason 必须写入 trace。

---

## 11. Trace 与日志验收

Phase 3.0 完成后，每一步至少应该能回答以下问题：

```text
1. 当前 driver 是谁？
2. 当前时间和位置是什么？
3. 看到了多少货源？
4. 生成了多少候选？
5. valid / soft_risk / hard_invalid 各有多少？
6. hard invalid 的主要原因是什么？
7. Advisor 看到了多少候选？
8. Advisor 选了哪个 candidate_id？
9. SafetyGate 是否通过？
10. 最终 action 是什么？
11. 是否用了 fallback？为什么？
12. 哪个 node 出现了异常？
```

---

## 12. 最小可接受 Trace 字段

每个 step 的 decision summary 至少包含：

```text
driver_id
step_id
current_time
current_day
current_location
visible_cargo_count
candidate_count
valid_count
soft_risk_count
hard_invalid_count
hard_invalid_reason_counts
advisor_candidate_count
selected_candidate_id
selected_action
selected_reason
safety_passed
fallback_used
fallback_reason
final_action
```

如果做节点级 trace，则每个 node 至少包含：

```text
event
node
driver_id
step_id
summary
error
```

---

## 13. 迁移步骤建议

### Step 1：新建 phase3 目录

新增：

```text
agent_state.py
graph_runner.py
trace_logger.py
utils/json_cleaner.py
graph_nodes/*.py
adapters/*.py
```

先不要改旧主流程。

---

### Step 2：实现 AgentState 和 TraceLogger

优先保证：

```text
AgentState 可创建
TraceLogger 可写合法 JSONL
clean_for_json 可处理 dataclass / dict / list / string
```

---

### Step 3：实现 GraphRunner

先用 dummy nodes 测试：

```text
node_start / node_end / node_error 能写 trace
state 能在 nodes 之间传递
```

---

### Step 4：逐个封装旧模块为 nodes

按顺序实现：

```text
observe_node
preference_node
runtime_node
candidate_node
constraint_node
advisor_node
safety_node
emit_node
```

每实现一个 node，都跑一次最小测试。

---

### Step 5：让 ModelDecisionService 使用 GraphRunner

把旧 `decide()` 主流程切换到：

```text
create AgentState
run GraphRunner
return final_action
```

旧代码可以暂时保留为 `_decide_legacy()`，便于回退。

---

### Step 6：对比运行结果

运行：

```bash
cd demo/server
python main.py

cd ../
python calc_monthly_income.py
```

检查：

```text
是否能完整跑完
是否有 validation_error
是否生成 logs
JSONL 是否合法
收益是否没有异常归零
```

---

### Step 7：清理明显不用的旧主控模块

本阶段可以只加 LEGACY 注释，不建议大规模删除。

可标记：

```text
MissionExecutor
MissionReplanner
LlmMissionPlanner
CandidateSafetyFilter
旧复杂 fallback 赚钱逻辑
```

---

## 14. 测试建议

### 14.1 JSONL 合法性测试

写一个简单脚本：

```python
import json
from pathlib import Path

path = Path("demo/results/logs/agent_graph_trace.jsonl")
for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
    try:
        json.loads(line)
    except Exception as exc:
        raise RuntimeError(f"Invalid JSONL at line {i}: {exc}")
print("JSONL OK")
```

---

### 14.2 final action 来源测试

每步检查：

```text
如果 fallback_used=false：
  final_action 必须来自 selected_candidate_id

如果 fallback_used=true：
  fallback_reason 必须非空
```

---

### 14.3 SafetyGate 测试

每步检查：

```text
如果 selected_candidate 存在：
  必须经过 safety_node
  safety_result 必须写入 trace
```

---

### 14.4 功能回归测试

至少跑：

```text
完整 31 天仿真
monthly income 计算
validation error 检查
日志检查
```

Phase 3.0 不要求收益提升，但不应出现明显灾难性退化。

---

## 15. Phase 3.0 验收标准

Phase 3.0 完成后，必须满足：

```text
1. demo/server/main.py 可以运行完成；
2. demo/calc_monthly_income.py 可以运行完成；
3. ModelDecisionService.decide() 已经变薄；
4. 主流程由 GraphRunner 执行；
5. 每个 node 输入 AgentState，输出 AgentState；
6. AgentState 字段能覆盖当前决策链；
7. TraceLogger 能记录 node_start / node_end / node_error；
8. agent_graph_trace.jsonl 是合法 JSONL；
9. agent_decisions.jsonl 不被 reason 换行污染；
10. final_action 必须来自 selected_candidate_id 或 safe fallback；
11. SafetyGate 仍然最终 hard validation；
12. fallback 不负责赚钱；
13. 没有引入 StrategicPlannerAgent / MemoryStore / ReflectionAgent / OpportunityAnalyst；
14. 后续可以自然插入 Phase 3.1 day_plan node。
```

---

## 16. Phase 3.0 完成后的理想主流程

```text
ModelDecisionService.decide()
    |
    v
AgentState(driver_id)
    |
    v
GraphRunner
    |
    +--> observe_node
    +--> preference_node
    +--> runtime_node
    +--> candidate_node
    +--> constraint_node
    +--> advisor_node
    +--> safety_node
    +--> emit_node
    |
    v
final_state.final_action
    |
    v
return action
```

此时项目已经具备主流 Agent 框架的基本形态：

```text
typed state
node-based workflow
trace observability
guardrail boundary
candidate-id-based action control
future extensibility
```

---

## 17. 后续 Phase 预留插入点

Phase 3.0 要为后续留好插入点，但不要实现。

### Phase 3.1 插入点

新增：

```text
strategic_planner_node
```

位置：

```text
preference_node
-> strategic_planner_node
-> runtime_node
```

输出：

```text
day_plan
strategy_context
```

---

### Phase 3.2 插入点

新增：

```text
memory_retrieval_node
reflection_node
memory_update_node
```

可能位置：

```text
observe_node -> memory_retrieval_node -> strategic_planner_node
emit_node -> reflection_node -> memory_update_node
```

---

### Phase 3.3 插入点

新增：

```text
opportunity_analysis_node
future_value_node
```

位置：

```text
constraint_node
-> opportunity_analysis_node
-> future_value_node
-> advisor_node
```

---

## 18. 给代码 Agent 的完整任务提示词

下面这段可以直接复制给代码 Agent 执行。

```text
我们进入 TruckDrivers Phase 3.0。目标不是继续修局部 bug，也不是马上加入多个 Agent，而是把当前主流程重构成 Agentic Graph Skeleton：typed AgentState + graph nodes + trace logger。请不要从零重写，不要删除现有可用模块，而是把旧能力包装成 graph nodes。

核心目标：
1. 新建 demo/agent/phase3/ 目录；
2. 定义 AgentState；
3. 定义 GraphRunner；
4. 定义 TraceLogger；
5. 将 ModelDecisionService.decide() 中的主流程拆成 graph nodes；
6. 复用当前已有模块；
7. final_action 必须来自 selected_candidate_id 或 safe fallback；
8. SafetyGate 仍是最终 hard validation；
9. fallback 只能保命，不能负责赚钱；
10. JSONL trace 必须一行一个合法 JSON。

请新增以下文件：

demo/agent/phase3/
  __init__.py
  agent_state.py
  graph_runner.py
  trace_logger.py
  schemas.py
  utils/
    __init__.py
    json_cleaner.py
    summaries.py
  adapters/
    __init__.py
    legacy_preference_adapter.py
    legacy_candidate_adapter.py
    legacy_constraint_adapter.py
    legacy_advisor_adapter.py
    legacy_safety_adapter.py
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

Phase 3.0 复用以下旧模块：
- PreferenceCompiler / compile_constraints
- StateTracker
- compute_constraint_runtime_state / ConstraintRuntimeState
- CandidateFactBuilder
- ConstraintEvaluator
- LlmDecisionAdvisor
- SafetyGate
- SimulationApiPort

重要边界：
1. 不要引入 StrategicPlannerAgent；
2. 不要引入 DayPlan；
3. 不要引入 MemoryStore；
4. 不要引入 ReflectionAgent；
5. 不要引入 OpportunityAnalyst；
6. 不要引入 FutureValueEstimator；
7. 不要恢复 MissionExecutor / MissionReplanner / CandidateSafetyFilter 等旧主控模块；
8. 不要让 LLM 自由编造 action；
9. Advisor 只能选择 candidate_id；
10. SafetyGate 只做最终 hard validation，不负责策略选择。

Graph nodes 顺序：
observe_node
-> preference_node
-> runtime_node
-> candidate_node
-> constraint_node
-> advisor_node
-> safety_node
-> emit_node

每个 node 必须满足：
- 输入 AgentState；
- 输出 AgentState；
- 只负责自己的字段；
- 写入必要 debug summary；
- 出错时让 TraceLogger 记录 node_error。

AgentState 至少包含：
- driver_id
- step_id
- driver_status
- current_time
- current_day
- current_location
- visible_cargo
- decision_history
- raw_preferences
- preference_rules
- constraints
- constraint_runtime_state
- raw_candidates
- evaluated_candidates
- valid_candidates
- soft_risk_candidates
- hard_invalid_candidates
- advisor_context
- advisor_result
- selected_candidate_id
- selected_candidate
- safety_result
- final_action
- fallback_used
- fallback_reason
- trace
- errors
- debug

TraceLogger 必须支持：
- node_start
- node_end
- node_error
- candidate_summary
- constraint_summary
- advisor_summary
- safety_summary
- final_action_summary

JSONL 清洗要求：
- 所有字符串去除换行和多余空白；
- 所有 dataclass / dict / list 可序列化；
- 每行一个 JSON object；
- reason 截断到合理长度；
- 不写入巨大 prompt 全文。

修改 ModelDecisionService.decide()：
- 只负责初始化 AgentState；
- 调用 GraphRunner；
- 返回 final_state.final_action；
- 可保留 _decide_legacy() 作为临时回退，但默认使用 Phase 3 graph。

验收标准：
1. cd demo/server && python main.py 能跑；
2. cd demo && python calc_monthly_income.py 能跑；
3. agent_graph_trace.jsonl 合法；
4. agent_decisions.jsonl 合法，不被 reason 换行污染；
5. 每一步都有 node trace；
6. final_action 来自 selected_candidate_id 或 safe fallback；
7. SafetyGate 被调用；
8. 当前功能不出现灾难性退化；
9. 后续可以自然插入 StrategicPlannerAgent/day_plan、MemoryStore/ReflectionAgent、OpportunityAnalyst/FutureValueEstimator。
```

---

## 19. 总结

Phase 3.0 的核心不是算法收益提升，而是架构地基升级。

现在要从：

```text
ModelDecisionService.decide() 大函数
```

升级为：

```text
AgentState 驱动的 graph workflow
```

从：

```text
LLM-assisted greedy optimizer
```

逐步迈向：

```text
stateful agentic decision system
```

Phase 3.0 做完后，项目应该具备：

```text
清晰 node
类型化 state
完整 trace
可插拔扩展点
SafetyGate 边界
candidate_id action control
```

这才是后续做 StrategicPlanner、Memory、Reflection、FutureValue 的基础。
