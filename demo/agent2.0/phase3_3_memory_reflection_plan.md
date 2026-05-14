# Phase 3.3 规划：MemoryStore + ReflectionAgent Skeleton

## 0. 本文档定位

本文档用于指导 TruckDrivers 项目从 Phase 3.2.5 进入 Phase 3.3。

当前项目已经完成：

```text
Phase 3.0     Agentic Graph Skeleton
Phase 3.0.5   Tool Layer + Diagnostic Trace + Legacy Boundary
Phase 3.1     StrategicPlannerAgent + DayPlan
Phase 3.1.5   DayPlan Quality Hardening
Phase 3.2     Goal-based Candidate Layer Refactor
Phase 3.2.5   Goal Layer Boundary Stabilization 与架构收口
```

Phase 3.3 的核心目标不是继续修某个司机的局部收益问题，而是新增一个**观察型、反思型、轻量记忆型**模块，让系统能记录失败模式、总结经验，并把这些经验作为下一轮 DayPlan / Advisor 的软提示。

一句话概括：

```text
Phase 3.3 不是让 Memory 直接开车；
Phase 3.3 是让系统开始“记住自己为什么失败”，但仍然保持 Candidate -> Advisor -> SafetyGate 的决策边界。
```

---

## 1. 是否可以进入 Phase 3.3

### 1.1 当前 Phase 3.2.5 的短测结论

由于完整实验耗时较长，目前只跑了 6 个司机。这个测试不能证明全局收益一定变好，也无法验证 D009 / D010 等关键复杂目标是否全部修复。

但是，从已跑的 6 个司机日志看，Phase 3.2.5 的主要目标已经部分达成：

```text
goal_satisfy selected rate 明显下降；
continuous_rest 不再明显牺牲高收益订单；
urgency / must_do_now 机制开始生效；
DayPlan guidance / risk_focus 仍保持稳定；
SafetyGate / fallback 没有大规模异常。
```

这说明 Phase 3.2.5 作为“Goal Layer 收口”是有效的。

### 1.2 为什么可以进入 Phase 3.3

可以进入 Phase 3.3 的原因：

```text
1. Phase 3.2.5 已经把 Goal Layer 过度接管的问题压下来了；
2. 继续在 3.2.x 里修局部现象，容易重新变成旧项目的增量补丁；
3. D009 / D010 / D004 / D005 的后续问题已经不只是候选生成问题，而是需要跨日经验、失败模式总结和策略提醒；
4. Phase 3.3 的 Memory / Reflection 正好可以处理“上一轮为什么失败、下一轮应该注意什么”。
```

因此，当前建议是：

```text
不继续开 Phase 3.2.6；
不回退 Phase 3.2；
直接进入 Phase 3.3；
但在 Phase 3.3 文档中保留 Phase 3.2.5 遗留注意事项。
```

---

## 2. Phase 3.2.5 后的小尾巴如何处理

### 2.1 不作为 Phase 3.2.6 继续修

当前还有几个小尾巴：

```text
D004 / D005 在有 profitable order 时仍选择 system wait；
forbid_action_in_time_window / daily limit / DayPlan guidance 可能偏保守；
D009 specific_cargo 不可见时仍缺少机会策略；
D010 ordered_steps 是否在完整实验中稳定，仍需完整日志验证；
完整 10 司机实验尚未跑完。
```

这些问题不建议继续作为 Phase 3.2.6 一项项修。

原因：

```text
这些问题已经不完全是 Goal Layer 的候选生成问题；
继续修会导致 3.2 无限膨胀；
容易又开始围绕 D004、D005、D009、D010 写隐性特化；
会拖慢进入 Memory / Reflection 的主线。
```

### 2.2 作为 Phase 3.3 的前置注意事项

这些问题应作为 Phase 3.3 的输入：

```text
MemoryStore 要记录：哪些司机在有高收益订单时仍 wait；
ReflectionAgent 要总结：为什么 system wait 过多；
DayPlan hints 要提醒：不要把低罚分目标压过高收益订单；
Advisor hints 要提醒：goal_satisfy 低 urgency 时可以让位给高净收益订单；
后续完整实验再验证 D009 / D010。
```

换句话说：

```text
Phase 3.2.5 后的小尾巴不继续在 Candidate Layer 里硬修；
而是转化为 Memory / Reflection 的观测对象。
```

---

## 3. Phase 3.3 的核心目标

Phase 3.3 的目标是新增：

```text
MemoryStore
ReflectionAgent
FailurePatternExtractor
Reflection hints injection
Reflection diagnostics
```

但第一版必须保持克制。

### 3.1 Phase 3.3 要解决什么

Phase 3.3 解决的是：

```text
系统每次失败后没有留下可复用经验；
DayPlan 每天都像第一次规划；
Advisor 不知道上一轮为什么错；
Goal Layer 的失败只停留在日志里，没有变成策略提醒；
高罚分任务失败、过度 wait、错过高收益订单等问题无法跨天复盘。
```

### 3.2 Phase 3.3 不解决什么

Phase 3.3 不解决：

```text
不做货源预测；
不做 FutureValue；
不做 OpportunityAnalyst；
不做 beam search；
不做全局路径优化；
不写 D009 / D010 特判；
不让 Memory 直接决定 action；
不让 Reflection 直接生成 candidate_id；
不绕过 SafetyGate。
```

这些留给后续 Phase 3.4 或更后面阶段。

---

## 4. Phase 3.3 的设计原则

## 4.1 Reflection 只能建议，不能决策

ReflectionAgent 只能输出：

```text
risk hints
failure summaries
next-day strategy notes
advisor warnings
```

不能输出：

```text
final_action
candidate_id
cargo_id
order_id
强制 wait
强制 take_order
强制 reposition
```

### 正确示例

```text
D004 最近多次在存在高收益合法订单时选择 wait，下一轮 Advisor 应重点比较 wait 的机会成本。
```

### 错误示例

```text
D004 下一步必须接 cargo_12345。
```

---

## 4.2 Memory 只能存经验，不存硬规则

MemoryStore 记录的是历史事实和反思结果，不是新的规则引擎。

允许存：

```text
driver_id
day_index
goal_type
failure_type
failure_summary
evidence
severity
suggested_hint
confidence
```

禁止存：

```text
if driver_id == D009 then ...
if cargo_id == 240646 then ...
某司机必须永远优先某动作
```

---

## 4.3 Memory / Reflection 不得破坏现有边界

Phase 3.3 之后主流程仍应是：

```text
Observe
-> Preference
-> Runtime
-> Candidate
-> Constraint
-> Planning
-> Reflection / Memory Hint
-> Advisor
-> Safety
-> Emit
```

或者：

```text
Reflection hints 注入 PlanningNode / AdvisorTool context
```

但是最终仍然必须满足：

```text
CandidateTool 生成候选；
Advisor 选择 candidate_id；
SafetyGate 做 hard validation；
Emit 返回 action。
```

---

## 4.4 Reflection 先做离线/准离线，不做在线强控

Phase 3.3 第一版建议采用：

```text
daily reflection
driver-level reflection
goal-level reflection
```

不要每一步都让 ReflectionAgent 参与实时决策。

推荐：

```text
每个 day 结束后；
或每个 driver 的一日任务结束后；
或每 N 步生成一次 summary。
```

这样可以降低 token 和运行时间成本，也避免 Reflection 过度干预。

---

## 5. Phase 3.3 模块设计

建议新增目录：

```text
demo/agent/phase3/memory/
  memory_schema.py
  memory_store.py
  failure_pattern_extractor.py
  reflection_agent.py
  reflection_tool.py
  reflection_diagnostics.py
```

---

## 5.1 memory_schema.py

### 职责

定义 Memory / Reflection 相关数据结构。

建议数据结构：

```python
@dataclass
class FailurePattern:
    pattern_id: str
    driver_id: str
    day_index: Optional[int]
    goal_id: Optional[str]
    goal_type: Optional[str]
    failure_type: str
    severity: str
    evidence: Dict[str, Any]
    summary: str
    suggested_hint: str
    confidence: float
```

```python
@dataclass
class ReflectionHint:
    hint_id: str
    driver_id: str
    scope: str  # driver / goal / day / global
    priority: str  # low / medium / high
    message: str
    applies_to_goal_type: Optional[str]
    expires_after_day: Optional[int]
    evidence_refs: List[str]
```

```python
@dataclass
class DriverMemory:
    driver_id: str
    recent_failures: List[FailurePattern]
    active_hints: List[ReflectionHint]
    last_updated_day: Optional[int]
```

### 注意

这些结构只表示记忆和提示，不表示动作。

---

## 5.2 memory_store.py

### 职责

提供简单的内存存储或 JSONL 存储。

第一版可以只用本地文件：

```text
demo/results/logs/memory_store.jsonl
demo/results/logs/reflection_hints.jsonl
```

### 必须支持

```python
add_failure(pattern)
add_hint(hint)
get_driver_memory(driver_id)
get_active_hints(driver_id, day_index)
expire_old_hints(day_index)
save()
load()
```

### 不要做

```text
复杂向量数据库；
embedding 检索；
长期复杂检索；
跨项目记忆。
```

Phase 3.3 第一版只做轻量可追踪存储。

---

## 5.3 failure_pattern_extractor.py

### 职责

从现有 trace / validation 中提取失败模式。

第一版可以只处理几类明确模式：

### Pattern A：profitable_order_but_wait

检测：

```text
valid_profitable_order_count > 0
selected_action = wait
best_valid_order_net > threshold
```

生成 hint：

```text
该司机多次在有高收益合法订单时选择 wait。后续 Advisor 应显式比较 wait 的机会成本。
```

### Pattern B：rest_over_profit

检测：

```text
selected goal_type = continuous_rest
best_valid_order_net > rest_penalty_at_risk * ratio
must_do_now = false
```

生成 hint：

```text
该司机存在非紧急休息压过高收益订单的问题。后续只有 must_do_now 为 true 时才强优先 rest。
```

### Pattern C：goal_overuse

检测：

```text
goal_satisfy_selected_rate too high
selected_goal_by_type 某类异常高
```

生成 hint：

```text
该司机被某类 goal 过度主导。后续低 urgency goal 应让位给高净收益订单。
```

### Pattern D：ordered_step_regression

检测：

```text
ordered_steps_regression_count > 0
```

生成 hint：

```text
多步目标发生进度回退。后续需要保持 completed_step 单调性。
```

### Pattern E：reached_but_left_window

检测：

```text
reached_but_left_window_count > 0
minutes_not_home_in_window > threshold
```

生成 hint：

```text
该司机到达过目标位置但没有保持到窗口结束。后续到达后应优先 hold/stay_until。
```

### Pattern F：specific_cargo_unavailable

检测：

```text
specific_cargo_not_visible_count > 0
selected_specific_cargo_count = 0
```

生成 hint：

```text
目标货长期不可见。当前不可执行时不要被低价值 goal 消耗黄金接单时间。
```

---

## 5.4 reflection_agent.py

### 职责

把 FailurePattern 转成更自然、更高层的策略总结。

### 输入

```text
driver_id
recent failure patterns
DayPlan
goal diagnostics
selected action stats
income / penalty summary
```

### 输出

```text
ReflectionHint[]
```

### 输出要求

必须是结构化 JSON。

建议 schema：

```json
{
  "driver_id": "D004",
  "summary": "该司机多次在存在高收益合法订单时选择 wait，主要受日计划或时间窗口解释影响。",
  "hints": [
    {
      "priority": "high",
      "scope": "advisor",
      "message": "当存在高净收益合法订单时，除非当前约束为 hard invalid 或 goal urgency 为 critical，否则不要默认 wait。",
      "applies_to_goal_type": null,
      "expires_after_day": 3
    }
  ],
  "confidence": 0.82
}
```

### 禁止

ReflectionAgent 禁止输出：

```text
candidate_id
order_id
cargo_id
final_action
driver-specific hard rule
```

如果 LLM 输出了这些字段，必须过滤。

---

## 5.5 reflection_tool.py

### 职责

作为 Phase 3 tool layer 的入口，封装 MemoryStore / FailurePatternExtractor / ReflectionAgent。

建议接口：

```python
class ReflectionTool:
    def build_reflection_context(state) -> dict:
        ...

    def extract_failures_from_trace(trace_path) -> list[FailurePattern]:
        ...

    def generate_hints(driver_id, failures) -> list[ReflectionHint]:
        ...

    def get_active_hints(driver_id, day_index) -> list[ReflectionHint]:
        ...
```

### 使用方式

Phase 3.3 第一版建议：

```text
在 PlanningNode 或 AdvisorTool 前读取 active hints；
把 hints 作为 context 注入 DayPlan / Advisor；
不新增一个强控制 node。
```

---

## 5.6 reflection_diagnostics.py

### 职责

输出 Reflection / Memory 的诊断指标。

建议统计：

```text
failure_patterns_detected_count
hints_generated_count
active_hints_count
hints_by_driver
hints_by_failure_type
reflection_filtered_illegal_fields_count
advisor_used_reflection_hint_count
reflection_hint_empty_count
```

---

## 6. Phase 3.3 的图流程建议

### 6.1 最小侵入方案

建议不要大改 GraphRunner，只在 Planning / Advisor 上下文中增加 reflection hints。

当前流程：

```text
observe
-> preference
-> runtime
-> candidate
-> constraint
-> planning
-> advisor
-> safety
-> emit
```

Phase 3.3 最小方案：

```text
observe
-> preference
-> runtime
-> candidate
-> constraint
-> planning
-> reflection_context
-> advisor
-> safety
-> emit
```

或者：

```text
reflection_context 不作为独立 node，
而是在 PlanningNode / AdvisorTool 中读取 MemoryStore。
```

更推荐第二种，减少节点膨胀。

### 6.2 不建议一开始新增复杂 graph node

不要一开始加：

```text
MemoryNode
ReflectionNode
CriticNode
DebateNode
RepairNode
```

因为这样会让图过快复杂化。

Phase 3.3 第一版只要：

```text
MemoryStore + FailurePatternExtractor + ReflectionAgent + ReflectionTool
```

---

## 7. Reflection hints 如何注入 Advisor

Advisor prompt 中可以新增一节：

```text
Reflection Hints:
- These hints summarize recent failures.
- They are advisory only.
- Do not follow them if they conflict with hard constraints or candidate facts.
- Do not create actions outside the candidate list.
```

每条 hint 格式：

```text
[priority=high][scope=advisor][type=profitable_order_but_wait]
D004 recently waited despite profitable valid orders. When best_valid_order_net is high and goal urgency is low, prefer profitable take_order over wait.
```

Advisor 必须理解：

```text
Reflection hint 是经验提醒；
Goal urgency 是当前目标紧急度；
Candidate facts 是当前事实；
SafetyGate 是最终硬约束。
```

优先级关系：

```text
Hard constraint > SafetyGate > Candidate availability > Current facts > Goal urgency > Reflection hint > DayPlan style preference
```

---

## 8. Reflection hints 如何注入 DayPlan

DayPlan 可以接收 driver-level hints，例如：

```text
该司机昨天多次因为低 urgency rest 错过高收益订单，今天规划时应避免过早休息。
```

但 DayPlan 不能因此输出具体 candidate_id。

DayPlan 只能调整：

```text
risk_focus
advisor_guidance
strategy_summary
```

---

## 9. Phase 3.3 必须避免的问题

### 9.1 避免 Memory 变成规则系统

错误方向：

```python
if memory.has_failure("D004_wait_too_much"):
    force_take_order()
```

正确方向：

```text
把 D004 wait 过多作为 Advisor hint，让 Advisor 在候选中权衡。
```

---

### 9.2 避免 Reflection 和 DayPlan 打架

DayPlan 是日级策略，Reflection 是历史经验。

如果二者冲突：

```text
DayPlan 说今天要注意休息；
Reflection 说昨天过早休息错过高收益订单；
```

Advisor 应看到两者，并根据当前候选事实判断。

不能让任意一方直接覆盖另一方。

---

### 9.3 避免 Reflection 直接修 D009 / D010

Reflection 可以说：

```text
D010 类多步目标过去出现到达后离开的问题，后续应关注 hold/stay_until。
```

不能说：

```text
D010 必须一直待在家。
```

不能写 driver hard rule。

---

### 9.4 避免引入太多文件

Phase 3.3 文件数量要控制。

建议新增不超过：

```text
memory_schema.py
memory_store.py
failure_pattern_extractor.py
reflection_agent.py
reflection_tool.py
reflection_diagnostics.py
```

不要继续新增大量细碎文件。

---

## 10. Phase 3.3 验收标准

### 10.1 架构验收

必须满足：

```text
Reflection 不输出 final_action；
Reflection 不输出 candidate_id；
Reflection 不绕过 CandidateTool；
Advisor 仍只选 candidate_id；
SafetyGate 仍最终硬校验；
Memory 只存历史和 hints；
旧模块不重新接管策略。
```

### 10.2 日志验收

新增日志字段：

```text
active_reflection_hint_count
reflection_hints_used
reflection_hint_priorities
reflection_failure_types
reflection_filtered_illegal_fields
advisor_reason_mentions_reflection
```

### 10.3 行为验收

短测中希望看到：

```text
D004 / D005 profitable_order_but_wait 被识别为 failure pattern；
下一轮 DayPlan / Advisor context 中出现对应 hint；
Advisor reason 中能看到对 reflection hint 的引用；
但 final action 仍来自合法 candidate_id。
```

### 10.4 不以收益作为第一验收

Phase 3.3.0 第一版不要求总收益立刻提高。

第一验收目标是：

```text
Memory / Reflection 链路跑通；
失败模式能被提取；
hints 能注入；
边界没有被破坏；
日志可解释。
```

收益提升应放到 Phase 3.3.1 / 3.3.2 再看。

---

## 11. Phase 3.3 推荐实施顺序

### Step 1：建立 Memory 数据结构

新增：

```text
memory_schema.py
memory_store.py
```

实现：

```text
FailurePattern
ReflectionHint
DriverMemory
JSONL save/load
```

### Step 2：实现 FailurePatternExtractor

先做规则化 pattern，不用 LLM：

```text
profitable_order_but_wait
rest_over_profit
goal_overuse
ordered_step_regression
reached_but_left_window
specific_cargo_unavailable
```

### Step 3：实现 ReflectionAgent

用 LLM 或 deterministic summary 把 patterns 变成 hints。

如果担心 token，可以第一版先不用 LLM，直接模板生成 hints。

### Step 4：实现 ReflectionTool

作为 tool layer 入口。

### Step 5：注入 Advisor context

先注入 Advisor，不急着注入 DayPlan。

原因：

```text
Advisor 是当前动作选择者；
Reflection hint 对它最直接；
DayPlan 注入可以放到 3.3.1。
```

### Step 6：增强 validation

输出 reflection diagnostics。

### Step 7：短测 6 个司机

先复用当前 6 个司机，观察：

```text
D004 / D005 的 profitable_order_but_wait 是否被识别；
下一轮是否减少类似 wait；
Advisor reason 是否引用 hint。
```

### Step 8：再跑完整司机

完整实验耗时长，可以放在 3.3.1 前后。

---

## 12. Phase 3.3.0 与后续阶段划分

### Phase 3.3.0

```text
MemoryStore + FailurePatternExtractor + ReflectionHint 注入 Advisor
```

目标：

```text
链路跑通；
边界稳定；
日志可解释。
```

### Phase 3.3.1

```text
Reflection hints 注入 DayPlan；
driver-level memory 稳定化；
hint expiration / confidence 改进。
```

### Phase 3.3.2

```text
根据实验调优 hint 使用方式；
减少 profitable_order_but_wait；
减少低 urgency goal 过度选择。
```

### Phase 3.4

```text
OpportunityAnalyst + FutureValueEstimator
```

处理：

```text
specific_cargo 不可见时是否等待；
是否提前 reposition；
当前订单是否会破坏未来高价值目标；
长期机会成本。
```

---

## 13. 给代码 Agent 的执行提示词

```text
现在进入 Phase 3.3：MemoryStore + ReflectionAgent Skeleton。

背景：
Phase 3.2.5 已经完成 Goal Layer 收口，6 个司机短测显示 goal_satisfy 过度接管问题有所缓解，但仍存在 system wait 过多、D004/D005 在有高收益订单时 wait、D009/D010 尚未完整验证等小尾巴。不要继续开 Phase 3.2.6 修局部 bug，而是把这些现象作为 Phase 3.3 Memory / Reflection 的输入。

目标：
建立一个观察型、建议型的 Memory / Reflection 层，让系统能记录失败模式，并把失败经验作为 Advisor 的软提示。第一版不直接控制 action。

请严格执行：

1. 新增目录：
   demo/agent/phase3/memory/

2. 新增文件：
   - memory_schema.py
   - memory_store.py
   - failure_pattern_extractor.py
   - reflection_agent.py
   - reflection_tool.py
   - reflection_diagnostics.py

3. 实现数据结构：
   - FailurePattern
   - ReflectionHint
   - DriverMemory

4. 实现 MemoryStore：
   - add_failure
   - add_hint
   - get_driver_memory
   - get_active_hints
   - expire_old_hints
   - save/load JSONL

5. 实现 FailurePatternExtractor：
   至少识别：
   - profitable_order_but_wait
   - rest_over_profit
   - goal_overuse
   - ordered_step_regression
   - reached_but_left_window
   - specific_cargo_unavailable

6. 实现 ReflectionAgent：
   - 输入 failure patterns
   - 输出 structured ReflectionHint
   - 可以第一版用 deterministic template，不强制 LLM
   - 禁止输出 candidate_id / cargo_id / order_id / final_action

7. 实现 ReflectionTool：
   - 提供 get_active_hints(driver_id, day_index)
   - 提供 extract_failures_from_trace(trace_path)
   - 提供 generate_hints(driver_id, failures)

8. 将 Reflection hints 注入 Advisor context：
   - hints 只作为 advisory context
   - Advisor 仍只能选择已有 candidate_id
   - SafetyGate 仍最终 hard validation

9. 增强日志和 validation：
   - active_reflection_hint_count
   - reflection_hints_used
   - reflection_failure_types
   - reflection_filtered_illegal_fields
   - advisor_reason_mentions_reflection

禁止：
- 不写 D009 / D010 / D004 / D005 特判
- 不写 cargo_id 特判
- Reflection 不得直接生成 action
- Memory 不得成为规则系统
- 不新增 FutureValue / Opportunity
- 不做 beam search
- 不绕过 CandidateTool / Advisor / SafetyGate
- 不继续新增大量无边界模块

验收：
- compileall 通过
- MemoryStore save/load smoke 通过
- FailurePatternExtractor 能从现有 agent_decisions.jsonl 识别 profitable_order_but_wait
- ReflectionHint 能注入 Advisor context
- Advisor reason 中能看到 reflection hint 被考虑
- final action 仍来自 candidate_id
```

---

## 14. 最终总结

可以进入 Phase 3.3。

但要注意：

```text
Phase 3.3 不是继续加一个能直接决策的大脑；
Phase 3.3 是加一个“记忆与复盘层”。
```

Phase 3.2.5 的小尾巴不要继续在 Candidate Layer 里硬修，而是变成 Memory / Reflection 的观察对象：

```text
D004 / D005 有高收益订单仍 wait；
D009 specific_cargo 不可见；
D010 ordered_steps 需要完整验证；
低 urgency goal 与高收益订单冲突；
system wait 过多。
```

Phase 3.3 的第一版必须保持克制：

```text
只记录；
只总结；
只提示；
不强控；
不绕边界。
```

如果 Phase 3.3 能做到这一点，项目就不会重新回到“模块越来越多、互相抢方向盘”的混乱状态，而是会形成更清晰的 agentic 架构：

```text
DayPlan 负责当日策略；
Goal Layer 负责目标候选；
Advisor 负责当前选择；
SafetyGate 负责硬安全；
Memory / Reflection 负责历史经验和失败提醒。
```
