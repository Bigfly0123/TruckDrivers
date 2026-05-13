# Phase 2.2：Dynamic Constraint State & Satisfy Candidate Generator

## 0. 当前背景

当前项目已经完成了 Phase 2.0 的中度主流程精简，并进入 Phase 2.1 的通用偏好约束层。

目前主流程应保持为：

```text
get_driver_status / query_cargo / query_decision_history
-> PreferenceCompiler
-> compile_constraints
-> CandidateFactBuilder.build_candidate_pool
-> ConstraintEvaluator.evaluate
-> split: valid / soft_risk / hard_invalid
-> LlmDecisionAdvisor choose selected_candidate_id
-> SafetyGate hard validation
-> return action
```
这个方向不能回退。

当前最新实验显示：

总分约 9w
罚分约 10w+

说明通用约束层已经开始生效，罚分比上一版有所下降；但仍有大量动态偏好没有处理好，尤其是：

continuous_rest
forbid_action_in_time_window
specific_cargo
ordered_steps
be_at_location_by_deadline

目前的问题不是主流程错误，而是：

ConstraintEvaluator 主要在做单步风险标注；
缺少动态状态追踪；
缺少持续满足约束的候选生成。

Phase 2.2 的目标就是补齐这部分。

1. Phase 2.2 总目标

本阶段目标：

在保持 agentic 主流程不变的前提下，
增加动态约束状态和满足候选生成能力。

核心思想：

Python 不直接决策；
Python 只维护动态状态、标注约束影响、生成可满足偏好的候选；
Advisor 仍然负责最终选择 candidate_id。

最终希望做到：

1. continuous_rest 使用连续休息状态，不再使用累计 wait 误判
2. forbid_action_in_time_window 能生成 wait_until_window_end 候选
3. specific_cargo 可见时生成完整候选，不可见时只进入 context
4. ordered_steps 只生成当前下一步候选，不恢复 MissionExecutor
5. be_at_location_by_deadline 能生成 go_to_required_location 候选
6. Advisor 能看到 satisfy candidate 的 penalty avoidance 价值
7. 总罚分下降，同时不把收入打回 0
2. 本阶段不做什么

不要做：

1. 不恢复 MissionExecutor
2. 不恢复 MissionReplanner
3. 不恢复 LlmMissionPlanner 主控流程
4. 不恢复 TaskGraphBuilder 主控流程
5. 不让 SafetyGate 处理 soft preference
6. 不写 driver_id 特化
7. 不写公开 cargo_id 特化，除非 cargo_id 来自 ConstraintSpec
8. 不让 Python force wait / force take_order / force reposition
9. 不为了当前开放结果写死司机策略

可以复用旧模块里的工具函数，但不要恢复旧模块的主控地位。

3. 当前主要问题复盘
3.1 continuous_rest 被当成累计 wait

当前 continuous_rest 可能统计的是：

当天 wait 总和

但评分规则通常要求：

连续停车休息 / 连续熄火休息

这两者不同。

错误示例：

10:00 wait 60
13:00 wait 60
18:00 wait 60

累计 wait = 180 分钟
但最长连续休息只有 60 分钟

如果司机偏好是“每天连续停车休息不少于 3 小时”，上面这种情况不满足。

因此 Phase 2.2 必须追踪：

current_rest_streak_minutes
max_rest_streak_today
remaining_rest_minutes
3.2 wait_rest 候选没有持续性

当前如果司机需要连续休息 480 分钟，但系统每次只生成：

wait_60

Advisor 可能下一步又接单，导致连续休息被打断。

正确做法：

如果正在补 continuous_rest，
下一步继续生成 continue_rest candidate，
并告诉 Advisor：接单会重置当前 rest streak。
3.3 forbid_action_in_time_window 只标风险，不生成避让候选

目前对夜间/午间/凌晨禁行窗口，多数只是给 take_order/reposition 标风险。

但 Advisor 也需要看到：

wait_until_window_end

这种满足候选。

否则它看到的是：

take_order: 有收益
wait_60: 没收益

自然会偏向接单。

3.4 specific_cargo 生成方式不对

对于 specific_cargo 约束：

如果目标 cargo 当前可见，应生成完整 take_order candidate
如果不可见，不应生成假 take_order

否则会出现：

候选不可执行
SafetyGate 拒绝
Advisor 浪费选择

正确做法：

可见 -> 生成完整候选，带 cargo facts 和 penalty_if_missed
不可见 -> 只写 target_cargo_not_visible context
3.5 ordered_steps 只有结构，没有 next-step candidate

ordered_steps 不应该恢复成复杂 MissionExecutor。
只需要做：

当前任务进度判断
生成下一步候选
Advisor 选择

例如：

当前下一步是 visit_location
-> 生成 reposition candidate

当前下一步是 stay_duration
-> 如果在目标点附近，生成 wait candidate

当前下一步是 specific_cargo
-> 如果 cargo visible，生成 take_order candidate
4. 新增模块建议

建议新增或修改以下模块：

state_tracker.py
agent_models.py
planner.py
constraint_evaluator.py
preference_constraints.py
llm_decision_advisor.py
model_decision_service.py

可以新增：

constraint_runtime.py
satisfy_candidate_generator.py

如果希望少新增文件，也可以先把 satisfy candidate 逻辑放在 planner.py 里，但要保持清晰。

5. ConstraintRuntimeState 设计

建议新增：

demo/agent/constraint_runtime.py

或在 agent_models.py 中新增 dataclass。

5.1 数据结构
from dataclasses import dataclass, field
from typing import Any

@dataclass
class RestRuntimeState:
    current_rest_streak_minutes: int = 0
    max_rest_streak_today: int = 0
    remaining_rest_minutes_by_constraint: dict[str, int] = field(default_factory=dict)

@dataclass
class TimeWindowRuntimeState:
    active_forbidden_windows: list[dict[str, Any]] = field(default_factory=list)
    upcoming_forbidden_windows: list[dict[str, Any]] = field(default_factory=list)

@dataclass
class SpecificCargoRuntimeState:
    target_cargo_ids: list[str] = field(default_factory=list)
    visible_target_cargo_ids: list[str] = field(default_factory=list)
    missing_target_cargo_ids: list[str] = field(default_factory=list)

@dataclass
class OrderedStepRuntimeState:
    current_step_index_by_constraint: dict[str, int] = field(default_factory=dict)
    step_status_by_constraint: dict[str, dict[str, Any]] = field(default_factory=dict)

@dataclass
class ConstraintRuntimeState:
    rest: RestRuntimeState = field(default_factory=RestRuntimeState)
    time_windows: TimeWindowRuntimeState = field(default_factory=TimeWindowRuntimeState)
    specific_cargo: SpecificCargoRuntimeState = field(default_factory=SpecificCargoRuntimeState)
    ordered_steps: OrderedStepRuntimeState = field(default_factory=OrderedStepRuntimeState)
    debug: dict[str, Any] = field(default_factory=dict)
5.2 原则

这个状态只服务于：

1. 生成候选
2. 标注风险
3. 告诉 Advisor 当前约束进度

不能直接驱动动作。

6. StateTracker 修改要求
6.1 计算连续休息状态

在 state_tracker.py 中基于历史动作计算：

current_rest_streak_minutes
max_rest_streak_today

休息定义暂时可以简化为：

连续 wait 动作

后续可扩展为：

wait + 停车不移动

计算逻辑：

1. 只看当天历史动作
2. 连续 wait 累加
3. 遇到 take_order / reposition 则 rest streak 归零
4. max_rest_streak_today 记录当天最大连续 wait 时长
5. 如果最近动作是 wait，则 current_rest_streak_minutes 为当前连续 wait 总时长
6.2 计算 remaining_rest_minutes

对于每个 continuous_rest constraint：

required_minutes - max_rest_streak_today

如果当前正在休息，继续休息可以增加 current_rest_streak。

注意：

不要用当天 wait 总和。
7. forbid_action_in_time_window 修改要求
7.1 compile_constraints 补 actions

对于类似：

夜间不接单不空驶
凌晨不接单不空驶
午间不接单不空驶

actions 应包含：

take_order
reposition

如果原文只说不接单，则 actions 只包含 take_order。
如果原文说不外跑/不空驶，则包含 reposition。
如果原文说不接单不空驶，则两者都包含。

不要只写 take_order。

7.2 ConstraintEvaluator 标注 overlap

Candidate facts 中应有：

action_interval.start_minute
action_interval.end_minute

Evaluator 判断：

candidate interval 与 forbidden time_window 是否 overlap

如果 overlap：

soft_risk_reasons 或 hard_invalid_reasons

并记录：

{
  "constraint_type": "forbid_action_in_time_window",
  "risk_code": "overlaps_forbidden_time_window",
  "estimated_penalty": 500
}
7.3 生成 wait_until_window_end candidate

如果当前处于 forbidden window，或即将进入 forbidden window，应生成：

wait_until_window_end

候选示例：

{
  "candidate_id": "wait_until_quiet_window_end_xxx",
  "action": "wait",
  "params": {"duration_minutes": 60},
  "source": "constraint_satisfy",
  "facts": {
    "satisfies_constraint_type": "forbid_action_in_time_window",
    "constraint_id": "...",
    "avoids_estimated_penalty": 500,
    "window_end_minute": 1800
  }
}

如果环境单次 wait 最多 60 分钟，则 duration 取：

min(60, window_end - current_minute)

下一步继续生成，直到离开窗口。

8. continuous_rest 修改要求
8.1 Evaluator 使用连续状态

continuous_rest 不能再用当天 wait 累计。

Evaluator 应使用：

max_rest_streak_today
current_rest_streak_minutes
remaining_rest_minutes

如果 take_order / reposition 会打断当前 rest streak，并且当天还未满足要求，应标注：

{
  "constraint_type": "continuous_rest",
  "risk_code": "breaks_or_delays_continuous_rest",
  "estimated_penalty": 300,
  "current_rest_streak_minutes": 120,
  "required_minutes": 480,
  "remaining_rest_minutes": 360
}
8.2 生成 continue_rest candidate

如果今天还没满足 continuous_rest，应生成：

continue_rest

候选：

{
  "candidate_id": "continue_rest_<constraint_id>",
  "action": "wait",
  "params": {"duration_minutes": 60},
  "source": "constraint_satisfy",
  "facts": {
    "satisfies_constraint_type": "continuous_rest",
    "constraint_id": "...",
    "current_rest_streak_minutes": 120,
    "required_minutes": 480,
    "remaining_rest_minutes_after_wait": 300,
    "avoids_estimated_penalty": 300
  }
}

注意：

Python 不强制选择 continue_rest。
Advisor 自己选择。
9. specific_cargo 修改要求
9.1 不可见时不生成假 take_order

如果 ConstraintSpec.constraint_type == specific_cargo，并且目标 cargo 当前不可见：

不要生成 take_order candidate

只在 runtime/context 中记录：

{
  "specific_cargo": {
    "target_cargo_ids": ["240646"],
    "visible_target_cargo_ids": [],
    "missing_target_cargo_ids": ["240646"]
  }
}
9.2 可见时生成完整候选

如果目标 cargo 当前 visible：

生成完整 Candidate

候选必须包含：

cargo_id
price
pickup location
destination location
pickup_minutes
deadline
estimated_net
penalty_if_missed

候选 source：

constraint_satisfy

candidate_id：

specific_cargo_<cargo_id>

或者复用 take_order candidate，并在 facts 中加入：

{
  "satisfies_constraint_type": "specific_cargo",
  "penalty_if_missed": 10000
}

不要重复生成两个完全一样的候选，避免 Advisor 混乱。

10. ordered_steps 修改要求
10.1 只实现 next-step candidate

不要恢复 MissionExecutor。

ordered_steps 只做：

识别当前下一步
生成下一步候选
10.2 支持的 step_type

先支持：

visit_location
stay_duration
stay_until
take_specific_cargo
10.3 step progress 判断

基于历史动作和当前位置判断：

visit_location 是否已到达
stay_duration 是否已停留足够
take_specific_cargo 是否已接

先做最小版本，不追求完美。

10.4 候选生成
visit_location

生成：

{
  "candidate_id": "ordered_step_visit_<constraint_id>_<step_index>",
  "action": "reposition",
  "params": {"latitude": ..., "longitude": ...},
  "source": "constraint_satisfy",
  "facts": {
    "satisfies_constraint_type": "ordered_steps",
    "step_type": "visit_location",
    "penalty_if_missed": 9000
  }
}
stay_duration / stay_until

如果当前已在目标点附近，生成：

{
  "candidate_id": "ordered_step_stay_<constraint_id>_<step_index>",
  "action": "wait",
  "params": {"duration_minutes": 60},
  "source": "constraint_satisfy",
  "facts": {
    "satisfies_constraint_type": "ordered_steps",
    "step_type": "stay_duration"
  }
}
take_specific_cargo

如果 cargo visible，生成：

{
  "candidate_id": "ordered_step_cargo_<cargo_id>",
  "action": "take_order",
  "params": {"cargo_id": "..."},
  "source": "constraint_satisfy",
  "facts": {
    "satisfies_constraint_type": "ordered_steps",
    "step_type": "take_specific_cargo"
  }
}
11. be_at_location_by_deadline 修改要求

如果存在：

每天 23 点前到家
某时间前到某地

编译成：

be_at_location_by_deadline

如果 deadline 接近且当前不在目标点附近，应生成：

go_to_required_location candidate

候选：

{
  "candidate_id": "go_to_location_by_deadline_<constraint_id>",
  "action": "reposition",
  "params": {"latitude": ..., "longitude": ...},
  "source": "constraint_satisfy",
  "facts": {
    "satisfies_constraint_type": "be_at_location_by_deadline",
    "deadline_minute": ...,
    "penalty_if_missed": 900
  }
}

不要强制回家，只生成候选。

12. Advisor 输入调整

Advisor 需要看到 satisfy candidate 的价值。

对于每个 candidate，传入：

estimated_net
estimated_penalty_exposure
estimated_net_after_penalty
satisfies_constraints
constraint_impacts
source

特别是 wait/reposition candidates，必须告诉 Advisor：

它能避免什么罚分
它能推进哪个约束
如果不选会有什么后果

否则 Advisor 会继续偏向接单。

Prompt 中加入：

Some wait/reposition candidates are not idle actions; they may satisfy constraints and avoid penalties.
Compare order profit against penalty exposure and penalty avoidance.
Choose the candidate with the best expected net outcome, not simply the highest immediate freight income.
13. 日志要求

每步记录：

{
  "driver_id": "D010",
  "step": 120,
  "day": 10,
  "minute": 600,
  "candidate_count": 40,
  "valid_count": 20,
  "soft_risk_count": 10,
  "satisfy_candidate_count": 3,
  "satisfy_candidate_types": [
    "continuous_rest",
    "forbid_action_in_time_window",
    "ordered_steps"
  ],
  "selected_candidate_id": "...",
  "selected_action": "...",
  "selected_source": "constraint_satisfy",
  "selected_satisfies_constraints": ["..."],
  "estimated_penalty_exposure": 0,
  "estimated_net_after_penalty": 1200
}

注意：日志不要影响决策。

14. 优先级

建议按顺序实现：

P0 continuous_rest
P1 forbid_action_in_time_window
P2 specific_cargo
P3 be_at_location_by_deadline
P4 ordered_steps

原因：

continuous_rest 和 forbid_action_in_time_window 最通用，影响多个司机；
specific_cargo 实现简单且有高额罚分；
be_at_location_by_deadline 和 ordered_steps 稍复杂，后做。
15. 验收标准
15.1 架构验收
1. 不恢复 MissionExecutor / Replanner
2. 不写 driver_id 特化
3. 不写公开数据 cargo_id 特化
4. ConstraintRuntimeState 只提供状态，不决策
5. Satisfy candidates 只进入候选池，不强制执行
6. Advisor 仍然只选择 candidate_id
7. SafetyGate 仍然只做硬合法校验
15.2 行为验收
1. continuous_rest 罚分下降
2. quiet/no-drive window 罚分下降
3. wait/reposition satisfy candidates 出现在日志中
4. specific_cargo 可见时有完整候选
5. ordered_steps 至少能生成下一步候选
6. gross income 不应归零
7. 总净收益应高于当前约 9w baseline
15.3 测试司机

优先测试：

D001: continuous_rest + area
D003/D005/D007: forbid_action_in_time_window
D009: specific_cargo + home/time window
D010: ordered_steps + continuous_rest
16. 完成后请输出总结

请输出：

1. 修改了哪些文件
2. 新增了哪些 runtime state
3. continuous_rest 是否使用连续 streak
4. wait_until_window_end 是否生成
5. specific_cargo 不可见时是否不再生成假 take_order
6. specific_cargo 可见时是否生成完整候选
7. ordered_steps 是否只生成 next-step candidate
8. Advisor 输入是否包含 satisfy candidate 的 penalty avoidance
9. D001/D003/D007/D009/D010 测试结果
10. 总分、gross、penalty 的变化
17. 最终原则

Phase 2.2 不是回到规则系统。

正确方式：

Python 维护动态状态
Python 生成满足候选
Python 标注风险和罚分暴露
Advisor 选择 candidate_id
SafetyGate 拦截硬非法

错误方式：

if rule.kind == "daily_rest": return wait()
if rule.kind == "home": return reposition()
if driver_id == "D009": ...

保持 agentic。


## 注意事项：
Python 维护动态状态、Python 生成满足候选、Python 标注风险和罚分暴露：
这三句话如果做过头，就会变回规则系统。

但它们本身不一定是错的，关键在于 Python 做的是“世界建模”，还是“动作决策”。

你质疑的这三句是：

Python 维护动态状态
Python 生成满足候选
Python 标注风险和罚分暴露

它们应该这样理解。

1. Python 维护动态状态：这是事实，不是决策

比如司机今天有没有连续休息够 8 小时，这不是策略判断，而是事实统计。

Python 可以算：

今天最长连续 wait = 120 分钟
当前连续 wait = 60 分钟
目标连续休息 = 480 分钟
还差 360 分钟

这就像算：

当前位置
当前时间
已跑距离
已接订单数

它不是在决定“必须休息”，只是告诉 Advisor：

如果现在继续接单，会打断当前 60 分钟休息 streak；
如果继续 wait，可以把 streak 增加到 120 分钟。

所以 状态计算可以由 Python 做，否则 LLM 每一步都要从历史动作里自己推理，成本高而且容易错。

2. Python 生成满足候选：这一步最容易变味，要非常小心

你担心的核心就在这里。

如果 Python 这样做：

if rest_not_enough:
    return wait()

这就是规则系统。

但如果 Python 只是生成一个候选：

{
  "candidate_id": "continue_rest_60",
  "action": "wait",
  "params": {"duration_minutes": 60},
  "facts": {
    "effect": "current_rest_streak 60 -> 120",
    "remaining_rest_after": 360,
    "may_reduce_penalty": 300
  }
}

同时还生成其他候选：

take_order_123
take_order_456
wait_60
continue_rest_60
go_home_candidate

然后交给 Advisor 选，这仍然是 Agentic。

区别是：

规则系统：Python 决定做什么
Agentic 系统：Python 提供可做什么，以及每个选择的后果

所以“生成满足候选”不是让 Python 决策，而是为了避免 Advisor 看不到可行方案。

如果没有 continue_rest 候选，Advisor 只能看到：

take_order 有钱
wait 没说明价值

那它当然会一直接单。

3. Python 标注风险和罚分暴露：也是事实估计，不是决策

Python 可以标：

{
  "candidate_id": "take_order_123",
  "risk": "overlaps_forbidden_time_window",
  "estimated_penalty": 500,
  "estimated_net": 1800,
  "estimated_net_after_penalty": 1300
}

这不是 Python 在说“不许接”。

真正的决策应该是 Advisor 做：

这个订单赚 1800，可能罚 500，净后仍然 1300，可以接。

或者：

这个订单赚 400，可能罚 1000，不值得接。

如果 Python 看到 penalty 就直接过滤，那就是规则系统。
如果 Python 只是把 penalty 暴露出来，那是 Agentic 决策所需的事实。

关键边界：Python 只能做“候选生成 + 后果评估”，不能做“选择”

你可以用这张表判断。

行为	可以吗	原因
计算连续休息时长	可以	事实统计
计算订单是否跨过禁行窗口	可以	时间区间计算
估算可能罚分	可以	后果评估
生成 wait_rest 候选	可以，但要谨慎	提供可选方案
生成 go_home 候选	可以，但要谨慎	提供可选方案
因为没休够直接 wait	不可以	Python 做决策
因为要回家直接 reposition	不可以	Python 做决策
因为 soft risk 删除订单	不可以	Python 做策略取舍
因为 penalty > profit 直接过滤	一般不可以	这是 trade-off，应给 Advisor
hard invalid 过滤	可以	接口/物理不可能
那为什么还要 Python 生成候选？

因为 Advisor 只能从候选里选。
如果候选池只有：

take_order
wait_60

而没有：

continue_rest
wait_until_window_end
go_home_before_deadline

Advisor 就很难知道 wait/reposition 的价值。

比如：

wait_60

这很弱。

但：

continue_rest_60
- 当前连续休息 120 -> 180
- 还差 300
- 如果现在接单，今天大概率罚 300

这就变成有意义的行动选项。

所以 Python 生成满足候选，本质上是：

把偏好目标翻译成可行动选项

不是：

替 Advisor 执行动作
怎么防止它滑回规则系统？

我建议在文档里把这几条写死。

规则 1：所有 satisfy candidate 必须和普通候选一起给 Advisor

禁止：

if rest_not_enough:
    return continue_rest_candidate

必须：

candidates = take_order_candidates + wait_candidates + satisfy_candidates
advisor.choose(candidates)
规则 2：soft risk 永远不能被 Python 删除

可以标：

soft_risk_reasons = ["quiet_window_overlap"]
estimated_penalty = 500

不能：

if quiet_window_overlap:
    remove_candidate()

除非它是 hard constraint。

规则 3：Python 不能用 estimated_net_after_penalty 直接选最终动作

可以排序候选给 Advisor 看：

sort by estimated_net_after_penalty

不能直接：

return max(candidates, key=estimated_net_after_penalty)

除非你明确引入“低风险直通”作为工程优化，但那就不是纯 agentic 了，需要单独开关。

规则 4：SafetyGate 不处理 soft preference

SafetyGate 只管：

cargo visible
load window reachable
action schema
wait duration
coordinate valid

不管：

休息没够
夜间偏好
回家偏好
任务偏好
更准确的表述应该改成这样

你刚才觉得不对的三句话，我建议改成：

原句：

Python 维护动态状态
Python 生成满足候选
Python 标注风险和罚分暴露

改成更严谨的：

Python 维护可验证的事实状态；
Python 将偏好约束翻译为可选候选，而不是直接执行；
Python 标注每个候选的约束影响和潜在罚分，但不做 soft-risk 取舍；
Advisor 在所有候选之间做最终 trade-off。

这就不会听起来像规则系统。

一个具体例子

司机偏好：

每天 23:00-04:00 不接单不空驶，违约罚 500

当前时间 22:30，有一个订单：

22:30 开始，预计 02:00 完成，赚 3000

Python 不应该说：

if overlaps_23_04:
    wait()

Python 应该生成：

[
  {
    "candidate_id": "take_order_123",
    "action": "take_order",
    "facts": {
      "estimated_net": 3000,
      "constraint_impacts": [
        {
          "type": "forbid_action_in_time_window",
          "risk": "overlap_23_04",
          "estimated_penalty": 500
        }
      ],
      "estimated_net_after_penalty": 2500
    }
  },
  {
    "candidate_id": "wait_until_04",
    "action": "wait",
    "facts": {
      "avoids_estimated_penalty": 500,
      "opportunity_cost": "may miss current cargo"
    }
  }
]

Advisor 可能选择接单，因为：

赚 3000，罚 500，净后仍高

这就是 Agentic trade-off。

如果订单只赚 300，罚 500，Advisor 可能选择 wait。

这才是你想要的系统。