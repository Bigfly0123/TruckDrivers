# Phase 3.2.5：Goal Layer Boundary Stabilization 与架构收口指南

## 0. 本文档定位

本文档用于指导 TruckDrivers 项目在进入 Phase 3.3 之前，对 Phase 3.2 的 Goal-based Candidate Layer 做一次**边界稳定与架构收口**。

本阶段不是继续追求短期收益提升，也不是继续围绕某个司机、某个订单、某个罚分现象做增量补丁。  
本阶段的核心目标是：

```text
防止 Goal Candidate Layer 过度接管决策；
防止模块继续膨胀；
防止 Python 层、Planner、Advisor、Goal Layer、SafetyGate 之间重新发生职责混乱；
为 Phase 3.3 Memory / Reflection 打一个干净稳定的地基。
```

一句话概括：

```text
Phase 3.2.0 让 goal candidate 能生成；
Phase 3.2.5 要让 goal candidate 有边界、有优先级、有稳定进度，并且不污染后续架构。
```

---

## 1. 为什么需要 Phase 3.2.5

### 1.1 当前项目的主要担忧

TruckDrivers 项目从 Phase 2 到 Phase 3 已经引入了大量新模块：

```text
AgentState
GraphRunner
GraphNodes
Tools
Adapters
TraceLogger
StrategicPlannerAgent
DayPlan
GoalBuilder
GoalProgressEngine
GoalMaterializer
GoalDiagnostics
Validation reports
```

这些模块的引入本身是合理的，因为项目目标是从：

```text
LLM-assisted constrained greedy optimizer
```

升级为：

```text
stateful agentic planning system
```

但是，随着模块数量增加，一个新的风险正在出现：

```text
每发现一个新问题，就继续加一个模块；
每个模块都想影响决策；
最后系统重新变成左右脑互搏。
```

所谓“左右脑互搏”，指的是：

```text
DayPlan 想做 A；
Goal Layer 生成 B；
Advisor 选择 C；
SafetyGate 拦截 D；
Fallback 又返回 E；
旧 Planner / CandidateFactBuilder 还在暗中影响 F；
Validation 只能事后解释，但无法说明谁真正负责。
```

这会导致项目回到早期 Phase 2 的老问题：

```text
表面上越来越 agentic；
实际上决策权越来越分散；
模块边界越来越模糊；
调试越来越困难；
收益下降时不知道该怪 Planner、Advisor、Candidate、Goal 还是 Safety。
```

因此，进入 Phase 3.3 之前，必须先做一次 Phase 3.2.5 的架构收口。

---

## 2. Phase 3.2.0 暴露出的真实问题

### 2.1 3.2.0 并不是完全失败

Phase 3.2.0 的 Goal-based Candidate Layer 已经证明了方向有效：

```text
以前：高罚分目标经常没有 candidate；
现在：goal_satisfy candidate 大量出现。

以前：D010 ordered_steps 卡在 step0；
现在：至少能推进到后续 step，但进度不稳定。

以前：specific_cargo 可能生成 fake candidate；
现在：目标货不可见时不再伪造 take_order，而是记录 target_cargo_not_visible。
```

这说明 Goal Layer 确实接入了主流程，也确实开始影响 Advisor。

### 2.2 但 3.2.0 的作用方向偏了

完整实验结果显示：

```text
Phase 3.1 净收益约：75,301.6
Phase 3.1 罚分约：111,100

Phase 3.2 净收益约：68,634.43
Phase 3.2 罚分约：105,650
```

也就是说：

```text
罚分下降约 5,450；
但净收益下降约 6,667。
```

这说明 3.2 不是没有减少罚分，而是为了少量减少罚分，牺牲了更多运输收益和机会成本。

核心现象：

```text
goal_satisfy 被选中次数过高；
wait 行为明显偏多；
continuous_rest / forbid window / location goal 过度主导；
Advisor 被大量“看起来重要”的 partial goal candidate 牵引。
```

因此问题已经从：

```text
没有 goal candidate
```

变成：

```text
goal candidate 太多、太强、太早、缺少边际价值判断。
```

---

## 3. Phase 3.2.5 的目标

Phase 3.2.5 不追求“马上总收益提升”，而是追求以下目标：

### 3.1 目标一：Goal Candidate 有边界

Goal candidate 不能一出现就天然高优先级。

所有 goal candidate 必须明确：

```text
它推进什么目标？
它是否现在必须做？
如果现在不做，损失是什么？
如果现在做，机会成本是什么？
它是 soft option，还是 urgent action？
```

### 3.2 目标二：Goal Progress 单调稳定

对 ordered_steps 这类多步目标，进度必须是单调的。

```text
step0 一旦完成，不能因为司机离开 step0 位置就回退；
step1 一旦完成，不能因为当前状态变化就回退；
stay / hold 类 step 必须明确是累计停留还是连续停留。
```

### 3.3 目标三：reach 与 stay/hold 语义分离

到达某地不等于完成在某地停留。

```text
reach_location = 到过；
stay_at_location = 停留足够时长；
stay_until_time / hold_location = 在窗口结束前保持不离开。
```

如果这三个语义混在一起，系统就会出现：

```text
sequence_ok = true
但 left_after_arrival = true
最终仍然高罚分。
```

### 3.4 目标四：模块职责重新明确

Phase 3.2.5 必须明确各模块边界，避免重复决策：

```text
StrategicPlannerAgent 不生成 action；
GoalBuilder 不判断收益；
GoalMaterializer 不决定最终动作；
Advisor 不创建 candidate；
SafetyGate 不做收益优化；
Fallback 不赚钱；
Validation 不影响决策；
旧模块不能暗中重新接管策略。
```

### 3.5 目标五：为 Phase 3.3 做准备

Phase 3.3 会引入 Memory / Reflection。  
如果 Phase 3.2 的 Goal Layer 不稳定，Reflection 会把错误行为记录成“经验”，导致后续阶段学偏。

因此 Phase 3.2.5 的本质是：

```text
在引入 Memory / Reflection 之前，
先保证 Goal Layer 不会把错误信号放大成长期记忆。
```

---

## 4. 本阶段明确要做什么

## 4.1 增加 Goal Urgency / Priority 语义

### 问题

当前 goal_satisfy candidate 一旦出现，就容易被 Advisor 当成“应该优先执行”的候选。

尤其是 continuous_rest：

```text
只要当天连续休息尚未满足，
GoalMaterializer 就持续生成 rest goal candidate。
```

这会导致：

```text
当前有高收益订单时，司机仍选择 wait/rest；
为了避免 200-300 的罚分，错过 700-1300 的净收益订单。
```

### 修改要求

所有 goal candidate 必须携带：

```text
goal_id
goal_type
goal_step_type
urgency
priority
penalty_at_risk
opportunity_cost_hint
must_do_now
latest_safe_start_time
reason
```

其中：

```text
urgency ∈ {low, medium, high, critical}
must_do_now ∈ {true, false}
```

默认规则：

```text
goal candidate 默认不得是 high / critical；
只有明确存在时间不可逆风险时，才能升级为 high / critical。
```

### continuous_rest 的特殊规则

continuous_rest 不能因为“还没满足”就强推。

只有在以下情况才允许 high urgency：

```text
如果当前不开始休息，
后续剩余时间已经不足以完成 required_continuous_rest；
或当前继续接单会导致休息目标不可达。
```

否则只能是：

```text
urgency = low 或 medium
must_do_now = false
```

### 最小判断逻辑

可以先实现一个简单版本：

```text
remaining_required_rest = required_rest_minutes - current_rest_streak
latest_safe_start = rest_deadline - remaining_required_rest

if now >= latest_safe_start:
    must_do_now = true
    urgency = high
else:
    must_do_now = false
    urgency = low 或 medium
```

如果当前存在高收益订单，还需要给 Advisor 提供：

```text
best_valid_order_net
rest_penalty_at_risk
opportunity_cost_hint
```

让 Advisor 明白：

```text
现在休息可能只减少 300 罚分；
但会错过 1000+ 的订单收益。
```

---

## 4.2 ordered_steps 改成单调进度状态机

### 问题

Phase 3.2.0 中，ordered_steps 已经不再固定卡在 step0，但出现了新的问题：

```text
step0 / step1 来回摆动；
到达 step1 后，又因为当前位置离开 step0，被判定 step0 未完成；
GoalProgressEngine 像是在每一步重新根据当前状态判断，而不是从历史确认完成进度。
```

这说明 ordered_steps 还不是状态机，而是当前状态匹配器。

### 修改要求

GoalProgressEngine 必须支持：

```text
completed_step_ids
current_step_index
step_started_at
step_completed_at
stay_accumulated_minutes
last_known_goal_location
```

或者在不引入持久存储的情况下，从 decision history / action history 中推导这些字段。

### 单调原则

```text
一旦 step_i 完成，step_i 不得回退；
除非规则明确要求“连续停留”，且停留被中断，则只能重置该 stay step，不能重置更早的 reach step。
```

### 示例

正确行为：

```text
step0: reach spouse location
完成后 completed_step_ids = [0]

step1: stay at spouse location for 10 minutes
如果 stay 完成，completed_step_ids = [0, 1]

step2: return home
完成后 completed_step_ids = [0, 1, 2]

step3: stay until required time
窗口结束后 completed_step_ids = [0, 1, 2, 3]
```

错误行为：

```text
完成 step0 后，司机离开 step0 位置；
下一轮又判断 step0 未完成；
重新生成 step0 reposition。
```

Phase 3.2.5 必须消除这种回退。

---

## 4.3 拆分 reach / stay / hold 语义

### 问题

许多偏好目标不是“到达某地一次”，而是：

```text
在某个窗口内留在某地；
到达后保持不离开；
停留至少 N 分钟；
直到某个时间点都在家。
```

如果 Goal Layer 只生成 reach_location，那么司机会：

```text
到达目标点；
立即离开去接单；
最终仍然因为 left_after_arrival / minutes_not_home_in_window 被罚。
```

### 修改要求

GoalStep 必须区分：

```text
reach_location
stay_at_location
stay_until_time
hold_location
return_to_location
```

### 语义定义

#### reach_location

表示：

```text
司机到达目标位置一次。
```

完成条件：

```text
当前位置达到目标位置；
或历史中存在到达目标位置的事件。
```

不表示：

```text
已经完成停留；
已经完成 home window；
已经完成 stay until deadline。
```

#### stay_at_location

表示：

```text
司机在目标位置停留至少 N 分钟。
```

需要记录：

```text
stay_started_at
stay_accumulated_minutes
required_stay_minutes
interrupted
```

#### stay_until_time / hold_location

表示：

```text
司机必须在目标位置保持到某个时间点或窗口结束。
```

如果当前已经在目标位置，但窗口未结束：

```text
GoalMaterializer 应生成 hold / stay_until candidate；
而不是认为目标已经完成。
```

如果司机离开：

```text
记录 reached_but_left_window；
该目标仍未完成。
```

---

## 4.4 specific_cargo_not_visible 只做诊断增强，不做复杂搜索

### 问题

D009 暴露出 specific_cargo 的问题：

```text
目标货不可见时，GoalMaterializer 不再造 fake take_order；
这是正确的。
```

但系统目前只是记录：

```text
target_cargo_not_visible
```

然后继续被其他低价值 goal 消耗时间。

### 本阶段边界

Phase 3.2.5 不做复杂货源预测，不做机会搜索，不做 FutureValue。

不做：

```text
预测目标货什么时候出现；
预测目标货在哪里出现；
为了目标货盲目 reposition；
写 cargo_id 特判。
```

### 要做的最小增强

记录并暴露：

```text
specific_cargo_goal_active_count
target_cargo_not_visible_count
time_spent_while_specific_cargo_unavailable
other_goal_selected_while_specific_cargo_unavailable
best_valid_order_net_when_specific_cargo_unavailable
```

给 Advisor 的事实提示：

```text
specific cargo 当前不可执行；
不要为了低罚分、低紧急度 goal 消耗大量黄金接单时间；
如果存在高收益合法订单，且不破坏未来可达性，可以优先接单。
```

这一阶段只做诊断和决策提示，不做高级机会规划。  
高级策略留给 Phase 3.4 OpportunityAnalyst / FutureValueEstimator。

---

## 4.5 增强 Validation，而不是继续隐式修逻辑

Phase 3.2.5 必须把问题显式暴露出来。

新增或确保存在以下统计：

```text
goal_satisfy_selected_rate
selected_goal_by_type
selected_goal_by_urgency
continuous_rest_selected_count_by_driver
continuous_rest_high_urgency_count
profitable_valid_order_but_selected_rest_count
rest_opportunity_cost_sum
ordered_steps_regression_count
ordered_steps_current_step_changes
reached_but_left_window_count
hold_candidate_generated_count
specific_cargo_not_visible_count
goal_candidate_count_by_type
goal_materialization_failure_top_reasons
```

这些指标的目的不是马上调到完美，而是判断：

```text
Goal Layer 是否过度接管；
rest 是否在错误时机被选择；
ordered_steps 是否回退；
reach 是否被误判为 hold；
specific_cargo 不可见是否长期没有策略说明。
```

---

## 5. 本阶段明确不要做什么

Phase 3.2.5 的关键不是多做，而是少做。

### 5.1 不写司机特判

禁止：

```python
if driver_id == "D009":
    ...
if driver_id == "D010":
    ...
```

禁止通过司机 ID 修复问题。

### 5.2 不写 cargo_id 特判

禁止：

```python
if cargo_id == "240646":
    ...
```

specific_cargo 必须通过通用 goal 机制处理。

### 5.3 不继续扩大 Goal Layer 的决策权

GoalMaterializer 只能生成 candidate，不能决定最终动作。

禁止：

```text
GoalMaterializer 直接覆盖 final_action；
GoalProgressEngine 直接要求 wait；
GoalBuilder 直接决定接单；
GoalDiagnostics 影响执行。
```

### 5.4 不让 SafetyGate 做收益决策

SafetyGate 只能判断 hard invalid。

禁止：

```text
SafetyGate 因为收益低改成 wait；
SafetyGate 因为 goal 重要强行放行；
SafetyGate 替 Advisor 做 trade-off。
```

### 5.5 不让 Fallback 重新赚钱

Fallback 只能保命。

允许：

```text
没有合法动作时 wait；
系统异常时 safe wait；
hard invalid 时保守处理。
```

禁止：

```text
fallback 自动选择最高收益订单；
fallback 自动选择 goal candidate；
fallback 重新成为隐藏策略层。
```

### 5.6 不在 Phase 3.2.5 做 Memory / Reflection

Phase 3.2.5 不是 Phase 3.3。

禁止：

```text
新增长期记忆；
新增 ReflectionAgent；
把历史失败总结注入 DayPlan；
根据昨天失败直接改变今天策略。
```

这些留到 Phase 3.3。

### 5.7 不做 FutureValue / Opportunity

Phase 3.2.5 不做：

```text
货源出现预测；
未来收益估计；
多步搜索；
beam search；
全局路径规划；
机会区域学习。
```

这些留到 Phase 3.4。

---

## 6. 各模块角色重新定义

这是本阶段最重要的架构收口内容。

## 6.1 StrategicPlannerAgent

### 角色

```text
日级策略规划者。
```

负责：

```text
生成 DayPlan；
识别今日主要风险；
给 Advisor 提供策略提醒；
指出哪些目标值得关注。
```

不负责：

```text
生成 candidate_id；
生成 final_action；
判断某个 action 是否 hard valid；
直接决定 wait / take_order / reposition。
```

### 输出边界

允许输出：

```text
strategy_summary
primary_goal
risk_focus
advisor_guidance
```

禁止输出：

```text
candidate_id
cargo_id
order_id
final_action
直接动作命令
```

---

## 6.2 GoalBuilder

### 角色

```text
把 Preference / ConstraintSpec 转成通用 Goal。
```

负责：

```text
识别 specific_cargo goal；
识别 continuous_rest goal；
识别 ordered_steps goal；
识别 location / stay / hold goal；
构建 Goal / GoalStep 数据结构。
```

不负责：

```text
判断当前是否应该执行；
判断收益是否划算；
生成 final action；
选择 candidate。
```

---

## 6.3 GoalProgressEngine

### 角色

```text
判断目标当前进度。
```

负责：

```text
根据当前状态和历史记录判断 GoalProgress；
维护或推导 completed_step_ids；
判断 ordered_steps 当前 step；
判断 stay 是否累计完成；
判断 hold 是否被中断。
```

不负责：

```text
创建候选；
选择候选；
计算订单收益；
替 Advisor 做 trade-off。
```

关键原则：

```text
Progress 必须单调；
当前状态不能覆盖历史完成事实；
reach / stay / hold 必须分离。
```

---

## 6.4 GoalMaterializer

### 角色

```text
把未完成的 GoalStep 物化成可执行 candidate。
```

负责：

```text
生成 goal_satisfy candidate；
为 candidate 附加 goal facts；
clone 可见 specific_cargo 的完整 base order candidate；
生成 rest / stay / hold / reposition 等目标候选；
为候选附加 urgency / must_do_now / opportunity_cost_hint。
```

不负责：

```text
决定是否最终选择；
绕过 base candidate；
伪造不可见货源；
强行把所有目标变成 high priority。
```

---

## 6.5 CandidateTool

### 角色

```text
候选池组装器。
```

负责：

```text
调用 legacy CandidateFactBuilder 生成 base candidates；
隔离或逐步替换 legacy constraint_satisfy candidates；
调用 GoalTool / GoalMaterializer 生成 goal candidates；
合并 base_candidates + goal_candidates；
记录 candidate source。
```

不负责：

```text
选择最终 candidate；
根据收益直接删除 goal candidate；
根据 goal 直接覆盖 base candidate；
暗中恢复旧 planner 决策权。
```

CandidateTool 是装配层，不是策略层。

---

## 6.6 ConstraintEvaluator

### 角色

```text
软硬约束评估器。
```

负责：

```text
判断 candidate 是否违反 hard constraint；
标记 soft risk；
提供风险 facts；
区分 hard_invalid / soft_risk / valid。
```

不负责：

```text
决定最终动作；
因为有风险直接返回 wait；
因为 goal 重要就忽略 hard invalid。
```

---

## 6.7 Advisor

### 角色

```text
当前动作选择者。
```

负责：

```text
在候选池中选择 candidate_id；
综合收益、风险、DayPlan、Goal facts、urgency、opportunity cost；
解释选择原因。
```

不负责：

```text
创造新 candidate；
输出候选池外动作；
绕过 SafetyGate；
修改 GoalProgress。
```

Advisor 必须理解：

```text
goal_satisfy 不等于必须选择；
urgency = high / critical 才代表强时机压力；
low urgency goal 可以让位给高收益订单。
```

---

## 6.8 SafetyGate

### 角色

```text
最终硬安全校验器。
```

负责：

```text
检查 final candidate 是否 hard valid；
阻止非法动作；
在动作不合法时返回 safe fallback。
```

不负责：

```text
收益优化；
目标优先级判断；
替换成更赚钱的动作；
替换成更符合目标的动作。
```

---

## 6.9 TraceLogger / Validation

### 角色

```text
可观测性和诊断层。
```

负责：

```text
记录每步决策；
记录 goal 是否构建、是否物化、是否被选；
统计收益、罚分、wait 比例、goal selected rate；
暴露模块失效位置。
```

不负责：

```text
影响在线决策；
改变 candidate；
改变 Advisor 输出。
```

Validation 的目标是让人知道：

```text
问题发生在 GoalBuilder、ProgressEngine、Materializer、Advisor、SafetyGate 还是执行环境。
```

---

## 7. 老文件与旧模块如何处理

### 7.1 当前问题

项目文件已经很多，如果继续不加整理，会出现：

```text
不知道哪个文件是主流程；
不知道哪个文件是 legacy；
新旧模块同时做同一件事；
一个 bug 可能在三个地方被修；
后续 agent 容易改错文件。
```

因此，Phase 3.2.5 必须开始做轻量清理。

但注意：

```text
不要大规模删除文件；
不要为了清理而破坏可运行性；
不要一次性重写旧模块。
```

### 7.2 建议采用三类标记

对旧文件进行分类，而不是立刻删除。

#### A. ACTIVE

表示当前主流程直接使用。

例如：

```text
demo/agent/phase3/agent_state.py
demo/agent/phase3/graph_runner.py
demo/agent/phase3/tools/candidate_tool.py
demo/agent/phase3/goals/*
demo/agent/phase3/trace_logger.py
```

文件顶部建议加：

```python
# STATUS: ACTIVE
# ROLE: Phase 3 graph/tool/goal runtime component.
```

#### B. LEGACY_USED

表示旧模块，但仍被 adapter/tool 调用。

例如：

```text
CandidateFactBuilder
PreferenceCompiler
ConstraintEvaluator
LlmDecisionAdvisor
SafetyGate
```

文件顶部建议加：

```python
# STATUS: LEGACY_USED
# ROLE: Legacy implementation still used through Phase 3 tools/adapters.
# NOTE: Do not extend with new strategy logic unless migrating into Phase 3 module.
```

#### C. LEGACY_ARCHIVED

表示旧主流程或旧实验模块，不再作为主流程使用。

例如：

```text
mission_executor.py
mission_replanner.py
llm_mission_planner.py
task_graph_builder.py
candidate_safety_filter.py
旧 planner.py 中不再使用的 constraint_satisfy 逻辑
```

文件顶部建议加：

```python
# STATUS: LEGACY_ARCHIVED
# ROLE: Historical implementation retained for reference only.
# NOTE: Not part of Phase 3 main decision path.
```

### 7.3 建议新增架构索引文档

新增：

```text
demo/agent2.0/phase3_architecture_index.md
```

内容包括：

```text
当前主流程调用链；
ACTIVE 文件列表；
LEGACY_USED 文件列表；
LEGACY_ARCHIVED 文件列表；
禁止修改说明；
新增模块入口规范。
```

这个文档很重要，因为后续 agent 不然很容易继续在旧文件里补逻辑。

### 7.4 暂不建议直接删除旧文件

当前不建议直接大规模删除老文件，原因：

```text
仍可能有 adapter 依赖；
删除后不方便对照；
容易引入 import error；
项目还在快速迭代。
```

推荐策略：

```text
先标记；
再建立 architecture index；
确认 2-3 个阶段不再使用后再归档到 legacy/；
最后再考虑删除。
```

---

## 8. 推荐目录整理方案

### 8.1 当前 Phase 3 主目录

建议保持：

```text
demo/agent/phase3/
  agent_state.py
  graph_runner.py
  trace_logger.py

  graph_nodes/
  tools/
  adapters/
  goals/
  validation/
  utils/
```

### 8.2 Goal Layer 目录

```text
demo/agent/phase3/goals/
  goal_schema.py
  goal_builder.py
  goal_progress_engine.py
  goal_materializer.py
  action_templates.py
  completion_checkers.py
  goal_diagnostics.py
```

职责：

```text
只处理 Goal；
不做 Advisor；
不做 SafetyGate；
不做 final action。
```

### 8.3 文档目录

```text
demo/agent2.0/
  truckdrivers_agentic_architecture_master_plan.md
  phase3_0_agentic_graph_skeleton_guide.md
  phase3_0_5_tool_trace_legacy_guide.md
  phase3_1_strategic_planner_dayplan_guide.md
  phase3_1_5_dayplan_quality_hardening_guide.md
  phase3_2_goal_based_candidate_layer_guide.md
  phase3_2_5_goal_layer_boundary_stabilization.md
  phase3_architecture_index.md
```

---

## 9. Phase 3.2.5 验收标准

Phase 3.2.5 不以总收益作为唯一验收标准。

### 9.1 架构验收

必须满足：

```text
GoalBuilder 不生成 action；
GoalMaterializer 不选择 action；
Advisor 仍只选择 candidate_id；
SafetyGate 仍只做 hard validation；
Fallback 仍只保命；
旧 constraint_satisfy 不重新接管主流程。
```

### 9.2 行为验收

希望看到：

```text
goal_satisfy_selected_rate 不再异常高；
continuous_rest 不再无条件强推；
profitable_valid_order_but_selected_rest_count 下降；
ordered_steps_regression_count 接近 0；
reach 和 hold 的 candidate 分开出现；
D010 类任务不再 step0/step1 来回摆动；
specific_cargo 不可见时有清晰诊断。
```

### 9.3 日志验收

日志中应能看到：

```text
goal_id
goal_type
goal_step_type
urgency
must_do_now
penalty_at_risk
opportunity_cost_hint
selected_candidate_source
selected_candidate_goal_id
goal_materialization_reason
goal_materialization_failure_reason
```

### 9.4 文件治理验收

必须新增或更新：

```text
phase3_architecture_index.md
```

并对关键旧文件加状态标记：

```text
ACTIVE
LEGACY_USED
LEGACY_ARCHIVED
```

---

## 10. 推荐执行顺序

### Step 1：先做文档和文件状态标记

不要先改逻辑。

先完成：

```text
phase3_architecture_index.md
ACTIVE / LEGACY_USED / LEGACY_ARCHIVED 标记
当前主流程调用链说明
```

目的：

```text
防止后续继续改错文件；
防止旧模块被误认为主流程；
防止新 agent 继续乱加模块。
```

### Step 2：给 Goal Candidate 加 urgency

最小改动：

```text
GoalMaterializer 输出 urgency / must_do_now；
continuous_rest 默认 low / medium；
只有 must_rest_now 才 high。
```

### Step 3：修 ordered_steps 单调进度

最小改动：

```text
从 history 推导 completed_step_ids；
禁止 step regression；
记录 ordered_steps_regression_count。
```

### Step 4：拆 reach / hold

最小改动：

```text
reach_location 完成后，如果目标还有 stay/hold window，则生成 hold/stay_until candidate；
不要把 reach 当成整个目标完成。
```

### Step 5：增强 validation

补充统计：

```text
selected_goal_by_urgency
rest opportunity cost
step regression
hold candidate
specific cargo unavailable
```

### Step 6：短测和完整实验

短测先看：

```text
compileall
import smoke
goal urgency smoke
ordered_steps no regression smoke
hold candidate smoke
validation build
```

完整实验再看：

```text
goal_satisfy_selected_rate
wait ratio
penalty
net income
D009 / D010 诊断
```

---

## 11. 给代码 Agent 的执行提示词

```text
我们准备进入 Phase 3.3，但在此之前需要完成 Phase 3.2.5：Goal Layer Boundary Stabilization 与架构收口。

核心目标：
不是继续修 D009/D010 小 bug，也不是追求本轮收益立刻提高，而是防止 Goal Candidate Layer 过度接管决策，防止模块继续膨胀，为 Phase 3.3 Memory / Reflection 打稳定地基。

请严格按以下范围执行：

一、先做架构索引和文件状态标记
1. 新增 demo/agent2.0/phase3_architecture_index.md
2. 说明 Phase 3 当前主流程调用链：
   ModelDecisionService -> AgentState -> GraphRunner -> graph_nodes -> tools -> adapters/goals -> Advisor -> SafetyGate -> Emit
3. 列出 ACTIVE / LEGACY_USED / LEGACY_ARCHIVED 文件
4. 给关键旧文件顶部加状态注释，避免后续误改旧主流程

二、Goal candidate 增加 urgency / must_do_now
1. 所有 goal_satisfy candidate 必须带 urgency: low / medium / high / critical
2. 默认不能 high
3. continuous_rest 不能因为未满足就强推
4. 只有 now >= latest_safe_rest_start 或后续时间不足以完成休息时，才 high / critical
5. 给 Advisor 提供 penalty_at_risk / best_valid_order_net / opportunity_cost_hint

三、ordered_steps 单调进度
1. GoalProgressEngine 不能只根据当前位置重算 step
2. 从 history 推导 completed_step_ids / current_step_index / step_completed_at
3. step 一旦完成不能回退
4. 不写 D010 特判

四、reach / stay / hold 语义分离
1. reach_location 只表示到达
2. stay_at_location 表示停留 N 分钟
3. stay_until_time / hold_location 表示保持到窗口结束
4. 如果已经到达但窗口未结束，应生成 hold/stay_until candidate

五、specific_cargo_not_visible 只做诊断增强
1. 不造 fake take_order
2. 不做 cargo_id 特判
3. 不做复杂货源预测
4. 记录 target_cargo_not_visible_count / time_spent_while_unavailable / other_goal_selected_while_unavailable

六、validation 增强
加入：
- goal_satisfy_selected_rate
- selected_goal_by_urgency
- continuous_rest_high_urgency_count
- profitable_valid_order_but_selected_rest_count
- rest_opportunity_cost_sum
- ordered_steps_regression_count
- reached_but_left_window_count
- hold_candidate_generated_count
- specific_cargo_not_visible_count

禁止事项：
- 不写 D009 / D010 / 240646 特判
- 不新增 Memory / Reflection
- 不新增 FutureValue / Opportunity
- 不让 GoalMaterializer 选择 action
- 不让 SafetyGate 做收益决策
- 不让 Fallback 赚钱
- 不继续增加无边界的新模块

完成后输出：
1. phase3_2_5_goal_layer_boundary_stabilization.md 或更新本文档
2. phase3_architecture_index.md
3. 修改摘要
4. smoke test 结果
5. 完整实验前的注意事项
```

---

## 12. Phase 3.2.5 完成后如何进入 Phase 3.3

当 Phase 3.2.5 完成后，可以进入 Phase 3.3。

但 Phase 3.3 的第一版必须保持克制：

```text
Memory / Reflection 只能观察和提示；
不能直接接管 action；
不能绕过 CandidateTool / Advisor / SafetyGate；
不能因为反思结果直接改 final_action。
```

Phase 3.3 的正确方向：

```text
记录失败模式；
总结昨天/前几天的 goal failure；
给 DayPlan 和 Advisor 提供 strategy hints；
帮助系统避免重复犯错；
但不做强规则控制。
```

如果 Phase 3.3 一上来就根据 memory 强行改动作，项目会再次变乱。

---

## 13. 最终总结

Phase 3.2.5 的意义不是“再修一轮 bug”，而是一次必要的架构收口。

当前项目真正的风险不是某个司机没有修好，而是：

```text
模块越来越多；
每个模块都开始影响策略；
旧模块没有清理；
新模块职责不清；
Goal Layer 过度接管；
后续 Memory / Reflection 可能学到错误信号。
```

因此，本阶段必须坚持：

```text
少加模块；
明确边界；
稳定 Goal Layer；
标记 legacy；
增强诊断；
不做特判；
不让任何非 Advisor 模块偷偷决策。
```

最终目标：

```text
让 Phase 3.2 停在一个可控、可解释、可扩展的状态；
然后再进入 Phase 3.3 Memory / Reflection。
```
