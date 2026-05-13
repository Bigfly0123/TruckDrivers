# TruckDrivers Agent 改造历程、当前状态与后续方向总结

## 0. 文档目的

本文用于帮助代码 Agent 重新理解本项目当前的改造目标、已经做过的 Phase、出现过的问题、当前架构状态，以及后续应该往哪个方向继续推进。

本项目的目标不是写一个只适配当前公开司机偏好的规则系统，而是构建一个更鲁棒的 **Agentic AI 决策系统**。

最终希望系统在面对新的司机偏好、复杂偏好、组合偏好时，也能比较稳定地工作。

---

# 1. 项目最终目标

## 1.1 业务目标

在卡车司机月度仿真环境中，Agent 每一步需要根据：

```text
司机当前位置
当前时间
可见货源
历史行为
司机偏好
任务约束
收益与成本
```
选择动作：

take_order
wait
reposition

最终目标：

1. 月度净收益尽量高
2. 偏好罚分尽量低
3. validation_error 为 0
4. 能泛化到新的司机偏好
5. 不依赖公开数据特化
1.2 架构目标

我们想要的是：

LLM 理解偏好与做 trade-off
Python 负责事实计算、约束评估、硬合法性校验
Advisor 做最终动作选择

而不是：

Python 根据 rule.kind 写死动作策略

最终理想架构：

Observe
  -> Preference Understanding
  -> General Constraint Compilation
  -> Candidate Fact Building
  -> Constraint Evaluation
  -> Advisor Decision
  -> Hard Safety Validation
  -> Action

核心理念：

Python 不开车；
Python 只画地图、标风险、拦非法；
Advisor 才是司机。
2. 总体路线

我们目前大致经历了这些阶段：

Phase 1：止血与收权
Phase 1.5：框架瘦身
Phase 2.0：中度精简主流程
Phase 2 Bugfix：修复 load_time_window_expired
Phase 2.1：通用偏好约束层
当前阶段：动态约束状态与满足候选生成

每个阶段的目的不同。不要混淆。

3. Phase 1：止血与收权
3.1 Phase 1 的目标

最初代码的问题是：

Python 规则层做了太多策略判断
LLM Advisor 没有真正的决策空间
soft risk 经常被当 hard invalid
SafetyGate 会静默改动作
fallback 会绕过 Advisor 直接 take_order

Phase 1 的目标是：

1. 减少 Python 硬编码策略
2. 区分 hard invalid 与 soft risk
3. 让 soft risk candidates 进入 Advisor
4. SafetyGate 只做硬安全
5. Advisor 输出结构化 JSON
6. reason_tokens 为 0 不影响流程
7. 支持 Qwen3.5-Flash / Mimo 等模型切换
3.2 Phase 1 中发现的问题
问题 1：PlannerScorer 权限太大

原来 Planner / Scorer 既做事实计算，又做策略筛选，导致：

候选在进入 Advisor 前已经被 Python 改写或删除

我们希望它变成：

CandidateFactBuilder

只做：

收益计算
成本计算
距离计算
时间窗计算
hard_invalid 标注
soft_risk 标注
问题 2：CandidateSafetyFilter 误杀 soft risk

原本 CandidateSafetyFilter 会把一些 risky candidates moved to blocked。

这会导致：

高收益 soft risk 候选根本不给 Advisor 看

我们要求：

soft risk 不过滤
hard invalid 才过滤
问题 3：SafetyGate 静默改 wait

原本 SafetyGate 会把 Advisor 选的动作改成 wait，导致日志看不清。

目标改成：

SafetyGate 只返回 accepted / rejected + reason
不替 Advisor 选择策略
问题 4：fallback 抢方向盘

原本有：

source=fallback action=take_order

也就是说 Python fallback 直接接单。

这违背 Agentic 目标。

Phase 1 要求：

fallback 只能保命，不能赚钱
4. Phase 1.5：框架瘦身
4.1 为什么进入 Phase 1.5

Phase 1 修了一些问题后，发现新问题：

代码越来越多
CandidateView / BlockedCandidate / CandidateScore / FilteredCandidates 混用
MissionExecutor / Planner / SafetyGate / fallback 都还在做一点决策

虽然名义上是 Agentic，但实际还是：

旧复杂框架 + 新补丁

因此进入 Phase 1.5：框架瘦身。

4.2 Phase 1.5 的目标

目标是把主流程简化成：

Observer
-> CandidateFactBuilder
-> CandidateGrouper
-> Advisor
-> SafetyGate
-> MinimalFallback

并且：

fallback 只能保命
CandidateGrouper 只能分组
SafetyGate 只能守门
MissionExecutor 不能直接执行
Advisor 是唯一策略主脑
4.3 Phase 1.5 中做过的事
fallback 降权

要求：

fallback 不允许主动 take_order
fallback 只允许在 LLM 失败、JSON 解析失败、SafetyGate 重试失败、无候选时 wait
CandidateSafetyFilter 改成 CandidateGrouper

从：

filter candidates

改成：

group candidates
MissionExecutor 降级

要求：

MissionExecutor 不直接 return final action
mission 只能生成 candidate 或 context
SafetyGate 极窄化

要求只做：

action schema
cargo visible
cargo not expired
pickup reachable
wait duration legal
reposition coordinate legal
4.4 Phase 1.5 产生的新 bug
Bug：Advisor 仍然被 trigger gate 控制

当 fallback 不能 take_order 后，如果 Advisor 仍然只在特殊 trigger 下调用，就会出现：

有候选，但 trigger=None
-> 不调用 Advisor
-> fallback wait
-> 全 wait

修复要求：

只要 advisor_candidates 非空，就必须调用 Advisor
Bug：BlockedCandidate 没有 hard_invalid_reasons

日志函数直接访问：

c.hard_invalid_reasons

但 hard_invalid_candidates 里有旧结构 BlockedCandidate，导致：

AttributeError: 'BlockedCandidate' object has no attribute 'hard_invalid_reasons'

修复思路：

日志函数必须 fail-safe
候选结构最好统一
5. Phase 2.0：中度精简主流程
5.1 为什么进入 Phase 2.0

Phase 1.5 后发现：虽然在“瘦身”，但代码没有少，反而增加了很多适配层。

因此 Phase 2.0 的目标变成：

不要继续给旧框架打补丁；
从主流程中移除明显负作用模块；
保留中度精简主流程。
5.2 Phase 2.0 的目标主流程

目标主流程：

Observe
-> PreferenceCompiler
-> CandidateFactBuilder
-> 简单分组 valid / soft_risk / hard_invalid
-> LlmDecisionAdvisor 选择 candidate_id
-> SafetyGate 硬校验
-> 返回动作
5.3 Phase 2.0 要弃用的模块

从主流程弃用：

CandidateGrouper / CandidateSafetyFilter
MissionExecutor
MissionReplanner
LlmMissionPlanner
TaskGraphBuilder
FactCollector
复杂 mission lock
复杂 _advisor_trigger gate
复杂 _constrain_advisor_candidates
复杂 fallback

文件可以保留，但主流程不再调用。

5.4 Phase 2.0 保留的模块

保留：

ModelDecisionService
PreferenceCompiler
CandidateFactBuilder
LlmDecisionAdvisor
SafetyGate
StateTracker
5.5 当前 Phase 2.0 状态

当前 ModelDecisionService 已明显变短，大约两百行左右。
主流程基本符合：

PreferenceCompiler
CandidateFactBuilder
Advisor
SafetyGate

旧模块如：

CandidateGrouper
FactCollector
MissionExecutor
MissionReplanner
LlmMissionPlanner
TaskGraphBuilder

已经不再是主流程核心。

这是一个重要进步。

6. Phase 2 Bugfix：load_time_window_expired
6.1 问题表现

Phase 2.0 后系统不再全 wait，开始大量接单。
但是出现了大量环境拒绝：

load_time_window_expired

说明：

CandidateFactBuilder 认为订单可接
SafetyGate 也通过
但仿真环境认为装货时间窗已过
6.2 根因

CandidateFactBuilder / SafetyGate 没有正确判断：

当前时间是否已过装货截止
司机到达装货点时是否已过装货截止

原本可能只判断了：

remove_time

但环境实际使用的是：

load_time_window_end / pickup_deadline / remove_time 等装货截止
6.3 修复目标

在 CandidateFactBuilder 中：

arrival_minute = state.current_minute + pickup_minutes
deadline_minute = cargo deadline

如果：

state.current_minute >= deadline_minute

则：

hard_invalid_reasons += load_time_window_expired

如果：

arrival_minute + buffer > deadline_minute

则：

hard_invalid_reasons += load_time_window_unreachable

SafetyGate 中也要重复校验。

6.4 修复后效果

系统稳定性提升，接单失败减少。
进入下一阶段时，主要问题不再是硬合法 bug，而是：

偏好罚分过高
7. Phase 2.1：通用偏好约束层
7.1 为什么进入 Phase 2.1

主流程精简后，系统接单能力恢复。
最新结果中总分一度达到约 11.9w，但罚分超过 15w。

这说明：

系统会赚钱
但不理解偏好风险
行动几乎都是接单
daily rest / night no-drive / home / mission 类罚分爆炸
7.2 关键担忧

不能为了当前开放司机偏好写大量：

if rule.kind == "daily_rest":
    ...
elif rule.kind == "quiet_hours":
    ...
elif rule.kind == "home_nightly":
    ...

因为复赛可能出现新的偏好。

这种写法短期可能提分，但不鲁棒。

7.3 Phase 2.1 的核心目标

构建：

General Preference Constraint Layer

也就是：

原始偏好文本
-> PreferenceCompiler / LLM 解析
-> 通用 ConstraintSpec
-> ConstraintEvaluator 评估候选动作影响
-> Advisor 做 trade-off

核心原则：

rule.kind 可以用于编译
不能直接用于决策

允许：

if rule.kind == "quiet_hours":
    constraint_type = "forbid_action_in_time_window"

不允许：

if rule.kind == "quiet_hours":
    return wait()
8. 通用 ConstraintSpec 设计
8.1 新增结构

新增：

preference_constraints.py

定义：

ConstraintSpec
TimeWindowSpec
LocationSpec
AreaBoundsSpec
TaskStepSpec
8.2 支持的通用 constraint_type

本阶段希望支持这些通用能力：

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

这些不是具体司机偏好，而是通用行为原语。

8.3 通用化示例
daily_rest

不要做：

if rule.kind == "daily_rest":
    force_wait()

而是编译成：

{
  "constraint_type": "continuous_rest",
  "scope": "daily",
  "required_minutes": 480,
  "priority": "soft",
  "penalty_amount": 300
}
quiet_hours

不要做：

if rule.kind == "quiet_hours":
    forbid_order()

而是编译成：

{
  "constraint_type": "forbid_action_in_time_window",
  "actions": ["take_order", "reposition"],
  "time_window": {"start": 1380, "end": 240},
  "priority": "soft",
  "penalty_amount": 500
}
home_by_deadline

编译成：

{
  "constraint_type": "be_at_location_by_deadline",
  "location": {"lat": ..., "lng": ..., "radius_km": ...},
  "deadline": "23:00",
  "priority": "soft",
  "penalty_amount": 900
}
complex family task

编译成：

{
  "constraint_type": "ordered_steps",
  "steps": [
    {"step_type": "visit_location", "location": "...", "deadline": "..."},
    {"step_type": "stay_duration", "required_minutes": 10},
    {"step_type": "visit_location", "location": "...", "deadline": "..."},
    {"step_type": "stay_until", "deadline": "..."}
  ],
  "penalty_amount": 9000
}
9. ConstraintEvaluator
9.1 目的

新增：

constraint_evaluator.py

职责：

ConstraintSpec + Candidate + State + History
-> hard_invalid_reasons
-> soft_risk_reasons
-> constraint_impacts
-> estimated_penalty_exposure
-> satisfies_constraints
9.2 它不能做什么

ConstraintEvaluator 不能：

1. 直接选择 action
2. 强制 wait
3. 强制 take_order
4. 强制 reposition
5. 调用 LLM
6. 替 Advisor 做 trade-off

它只能标注候选影响。

9.3 候选事实中应加入
{
  "constraint_impacts": [
    {
      "constraint_id": "...",
      "constraint_type": "...",
      "severity": "soft",
      "risk_code": "...",
      "estimated_penalty": 500
    }
  ],
  "estimated_penalty_exposure": 500,
  "estimated_net_after_penalty": 1200,
  "satisfies_constraints": []
}
10. Satisfy Candidates
10.1 为什么需要 satisfy candidates

只给接单候选标风险不够。
如果 Advisor 只看到：

take_order：有收益
wait：没有收益

它很容易一直接单。

因此 CandidateFactBuilder 还需要生成：

能够满足偏好的候选

例如：

wait_rest
wait_until_window_end
go_to_required_location
specific_cargo
ordered_step_next_action
10.2 continuous_rest -> wait_rest

如果司机今天需要连续休息 8 小时，应生成：

{
  "candidate_id": "wait_rest_480",
  "action": "wait",
  "params": {"duration_minutes": 60},
  "source": "constraint_satisfy",
  "facts": {
    "satisfies_constraint_type": "continuous_rest",
    "adds_rest_minutes": 60,
    "remaining_rest_minutes_after": 420,
    "avoids_estimated_penalty": 300
  }
}

注意：如果环境单次最多 wait 60 分钟，需要连续生成 continue_rest 候选，而不是只生成一次。

10.3 forbidden time window -> wait_until_window_end

如果当前进入 23:00-04:00 不接单窗口，生成：

{
  "candidate_id": "wait_until_quiet_window_end",
  "action": "wait",
  "params": {"duration_minutes": 60},
  "source": "constraint_satisfy",
  "facts": {
    "satisfies_constraint_type": "forbid_action_in_time_window",
    "avoids_estimated_penalty": 500
  }
}
10.4 home deadline -> go_to_required_location

生成：

{
  "candidate_id": "go_home_before_deadline",
  "action": "reposition",
  "params": {"latitude": ..., "longitude": ...},
  "source": "constraint_satisfy",
  "facts": {
    "satisfies_constraint_type": "be_at_location_by_deadline",
    "deadline_minute": ...,
    "penalty_if_missed": 900
  }
}
10.5 specific_cargo

如果指定货源当前可见，生成完整候选：

{
  "candidate_id": "specific_cargo_240646",
  "action": "take_order",
  "params": {"cargo_id": "240646"},
  "source": "constraint_satisfy",
  "facts": {
    "satisfies_constraint_type": "specific_cargo",
    "penalty_if_missed": 10000
  }
}

如果不可见，不要生成假 take_order，只在 context 中记录：

target_cargo_not_visible
10.6 ordered_steps

只生成当前下一步候选，不恢复旧 MissionExecutor。

例如：

当前 step = visit_location
-> 生成 reposition candidate

当前 step = stay_duration
-> 生成 wait candidate

当前 step = take_specific_cargo
-> 如果 cargo visible，生成 take_order candidate

Advisor 决定是否执行。

11. 最新 Phase 2.1 实验结果

最近一版结果：

总分约 9w
罚分约 10w+

对比之前：

总分约 11.9w
罚分约 15w+

说明：

通用约束层开始生效，罚分下降
但收入也下降
而且高额动态罚分仍然存在
12. 当前最新问题分析
12.1 静态约束改善了

例如：

禁接货物
区域限制
距离限制
部分 off-day

罚分下降明显。

这说明 ConstraintSpec / ConstraintEvaluator 的方向有效。

12.2 动态约束仍然失败

当前主要罚分集中在：

continuous_rest
forbid_action_in_time_window
be_at_location_by_deadline
specific_cargo
ordered_steps

这些不是单步静态判断能完全解决的。

它们需要：

动态状态追踪
连续候选生成
下一步任务候选
13. 当前代码暴露的问题
13.1 continuous_rest 被错误实现为累计 wait

当前 continuous_rest 可能统计的是：

当天 wait 总和

但评分要求是：

连续停车 / 连续休息

所以要维护：

current_rest_streak_minutes
max_rest_streak_today
remaining_rest_minutes

而不是只看当天总 wait。

13.2 wait_rest 每次最多 60 分钟，但没有连续保持机制

如果司机需要 480 分钟连续休息，而环境一次最多 wait 60，那么系统必须在下一步继续生成：

continue_rest

否则 Advisor 下一步又接单，连续休息就断了。

13.3 forbid_action_in_time_window 只标风险，不生成避让候选

应生成：

wait_until_window_end
park_through_quiet_hours

并告诉 Advisor：

这个 wait 可以避免罚分
13.4 specific_cargo 没有真正追踪目标货源

对于 D009 这种指定熟货：

如果目标 cargo 可见，应生成完整高优先级候选
如果不可见，应在 context 中记录等待/搜索状态

不能生成空的假候选。

13.5 ordered_steps 没有通用 next-step 状态机

D010 家事任务失败说明 ordered_steps 还没真正执行。

但不要恢复旧 MissionExecutor。
应该只做：

当前步骤状态追踪
生成下一步候选
Advisor 选择
14. 当前下一阶段建议：Phase 2.2
14.1 阶段名称
Phase 2.2：Dynamic Constraint State & Satisfy Candidate Generator
14.2 目标

在不破坏 agentic 架构的前提下，补齐动态约束能力：

1. 连续休息状态
2. 禁行窗口避让候选
3. 回家/到点 deadline 候选
4. 指定货源追踪
5. ordered_steps 下一步候选
14.3 不要做

不要：

1. 恢复 MissionExecutor
2. 恢复 MissionReplanner
3. 写 driver_id 特化
4. 写 cargo_id 特化，除非 cargo_id 来自 ConstraintSpec
5. Python 直接强制动作
6. SafetyGate 处理 soft preference
14.4 要做

新增或加强：

ConstraintStateTracker
SatisfyCandidateGenerator
OrderedStepState
SpecificCargoTracker
RestStreakTracker

这些模块只提供：

状态
候选
风险

不做最终动作选择。

15. 后续方向
15.1 短期目标

降低罚分，尤其：

D009 home-by-23 + night window
D010 family ordered_steps
continuous_rest
quiet_hours
specific_cargo
15.2 中期目标

减少 token 成本：

1. 无风险 top valid 单可自动直通或低频调用 Advisor
2. Advisor prompt 压缩
3. 只传 top candidates
4. 只在 trade-off 场景调用 LLM

但要注意：不能让 Python 回到复杂规则决策。

15.3 长期目标

形成真正泛化的 Agentic 系统：

新偏好文本
-> 通用约束编译
-> 通用约束评估
-> 满足候选生成
-> Advisor trade-off

而不是：

新偏好 -> 新 Python if-else
16. 当前架构原则总结
16.1 Python 可以做
1. 解析时间、地点、区域
2. 计算距离、时间、收益、成本
3. 判断动作物理合法性
4. 评估候选与通用约束的关系
5. 标注 hard_invalid / soft_risk
6. 估算 penalty exposure
7. 生成 satisfy candidates
8. 维护动态约束状态
16.2 Python 不应该做
1. 不应该直接根据偏好选择动作
2. 不应该直接 force wait / force take_order / force reposition
3. 不应该把 soft risk 当 hard invalid
4. 不应该写 driver_id 特化
5. 不应该写公开数据特化
6. 不应该恢复旧 MissionExecutor 主控流程
7. 不应该让 SafetyGate 处理策略问题
16.3 Advisor 应该做
1. 比较收益与罚分
2. 选择 candidate_id
3. 接受或拒绝 soft risk
4. 决定是否为了长期约束暂时 wait/reposition
5. 解释选择
16.4 SafetyGate 应该做

只做硬合法校验：

action schema
cargo visible
cargo not expired
load window reachable
wait duration legal
reposition coordinates legal

不处理 soft preference。

17. 对代码 Agent 的当前任务建议

如果代码 Agent 要继续工作，建议按这个顺序：

Step 1：整理当前主流程

确认当前主流程保持：

CandidateFactBuilder
ConstraintEvaluator
Advisor
SafetyGate

不要重新引入旧 mission 系统。

Step 2：修 continuous_rest

重点：

连续休息，而不是累计 wait

新增：

current_rest_streak_minutes
max_rest_streak_today
continue_rest candidate
Step 3：修 forbid_action_in_time_window

新增：

wait_until_window_end

并在候选 facts 中写明：

avoids_estimated_penalty
Step 4：修 specific_cargo

确保：

指定 cargo 可见时生成完整 candidate
不可见时只写 context，不生成假 action
Step 5：修 ordered_steps

只实现：

next-step candidate generator

不要恢复 executor。

Step 6：压缩 Advisor 输入

减少 token 成本，但不要牺牲必要 constraint facts。

18. 当前阶段的一句话结论

我们已经从：

复杂 Python rule system

走到了：

精简主流程 + 通用约束层雏形

现在不能回头恢复复杂执行器，也不能继续为每种偏好写 if-else。

下一步要做的是：

让通用约束层具备动态状态和满足候选生成能力。

最终目标仍然是：

LLM 理解偏好；
Python 通用评估；
Advisor 做决策；
SafetyGate 守底线