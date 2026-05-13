# TruckDrivers Agent 改造历程、当前状态与后续方向总结（新会话接续版）

## 0. 文档目的

本文用于帮助新的代码 Agent / 新会话重新理解 TruckDrivers 项目目前的改造历程、架构目标、已经做过的 Phase、当前最新问题，以及下一步应该怎么继续。

本项目的最终目标不是写一个只适配当前公开司机偏好的规则系统，而是构建一个更鲁棒的 **Agentic AI 决策系统**。

系统应该能够在司机偏好发生变化、复赛出现新偏好、偏好表达更复杂时，仍然保持较好的泛化能力，而不是依赖大量：

```python
if rule.kind == "xxx":
    return action
```

这种固定规则策略。

---

# 1. 总目标

## 1.1 业务目标

在月度卡车司机仿真环境中，每一步 Agent 都需要根据：

```text
司机当前位置
当前时间
当前可见货源
历史动作
司机偏好
偏好罚分
订单收益
订单成本
硬合法性约束
```

选择动作：

```text
take_order
wait
reposition
```

最终希望：

```text
1. 月度净收益尽量高
2. 偏好罚分尽量低
3. validation_error 为 0
4. 不全 wait
5. 不盲目全接单
6. 能泛化到新的司机偏好
```

核心指标是：

```text
net_income = gross_income - cost - preference_penalty
```

所以我们的目标不是单纯压罚分，也不是单纯接最多订单，而是：

```text
在收入和罚分之间做合理 trade-off，最大化净收益。
```

---

## 1.2 架构目标

我们希望的架构是：

```text
LLM / Advisor 负责策略取舍
Python 负责事实计算、约束评估、候选生成和硬合法校验
```

也就是：

```text
Python 不开车；
Python 只画地图、标风险、生成可选路线、拦截非法动作；
Advisor 才是司机。
```

最终理想链路：

```text
Observe
-> Preference Understanding
-> General Constraint Compilation
-> Candidate Fact Building
-> Constraint Evaluation
-> Satisfy Candidate Generation
-> Advisor Decision
-> Hard Safety Validation
-> Action
```

---

# 2. 已完成 Phase 总览

目前项目经历了以下阶段：

```text
Phase 1：止血与收权
Phase 1.5：框架瘦身
Phase 2.0：中度精简主流程
Phase 2 Bugfix：修复 load_time_window_expired
Phase 2.1：通用偏好约束层
Phase 2.2：动态约束状态与满足候选生成
当前最新问题：rest 候选误导 + hard_invalid 过多
```

---

# 3. Phase 1：止血与收权

## 3.1 初始问题

早期代码里 Python 层做了太多策略决策：

```text
PlannerScorer 会筛掉风险候选
CandidateSafetyFilter 会把 soft risk 变成 blocked
SafetyGate 会静默把动作改成 wait
fallback 会直接 take_order
MissionExecutor 会直接输出动作
```

结果导致：

```text
Advisor 名义上存在
但真正决策权仍在 Python
```

---

## 3.2 Phase 1 目标

Phase 1 的目标是：

```text
1. 区分 hard invalid 和 soft risk
2. soft risk 不提前删除，要交给 Advisor
3. SafetyGate 不静默改动作
4. fallback 不主动赚钱
5. Advisor 输出结构化 JSON
6. reason_tokens 为 0 不影响运行
7. 支持切换模型，比如 Mimo / Qwen
```

---

## 3.3 Phase 1 主要经验

核心结论：

```text
hard invalid 可以由 Python 过滤；
soft risk 不能由 Python 决策；
soft risk 应该进入 Advisor，让 Advisor 做 trade-off。
```

---

# 4. Phase 1.5：框架瘦身

## 4.1 进入 Phase 1.5 的原因

Phase 1 后发现：

```text
代码越来越多
CandidateScore / CandidateView / BlockedCandidate / FilteredCandidates 混用
MissionExecutor / SafetyGate / fallback / Planner 都还保留一点策略权
```

所以 Phase 1.5 的目标是减少模块权力，避免 Python 再次抢方向盘。

---

## 4.2 Phase 1.5 的目标主流程

当时目标是：

```text
Observer
-> CandidateFactBuilder
-> CandidateGrouper
-> Advisor
-> SafetyGate
-> MinimalFallback
```

并且：

```text
fallback 只能保命，不能赚钱
CandidateGrouper 只能分组，不能过滤 soft risk
SafetyGate 只能守门，不能开车
MissionExecutor 不能直接执行任务
Advisor 是唯一策略主脑
```

---

## 4.3 Phase 1.5 中出现的问题

### 4.3.1 Advisor trigger bug

曾出现：

```text
有候选，但 trigger=None
-> 不调用 Advisor
-> fallback wait
-> 全 wait
```

修复原则：

```text
只要 advisor_candidates 非空，就必须调用 Advisor。
```

---

### 4.3.2 BlockedCandidate 结构兼容 bug

日志访问：

```python
candidate.hard_invalid_reasons
```

但旧 `BlockedCandidate` 没有这个字段，导致崩溃。

经验：

```text
日志必须 fail-safe；
候选结构必须尽量统一；
日志错误不能影响最终 action。
```

---

# 5. Phase 2.0：中度精简主流程

## 5.1 为什么做 Phase 2.0

Phase 1.5 之后发现：

```text
名义上在瘦身
实际上代码还在增加适配层
旧模块仍然参与主流程
```

所以进入 Phase 2.0：不再继续修旧复杂框架，而是做中度精简主流程。

---

## 5.2 Phase 2.0 目标主流程

当前主流程应保持为：

```text
get_driver_status / query_cargo / query_decision_history
-> PreferenceCompiler
-> compile_constraints
-> CandidateFactBuilder.build_candidate_pool
-> ConstraintEvaluator.evaluate
-> split: valid / soft_risk / hard_invalid
-> LlmDecisionAdvisor 只选 selected_candidate_id
-> SafetyGate 只做硬合法校验
-> return action
```

---

## 5.3 从主流程弃用的旧模块

这些文件可以存在，但不能重新接入主流程做策略决策：

```text
candidate_safety_filter.py
candidate_pool.py
fact_collector.py
mission_executor.py
mission_replanner.py
llm_mission_planner.py
task_graph_builder.py
复杂 mission lock
复杂 _advisor_trigger gate
复杂 _constrain_advisor_candidates
```

不能再恢复为：

```text
MissionExecutor 主控动作
MissionReplanner 重规划动作
CandidateGrouper 过滤候选
FactCollector pressure 触发动作
SafetyGate 处理 soft preference
```

---

## 5.4 当前 Phase 2.0 状态

当前 `ModelDecisionService` 已经明显变短，约两百行左右，主流程基本符合 Phase 2.0 目标。

这是一个重要进步。

---

# 6. Phase 2 Bugfix：load_time_window_expired

## 6.1 问题表现

Phase 2.0 后系统不再全 wait，开始接单，但出现大量仿真拒绝：

```text
load_time_window_expired
```

说明：

```text
CandidateFactBuilder 认为订单可接
SafetyGate 也通过
但环境认为装货时间窗已过
```

---

## 6.2 修复方向

在 CandidateFactBuilder 和 SafetyGate 中加入装货时间窗硬校验：

```text
arrival_minute = state.current_minute + pickup_minutes
deadline_minute = cargo load deadline

if state.current_minute >= deadline_minute:
    hard_invalid = load_time_window_expired

if arrival_minute + buffer > deadline_minute:
    hard_invalid = load_time_window_unreachable
```

同时注意：

```text
不要把 remove_time 过度误用为严格装货截止；
要确保时间基准一致；
hard_invalid reason 要可追踪。
```

---

# 7. Phase 2.1：通用偏好约束层

## 7.1 为什么进入 Phase 2.1

系统恢复接单后，出现新问题：

```text
总收入上来了
但偏好罚分爆炸
行动几乎全是接单
```

这说明：

```text
CandidateFactBuilder 没有把很多偏好转成风险
Advisor 以为很多订单都是 valid
于是自然选择最高收益订单
```

---

## 7.2 不能回到 Python rule engine

我们明确不要写：

```python
if rule.kind == "daily_rest":
    return wait()

if rule.kind == "home_nightly":
    return reposition_home()

if driver_id == "D009":
    ...
```

这种会导致：

```text
新偏好需要新 if-else
复赛泛化差
Python 重新成为策略主脑
```

---

## 7.3 Phase 2.1 正确方向

新增通用偏好约束层：

```text
原始偏好文本
-> PreferenceRule
-> ConstraintSpec
-> ConstraintEvaluator
-> Candidate risk / satisfy facts
-> Advisor trade-off
```

核心原则：

```text
rule.kind 可以用于“编译”
不能用于“决策”
```

允许：

```python
if rule.kind == "quiet_hours":
    constraint_type = "forbid_action_in_time_window"
```

不允许：

```python
if rule.kind == "quiet_hours":
    return wait()
```

---

## 7.4 通用 ConstraintSpec 类型

当前希望支持的通用约束：

```text
forbid_cargo_category
forbid_action_in_time_window
continuous_rest
operate_within_area
avoid_zone
max_distance
be_at_location_by_deadline
stay_at_location
monthly_count_requirement
specific_cargo
ordered_steps
```

这些不是针对当前 10 个司机写的，而是通用行为原语。

---

## 7.5 Phase 2.1 的效果

通用约束层上线后，出现过一次结果：

```text
总分约 9w
罚分约 10w+
```

相较之前：

```text
罚分从 15w+ 降到 10w+
但总收入也下降
```

说明：

```text
静态约束开始生效
但动态约束还没处理好
```

---

# 8. Phase 2.2：动态约束状态与满足候选生成

## 8.1 为什么进入 Phase 2.2

Phase 2.1 能处理一部分静态约束，比如：

```text
禁接品类
区域限制
距离限制
部分 off-day
```

但动态约束仍然失败：

```text
continuous_rest
forbid_action_in_time_window
be_at_location_by_deadline
specific_cargo
ordered_steps
```

这些不是单个候选的静态判断能解决的，需要：

```text
动态状态追踪
持续候选生成
下一步候选生成
```

---

## 8.2 Phase 2.2 目标

在保持 agentic 主流程不变的前提下，增加：

```text
ConstraintRuntimeState
SatisfyCandidateGenerator
RestStreakTracker
SpecificCargoTracker
OrderedStep next-step generator
```

这些模块只能提供：

```text
状态
候选
风险
罚分暴露
```

不能直接选择动作。

---

## 8.3 Phase 2.2 的核心边界

Python 可以：

```text
计算连续休息状态
计算是否跨禁行窗口
生成 continue_rest 候选
生成 wait_until_window_end 候选
生成 go_home candidate
生成 specific_cargo candidate
生成 ordered_steps 下一步候选
标注 penalty exposure
```

Python 不可以：

```text
因为没休够直接 return wait
因为要回家直接 return reposition
因为 soft risk 直接删除订单
因为 penalty > profit 直接替 Advisor 决策
```

Advisor 仍然选择 candidate_id。

---

# 9. 当前最新问题：Phase 2.2 rest 候选误导 bug

## 9.1 最新异常表现

最新代码和日志显示：

```text
D001 每天前半段倾向于先选择 wait_rest_480
等休息“看似满足”后，后半段再开始接单
有时甚至几乎没有收入
```

日志表现：

```text
visible_cargo_count 很多
hard_invalid_count 接近全部货源数量
valid_count 很少
selected_candidate_id = wait_rest_480
selected_action = wait
```

---

## 9.2 当前异常根因

### 根因 1：wait_rest_480 语义错误

当前候选名：

```text
wait_rest_480
```

但实际动作通常是：

```text
wait 60
```

这会误导 Advisor 以为：

```text
选这个候选就能满足 480 分钟连续休息
```

尤其如果 facts 中写了：

```text
satisfies_continuous_rest = true
```

则误导更严重。

正确做法：

```text
start_rest_60
continue_rest_60
```

并明确：

```text
current_rest_streak_minutes
max_rest_streak_today
required_minutes
rest_streak_after_wait
remaining_rest_minutes_after_wait
actually_satisfies_after_this_wait
```

只有这次 wait 后真的满足 required_minutes，才能把 `actually_satisfies_after_this_wait` 设为 true。

---

### 根因 2：continuous_rest 仍可能使用累计 wait

不能用：

```python
today_wait = sum(wait intervals)
```

这只是当天累计 wait，不是连续休息。

正确应该维护：

```text
current_rest_streak_minutes
max_rest_streak_today
remaining_rest_minutes
```

遇到 take_order / reposition，连续 rest streak 应中断。

---

### 根因 3：rest risk 过度惩罚订单

当前逻辑可能类似：

```text
今天还没休够
-> 所有 take_order 都有高额 rest risk
```

这会导致 Advisor 认为：

```text
所有订单 after penalty 都不值得
所以先休息
```

正确逻辑应该是：

```text
如果接这个订单后，今天剩余时间仍然足够完成连续休息，
就不应该给高额 rest risk。
```

也就是说，rest risk 应判断：

```text
candidate_finish_minute
day_end_minute
remaining_day_minutes_after_candidate
required_rest_minutes
max_rest_streak_today
```

---

### 根因 4：hard_invalid 过多但缺少原因统计

最新日志里经常出现：

```text
visible_cargo_count 很多
hard_invalid_count 接近全部货源数量
```

但没有足够清晰的：

```text
top_hard_invalid_reasons
sample_hard_invalid_candidates
```

需要补充日志，否则无法判断是否 load window 过严、时间解析错误、geometry 错误或区域过滤过严。

---

# 10. 当前最新修复方向

## 10.1 修 rest 候选

不要再生成语义错误的：

```text
wait_rest_480
```

改为：

```text
start_rest_60
continue_rest_60
```

facts 中必须包含：

```text
current_rest_streak_minutes
max_rest_streak_today
required_minutes
wait_duration
rest_streak_after_wait
remaining_rest_minutes_after_wait
actually_satisfies_after_this_wait
```

---

## 10.2 修 continuous_rest 计算

在 `state_tracker.py` 或 runtime state 中计算：

```text
current_rest_streak_minutes
max_rest_streak_today
```

基于连续 wait 计算，而不是当天累计 wait。

---

## 10.3 修 rest risk 逻辑

对 take_order / reposition 候选，不应因为“当前还没休够”就直接标高罚分。

正确判断：

```text
如果 max_rest_streak_today 已满足 required，则无风险；
否则看 candidate 完成后今天是否仍有足够时间完成 required 连续休息；
如果仍有足够时间，则 no/low risk；
如果没有足够时间，则标 soft risk。
```

---

## 10.4 增加 hard_invalid reason 统计

日志中加入：

```json
{
  "top_hard_invalid_reasons": {
    "load_time_window_unreachable": 32,
    "invalid_cargo_geometry": 5
  },
  "sample_hard_invalid_candidates": [
    {
      "candidate_id": "take_order_123",
      "hard_invalid_reasons": ["load_time_window_unreachable"],
      "pickup_arrival_minute": 1230,
      "cargo_deadline_minute": 1220,
      "deadline_source": "remove_time"
    }
  ]
}
```

这样才能判断是否货源被误杀。

---

# 11. 当前必须保持的架构原则

## 11.1 Python 可以做

```text
解析偏好为 ConstraintSpec
计算距离、时间、收益、成本
计算连续休息状态
判断候选是否硬非法
标注 soft_risk
估算 penalty exposure
生成 satisfy candidates
记录日志
```

---

## 11.2 Python 不应该做

```text
直接 force wait
直接 force take_order
直接 force reposition
因为 soft risk 删除候选
因为 rest_not_enough 直接 return wait
因为 driver_id 做特化
因为公开 cargo_id 做特化
恢复 MissionExecutor 主控
让 SafetyGate 处理 soft preference
```

---

## 11.3 Advisor 应该做

```text
比较收益与罚分
选择 candidate_id
接受或拒绝 soft risk
决定是否为了约束暂时 wait / reposition
```

---

## 11.4 SafetyGate 应该做

只做硬合法校验：

```text
action schema
cargo visible
cargo not expired
load window reachable
wait duration legal
reposition coordinate legal
```

---

# 12. 下一步建议

当前不要继续大改架构。

下一步只修：

```text
1. rest candidate 语义
2. continuous_rest 连续状态
3. rest risk 过度惩罚
4. hard_invalid reason 日志
```

先跑 D001 前 50 步验证。

验收：

```text
D001 不再每天前半段无脑 wait_rest
D001 出现 take_order
gross_income > 0
visible cargo 不应几乎全部 hard_invalid
能看到 hard_invalid reason 分布
validation_error = 0
```

---

# 13. 给代码 Agent 的当前任务摘要

请代码 Agent 重点理解：

```text
现在的问题不是模型不聪明，
也不是要恢复旧 mission 系统，
而是 Phase 2.2 的 rest satisfy candidate 和 continuous_rest 状态建模有 bug。
```

优先修：

```text
wait_rest_480 -> start_rest_60 / continue_rest_60
累计 wait -> 连续 rest streak
当前未休够 -> 不等于所有订单高罚分
hard_invalid_count -> 必须有 reason 分布
```

保持 agentic：

```text
Python 生成事实和候选；
Advisor 选择 candidate_id。
```

---

# 14. 一句话结论

项目当前已经完成：

```text
主流程精简
通用约束层雏形
动态约束候选雏形
```

但最新问题是：

```text
rest satisfy candidate 语义错误
continuous_rest 状态计算错误
rest risk 太激进
hard_invalid 过多且不可解释
```

修复这些后，再继续处理：

```text
night window
specific_cargo
ordered_steps
be_at_location_by_deadline
token 优化
收益提升
```
