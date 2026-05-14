# TruckDrivers Phase 3.2 指导方案：Goal-based Candidate Layer 重构

## 0. 阶段定位

Phase 3.0 完成了 Agentic Graph Skeleton：

```text
AgentState
GraphRunner
graph_nodes
TraceLogger
```

Phase 3.0.5 完成了工具层和可观测性收口：

```text
graph_node -> tool -> adapter -> old_module
DiagnosticTool
Validation Report
Legacy boundary
```

Phase 3.1 / 3.1.5 完成了日级策略规划：

```text
StrategicPlannerAgent
DayPlan
DayPlanStore
PlanningNode
Advisor 接收 DayPlan guidance
DayPlan Quality Hardening
```

当前系统已经具备：

```text
Planner 能识别今天应该重视的高罚金任务；
Advisor 能在候选池中选择 candidate_id；
SafetyGate 能做最终硬校验；
Trace 能观察 DayPlan 和 decision diagnosis。
```

但是最新实验说明一个更核心的问题：

```text
Planner 已经会“想做重要任务”，
但 Candidate Layer 不能稳定把这些任务变成正确、可推进、可执行的 candidate_id。
```

因此 Phase 3.2 的核心目标不是继续调 prompt，也不是针对 D009/D010 写补丁，而是：

```text
重构 Candidate Layer：
从旧 planner.py 的规则式候选生成，
升级为 Goal-based Candidate Materialization。
```

一句话：

```text
Phase 3.2 = Goal-based Candidate Layer Refactor
```

---

## 1. 为什么 Phase 3.2 要先做 Candidate Layer，而不是 Memory/Reflection

原本 Phase 3.2 可以规划为 MemoryStore + ReflectionAgent，但当前实验暴露出更底层的问题：

```text
如果 Candidate Layer 不能正确承接 Planner 意图，
Memory/Reflection 只能复盘“失败了”，但无法让系统真的执行任务。
```

例如：

```text
Planner 知道 D010 要完成家事任务；
Advisor 愿意选家事相关 candidate；
但候选层一直给 step 0，不推进到停留/回家/静止。

Planner 知道 D009 有熟货任务；
Advisor 被提醒要重视熟货；
但候选层没有稳定物化 specific cargo 的可执行候选或不可执行诊断。
```

这说明：

```text
不是 Planner 不知道；
不是 Advisor 完全不听；
而是 Candidate Layer 无法把“任务意图”可靠落地。
```

所以如果现在直接加 Reflection，会变成：

```text
ReflectionAgent 总结：应该完成熟货 / 家事任务；
但 Candidate Layer 仍然做不到。
```

因此 Phase 3.2 应先重构 Candidate Layer。Memory / Reflection 可以后移到 Phase 3.3。

---

## 2. 本阶段核心目标

Phase 3.2 只做一件大事：

```text
建立 Goal-based Candidate Layer。
```

它包括：

```text
1. 引入 Goal / GoalStep / GoalGraph schema；
2. 把结构化约束转换为通用 GoalGraph；
3. 用 GoalProgressEngine 根据当前状态和历史判断 goal 进度；
4. 用 GoalMaterializer 把 next step 转成可执行 candidate；
5. 用 GoalDiagnostics 诊断 goal 为什么不能物化；
6. 逐步替代旧 planner.py 中 constraint_satisfy candidate 逻辑；
7. 保留普通订单基础候选生成，但将 satisfy candidate 生成迁移到新 Goal Layer。
```

---

## 3. 本阶段不是修什么

Phase 3.2 不应该写成：

```text
修 D009
修 D010
修 ordered_steps
修 specific_cargo
修某个坐标
修某个 cargo_id
修某个 driver_id
```

这些只是测试样例，不是代码目标。

Phase 3.2 要解决的是通用问题：

```text
任何高罚金偏好任务，都应该能表示为 Goal；
任何 Goal 都应该能跟踪进度；
任何 Goal 的下一步都应该能尝试物化成 candidate；
如果不能物化，必须明确诊断原因；
Advisor 只能选择物化后的 candidate_id。
```

---

## 4. 绝对边界

### 4.1 不写 driver 特判

禁止：

```python
if driver_id == "D009":
    ...
if driver_id == "D010":
    ...
```

### 4.2 不写具体 cargo 特判

禁止：

```python
if cargo_id == "240646":
    ...
```

### 4.3 不让 LLM 直接生成 action

禁止：

```json
{"action": "take_order", "cargo_id": "240646"}
```

LLM 可以生成 Goal / Intent，但最终动作必须是 Candidate Layer 物化后的 candidate_id。

### 4.4 不绕过 SafetyGate

最终动作仍然必须经过：

```text
Advisor selected_candidate_id
-> SafetyGate
-> final_action
```

### 4.5 不让 GoalMaterializer 变成策略主控

GoalMaterializer 只能生成候选和诊断，不能直接决定最终执行哪个候选。

### 4.6 不提前做 Phase 3.3

本阶段不做：

```text
MemoryStore
ReflectionAgent
long-term memory
FutureValueEstimator
OpportunityAnalyst
Beam Search
multi-agent debate
```

---

## 5. 当前旧 Candidate Layer 的问题

当前旧 `planner.py / CandidateFactBuilder` 在 Phase 3 架构中实际承担的是：

```text
Candidate Layer / Candidate Generator / CandidateFactBuilder
```

它不是现在的 StrategicPlannerAgent。

旧 Candidate Layer 当前问题：

```text
1. constraint_satisfy candidate 多数是按 constraint_type 写死；
2. 多步任务缺少通用 progress tracking；
3. ordered_steps 可能不会推进 step；
4. 到达目标点后不一定生成 stay/wait next step；
5. specific_cargo 不一定被完整物化为普通 take_order candidate；
6. candidate 是否推进约束缺少统一 facts；
7. 重复选择同一个 satisfy candidate 缺少卡死诊断；
8. Planner intent 和 candidate list 缺少对齐诊断。
```

因此旧 planner 不能继续作为“复杂任务候选生成核心”。

Phase 3.2 的方向是：

```text
保留旧 planner.py 中可用的基础候选能力；
废弃或旁路旧的 constraint_satisfy candidate 规则生成；
引入新的 Goal-based satisfy candidate engine。
```

---

## 6. 新 Candidate Layer 总体架构

推荐新结构：

```text
demo/agent/phase3/goals/
  __init__.py
  goal_schema.py
  goal_builder.py
  goal_progress_engine.py
  goal_materializer.py
  action_templates.py
  completion_checkers.py
  goal_diagnostics.py

demo/agent/phase3/tools/
  candidate_tool.py
  goal_tool.py
```

推荐数据流：

```text
Preference / ConstraintSpec
        |
        v
GoalBuilder
        |
        v
GoalGraph / active_goals
        |
        v
GoalProgressEngine
        |
        v
current_goal_step / next_required_state
        |
        v
GoalMaterializer
        |
        v
goal_satisfy candidates + diagnostics
        |
        v
ConstraintTool / AdvisorTool
```

在 graph 中的位置：

```text
observe
-> preference
-> runtime
-> candidate
   - base candidates from legacy CandidateFactBuilder
   - goal candidates from GoalTool
-> constraint
-> planning
-> advisor
-> safety
-> emit
```

---

## 7. 核心抽象：Goal / GoalStep / GoalGraph

### 7.1 Goal

Goal 表示一个偏好任务或约束任务。

示例字段：

```python
@dataclass
class Goal:
    goal_id: str
    source_constraint_id: str | None
    goal_type: str
    priority: str
    penalty: float | None
    description: str

    steps: list[GoalStep]
    deadline_minute: int | None = None
    active_window: dict | None = None

    status: str = "active"
    metadata: dict = field(default_factory=dict)
```

`goal_type` 可以是通用类型，不是司机特判：

```text
location_sequence
cargo_delivery
stay_requirement
return_by_deadline
rest_requirement
monthly_count
avoid_window
```

注意：`goal_type` 只是结构分类，不负责策略选择。

---

### 7.2 GoalStep

GoalStep 表示 Goal 的一个可推进步骤。

```python
@dataclass
class GoalStep:
    step_id: str
    step_index: int
    step_type: str
    description: str

    target_location: dict | None = None
    target_cargo_id: str | None = None
    required_stay_minutes: int | None = None
    deadline_minute: int | None = None

    completion_condition: dict = field(default_factory=dict)
    acceptable_action_types: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
```

`step_type` 应该尽量少，围绕基础动作语义：

```text
reach_location
stay_at_location
take_specific_cargo
deliver_cargo
return_to_location
stay_until_time
complete_rest
```

这些是通用动作语义，不是司机特判。

---

### 7.3 GoalProgress

```python
@dataclass
class GoalProgress:
    goal_id: str
    status: str
    current_step_index: int
    current_step_id: str | None

    completed_steps: list[str] = field(default_factory=list)
    remaining_steps: list[str] = field(default_factory=list)

    is_stuck: bool = False
    stuck_reason: str | None = None

    last_matching_action_time: int | None = None
    repeated_candidate_count: int = 0

    diagnostics: dict = field(default_factory=dict)
```

---

## 8. GoalBuilder

### 8.1 职责

GoalBuilder 负责把当前已有的结构化约束转换成 Goal。

它不是自然语言解释器。  
它不读原始偏好文本做语义推理。  
它只读取已经结构化的 ConstraintSpec / rule / runtime state。

### 8.2 输入

```text
state.constraints
state.preference_rules
state.runtime_state
state.debug["constraint_summary"]
```

### 8.3 输出

```text
state.active_goals
```

或：

```text
state.debug["goal_summary"]
```

### 8.4 转换原则

不要写 driver 特判。

可以写通用 constraint -> goal adapter，但要尽量抽象成 Goal schema。

例如：

#### ordered_steps -> location_sequence goal

```text
constraint_type: ordered_steps
-> Goal(goal_type="location_sequence")
-> steps:
   reach_location
   stay_at_location
   reach_location
   stay_until_time
```

#### specific_cargo -> cargo_delivery goal

```text
constraint_type: specific_cargo
-> Goal(goal_type="cargo_delivery")
-> step:
   take_specific_cargo
```

#### be_at_location_by_deadline -> return_by_deadline goal

```text
constraint_type: be_at_location_by_deadline
-> Goal(goal_type="return_by_deadline")
-> step:
   reach_location
```

#### stay_at_location -> stay_requirement goal

```text
constraint_type: stay_at_location
-> Goal(goal_type="stay_requirement")
-> step:
   stay_at_location / stay_until_time
```

#### continuous_rest -> rest_requirement goal

```text
constraint_type: continuous_rest
-> Goal(goal_type="rest_requirement")
-> step:
   complete_rest
```

注意：

```text
这仍然有 constraint_type 映射，但这是结构映射，不是策略规则。
它必须只负责把已结构化约束放进统一 Goal schema。
```

---

## 9. GoalProgressEngine

### 9.1 职责

GoalProgressEngine 负责：

```text
根据 current_state + decision_history + action history 判断 Goal 当前进度。
```

它不决定最终动作。

### 9.2 输入

```text
Goal
current location
current time
decision_history
executed actions
driver status
```

### 9.3 输出

```text
GoalProgress
current step
completed steps
remaining steps
stuck diagnostics
```

### 9.4 通用 completion check

要把 completion check 抽象成通用检查器：

```text
location_reached
stay_duration_satisfied
cargo_taken_or_delivered
deadline_satisfied
rest_streak_satisfied
```

目录建议：

```text
completion_checkers.py
```

示例：

```python
def is_location_reached(current_location, target_location, threshold_km) -> bool:
    ...

def get_continuous_stay_minutes(history, location, current_time) -> int:
    ...

def has_cargo_been_taken_or_delivered(history, cargo_id) -> bool:
    ...
```

### 9.5 关键要求：防止重复 step

如果当前位置已经满足当前 step 的 completion condition，必须推进到下一步。

例如：

```text
当前 step = reach_location spouse
当前车辆已在 spouse location threshold 内
=> current_step 应推进到 stay_at_location
=> 不应继续生成 reposition_to_spouse
```

这是通用逻辑，不是 D010 特判。

---

## 10. GoalMaterializer

### 10.1 职责

GoalMaterializer 负责把当前 GoalStep 物化成 candidate。

它输入：

```text
Goal
GoalProgress
current_step
current_state
visible_cargo
base action templates
```

输出：

```text
goal_satisfy_candidates
goal_materialization_diagnostics
```

### 10.2 支持的基础 action templates

不要围绕 constraint_type 写候选，而要围绕基础环境动作写模板：

```text
take_order
wait
reposition
stay
```

可选候选类型：

```text
goal_reach_location
goal_stay_at_location
goal_take_specific_cargo
goal_wait_until_time
goal_complete_rest
```

注意：这些是 candidate source / candidate purpose，不是策略决策。

---

### 10.3 reach_location step

如果当前未到目标点：

生成：

```text
action = reposition
params = target_location
candidate_id = goal_<goal_id>_step_<index>_reach_location
```

如果已经到达目标点：

不生成 reposition，诊断：

```text
step_already_satisfied
advance_to_next_step
```

---

### 10.4 stay_at_location step

如果当前在目标点，但停留不足：

生成：

```text
action = wait
duration = min(remaining_stay, allowed_wait_increment)
candidate_id = goal_<goal_id>_step_<index>_stay
```

如果不在目标点：

生成 reach_location candidate 或诊断：

```text
cannot_stay_not_at_target
```

---

### 10.5 stay_until_time step

如果当前在目标点且需要等到某时间：

生成：

```text
action = wait
duration = min(deadline - current_time, max_wait_increment)
```

如果 wait 过长，可以分段 wait，但 candidate facts 必须说明：

```text
remaining_until_deadline
will_complete_after_wait
```

---

### 10.6 take_specific_cargo step

如果目标 cargo 在 visible cargo 中：

生成完整 take_order candidate，必须复用普通 cargo candidate 的 fact builder 逻辑，不能生成空壳。

必须包含：

```text
cargo_id
pickup location
destination
pickup_arrival_minute
deadline
estimated_net
finish_minute
hard_invalid reasons
soft risk
```

如果目标 cargo 不可见：

不生成 take_order 空壳，而是输出诊断：

```text
target_cargo_not_visible
```

如果可见但不可达：

输出诊断：

```text
target_cargo_unreachable
```

如果可见但 hard invalid：

输出诊断：

```text
target_cargo_hard_invalid
```

---

### 10.7 complete_rest step

可以复用现有 rest candidate 逻辑，但需要 goal facts：

```text
current_rest_streak
required_rest_minutes
remaining_rest_minutes
will_complete_after_wait
is_partial_progress_only
```

注意：本阶段不重写 continuous_rest 策略，只统一成 Goal candidate facts。

---

## 11. CandidateTool 改造

当前 CandidateTool 应从：

```text
调用 legacy candidate adapter
返回 raw_candidates
```

逐步升级为：

```text
1. 生成 base candidates：
   - 普通 cargo candidates
   - wait candidates
   - basic reposition candidates
   - 可以继续复用 legacy CandidateFactBuilder

2. 生成 goal candidates：
   - GoalBuilder
   - GoalProgressEngine
   - GoalMaterializer

3. 合并候选：
   - base_candidates + goal_candidates

4. 写入诊断：
   - goal_summary
   - goal_candidate_summary
   - goal_materialization_diagnostics
```

### 11.1 过渡策略

不要一次删除旧 CandidateFactBuilder。

推荐：

```text
Phase 3.2 第一版：
- 旧 CandidateFactBuilder 继续生成 base candidates；
- 新 GoalMaterializer 生成 goal_satisfy candidates；
- 逐步禁用旧 CandidateFactBuilder 中的 constraint_satisfy 生成，避免重复候选。
```

如果短期无法禁用旧 satisfy 生成，也至少要：

```text
给旧 satisfy candidate 标记 source = legacy_constraint_satisfy
给新 goal candidate 标记 source = goal_satisfy
诊断里区分两者
```

---

## 12. AgentState 需要新增字段

建议新增：

```python
active_goals: list = field(default_factory=list)
goal_progress: dict = field(default_factory=dict)
goal_candidates: list = field(default_factory=list)
goal_diagnostics: dict = field(default_factory=dict)
```

或者放到：

```text
state.debug["goal_summary"]
state.debug["goal_progress"]
state.debug["goal_candidate_summary"]
state.debug["goal_diagnostics"]
```

建议显式字段更好，方便后续 Phase 3.3 / 3.4 使用。

---

## 13. Trace / Decision Summary 增强

每一步应该输出：

```text
active_goal_count
goal_candidate_count
goal_types
high_priority_goal_count
goal_progress_summary
goal_materialization_failures
goal_stuck_suspected
repeated_goal_candidate_selected
```

agent_decisions.jsonl 增加：

```text
active_goal_count
goal_candidate_count
goal_types
selected_candidate_goal_id
selected_candidate_goal_step
selected_candidate_advances_goal
goal_stuck_suspected
goal_materialization_diagnostics
```

---

## 14. Validation Report 增强

新增 Phase 3.2 section：

```markdown
## Goal Candidate Layer

| metric | value |
|---|---|
| active_goal_count | ... |
| goal_candidate_count | ... |
| goal_materialization_failure_count | ... |
| stuck_goal_count | ... |
| repeated_goal_candidate_selected_count | ... |
| selected_goal_candidate_count | ... |
```

按 driver 统计：

```text
goal_stuck_suspected_by_driver
goal_materialization_failure_by_type
repeated_goal_candidate_by_goal_type
specific high-penalty goals without candidate
```

注意：报告里可以显示 D009/D010，但不要在代码里特判。

---

## 15. 和 StrategicPlannerAgent 的关系

Phase 3.2 不是替换 DayPlan，而是让 DayPlan 有执行地基。

关系是：

```text
StrategicPlannerAgent：
    生成 day-level strategy，指出今天应关注哪些高风险目标。

Goal-based Candidate Layer：
    把结构化 goals 物化成 candidate_id，并报告哪些 goal 可执行/不可执行。

Advisor：
    同时看到 DayPlan guidance + goal candidates + diagnostics，
    从候选池中选择 candidate_id。
```

重要：

```text
DayPlan 不直接生成 Goal。
```

第一版 Phase 3.2 可以先从已有 ConstraintSpec 构建 Goal。  
以后如果引入 PreferenceInterpreterAgent，可以让 LLM 直接输出 GoalGraph，但这不属于本阶段。

---

## 16. 不要被 D009/D010 带偏

D009/D010 是验收样例，不是实现目标。

本阶段代码不能出现：

```text
D009
D010
240646
家事
配偶
老家
```

这些词可以出现在日志和测试结果里，但不能作为硬编码条件。

正确实现应该能处理：

```text
任何 specific cargo goal；
任何 ordered/multi-step location goal；
任何 stay requirement；
任何 location deadline goal；
任何 rest requirement goal。
```

---

## 17. 测试策略

### 17.1 第一层：结构测试

```bash
python -m compileall demo/agent
grep -R "D009\\|D010\\|240646" demo/agent/phase3
```

要求：

```text
不应出现硬编码特判。
```

### 17.2 第二层：Goal unit tests

建议新增轻量单元测试或脚本：

```text
test_goal_progress.py
test_goal_materializer.py
```

至少覆盖：

```text
reach_location 已到达 -> 推进下一步
stay_at_location 未满 -> 生成 wait
stay_at_location 已满 -> 推进下一步
specific cargo 可见 -> 生成完整 take_order candidate
specific cargo 不可见 -> 诊断 target_cargo_not_visible
repeated candidate -> 标记 stuck_suspected
```

如果不想引入 pytest，可以写：

```text
demo/agent/phase3/validation/smoke_goal_layer.py
```

### 17.3 第三层：短测 D001-D005

确认没有破坏普通行为：

```text
node_error = 0
final_action missing = 0
goal diagnostics 有输出
fallback 不异常
```

### 17.4 第四层：包含 D009/D010 的短测

这不是特判，而是因为 D009/D010 是高罚金复杂目标样例。

重点看：

```text
D009 是否出现 cargo_delivery goal
D009 如果目标 cargo 不可见，是否有诊断
D009 如果目标 cargo 可见，是否有 goal candidate

D010 是否出现 location_sequence goal
D010 是否推进 step
D010 是否不再无限重复 step 0
```

### 17.5 第五层：完整实验

如果短测通过，再完整跑。

完整实验不要求总收入立刻大涨，但应关注：

```text
高罚金目标失败数量是否下降；
goal_stuck_suspected 是否减少；
repeated_goal_candidate_selected 是否减少；
selected goal candidates 是否合理增加。
```

---

## 18. 验收标准

Phase 3.2 最低验收：

```text
1. 新增 Goal schema；
2. 新增 GoalBuilder；
3. 新增 GoalProgressEngine；
4. 新增 GoalMaterializer；
5. 新增 GoalDiagnostics；
6. CandidateTool 能合并 base candidates 和 goal candidates；
7. goal candidate 有 goal_id / step_index / advances_goal facts；
8. specific cargo 不可见时有明确诊断，不生成空壳 take_order；
9. location sequence 到达后能推进下一步；
10. stay step 能生成 wait/stay candidate；
11. repeated goal candidate 能被诊断；
12. Advisor 仍只选 candidate_id；
13. SafetyGate 仍最终校验；
14. 没有 driver_id / cargo_id 特判；
15. 没有新增 Memory/Reflection/FutureValue；
16. validation report 能输出 Goal Candidate Layer section。
```

---

## 19. 风险与注意事项

### 19.1 最大风险：又写成一堆类型特化工具

不要把代码写成：

```text
ordered_steps_tool.py
specific_cargo_tool.py
stay_tool.py
```

可以有 completion checker / action template，但核心应该是：

```text
GoalProgressEngine
GoalMaterializer
```

而不是一堆约束类型专用工具。

---

### 19.2 最大风险：重复生成候选

旧 CandidateFactBuilder 可能仍生成 constraint_satisfy candidate。新 GoalMaterializer 也生成 goal candidate，可能重复。

需要：

```text
1. 标记 source；
2. 去重；
3. 或逐步禁用旧 satisfy candidate；
4. trace 中区分 legacy_satisfy 和 goal_satisfy。
```

---

### 19.3 最大风险：Goal candidate 抢走普通订单机会

Goal candidate 不应该自动胜出。它只进入候选池。

Advisor 仍要结合：

```text
DayPlan
estimated net
penalty exposure
goal priority
constraint risk
```

来选择。

---

### 19.4 最大风险：LLM 直接控制 GoalMaterializer

本阶段不要让 LLM 在每一步动态生成 action。  
GoalMaterializer 必须是 deterministic tool。

---

## 20. 给代码 Agent 的执行提示词

可以直接复制：

```text
现在进入 TruckDrivers Phase 3.2。目标是重构 Candidate Layer，不是修 D009/D010 特判，也不是新增 Memory/Reflection。

当前问题：
Phase 3.1/3.1.5 已经让 StrategicPlannerAgent 和 DayPlan 生效，Planner 能识别高罚金任务；但旧 planner.py / CandidateFactBuilder 作为 Candidate Layer，不能稳定把复杂任务转成正确、可推进、可执行的 candidate_id。下一步要把 constraint_satisfy candidate 从旧规则式生成，升级为 Goal-based Candidate Materialization。

请新增：

demo/agent/phase3/goals/
  __init__.py
  goal_schema.py
  goal_builder.py
  goal_progress_engine.py
  goal_materializer.py
  action_templates.py
  completion_checkers.py
  goal_diagnostics.py

并修改：
demo/agent/phase3/tools/candidate_tool.py
demo/agent/phase3/agent_state.py
demo/agent/phase3/tools/diagnostic_tool.py
demo/agent/phase3/validation/validate_phase3_run.py

核心要求：
1. 定义 Goal / GoalStep / GoalProgress schema。
2. GoalBuilder 从已有 ConstraintSpec / preference rules 构建 active_goals。
3. GoalProgressEngine 根据 current_state + decision_history 判断每个 goal 当前 step。
4. GoalMaterializer 根据当前 step 生成可执行 goal_satisfy candidates。
5. CandidateTool 合并 base candidates 和 goal candidates。
6. goal candidate 必须包含：
   - goal_id
   - goal_type
   - step_index
   - step_type
   - advances_goal
   - completion_condition
   - materialization_reason
7. 如果 goal 无法物化，必须输出 diagnostics，不要生成空壳 candidate。
8. specific cargo 不可见时输出 target_cargo_not_visible，不生成 fake take_order。
9. location step 已满足时推进到下一 step，不要重复生成同一 reposition。
10. stay step 生成 wait/stay candidate。
11. 重复选择同一 goal candidate 时输出 stuck_suspected 诊断。
12. Trace / agent_decisions / validation report 增加 Goal Candidate Layer section。

禁止：
- 不写 if driver_id == D009/D010；
- 不写 if cargo_id == 240646；
- 不新增 MemoryStore / ReflectionAgent；
- 不新增 OpportunityAnalyst / FutureValueEstimator；
- 不做 lookahead / beam search；
- 不让 LLM 直接生成 action；
- 不绕过 Advisor candidate_id；
- 不绕过 SafetyGate；
- 不让 GoalMaterializer 直接决定 final action。

保留：
- StrategicPlannerAgent / DayPlan 继续作为策略指导；
- Advisor 仍然选择 candidate_id；
- SafetyGate 仍然最终校验；
- legacy CandidateFactBuilder 可继续生成 base candidates；
- 新 GoalMaterializer 负责 goal_satisfy candidates。

验收：
1. compile ok；
2. graph can run；
3. no driver/cargo hardcoding；
4. active_goal_count / goal_candidate_count 出现在日志；
5. goal diagnostics 出现在 validation report；
6. 多步 goal 能推进 step；
7. specific cargo 不可见有诊断；
8. final action 仍来自 candidate_id；
9. D009/D010 只作为测试样例，不作为硬编码对象。
```

---

## 21. 完成后再进入什么阶段

Phase 3.2 完成后，才适合进入：

```text
Phase 3.3：MemoryStore + ReflectionAgent
```

因为那时系统已经具备：

```text
Planner 会提出目标；
Goal-based Candidate Layer 能物化目标；
Advisor 能选择候选；
SafetyGate 能校验；
Trace 能复盘目标推进。
```

这时 Memory/Reflection 才有意义。

---

## 22. 总结

Phase 3.2 不应该是“小修 D009/D010”。

Phase 3.2 应该是：

```text
舍弃旧 planner.py 中偏规则式的 constraint_satisfy candidate 逻辑，
建立 Goal-based Candidate Layer。
```

它解决的是：

```text
Planner 想做的事，Candidate Layer 是否真的做得出来。
```

这是继续 Agentic 大方向的关键一步，不是回到 Phase 2 式修小 bug。
