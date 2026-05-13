# Phase 2.2 Bugfix：修复 rest 候选误导与 hard_invalid 过多问题

## 0. 当前问题背景

当前项目已经进入 Phase 2.2：

```text
Dynamic Constraint State & Satisfy Candidate Generator
```
目标是保持 agentic 主流程：

PreferenceCompiler
-> ConstraintSpec
-> CandidateFactBuilder
-> ConstraintEvaluator
-> Advisor choose candidate_id
-> SafetyGate hard validation

同时增加：

动态约束状态
满足约束的候选
约束影响与罚分暴露

但是最新代码和结果出现了明显异常：

D001 会在每天前半段优先选择 wait_rest_480 / rest 候选
等休息似乎满足后，后半段才开始接单
整体收入很低或几乎没有收入

这个行为不是合理的 agentic trade-off，而是候选生成和 continuous_rest 风险建模出现了问题。

1. 当前异常现象

从最新日志看，D001 多步出现类似情况：

visible_cargo_count 很多
candidate_count 很多
hard_invalid_count 接近全部货源数量
valid_count 很少
selected_candidate_id = wait_rest_480
selected_action = wait

典型表现：

可见货源几十个甚至上百个
但大量 cargo candidates 被标为 hard_invalid
Advisor 看到的可选候选主要是 wait / rest
于是反复选择 wait_rest_480

这导致系统行为变成：

每天先休息
休息一段时间后再接单
收入下降

这不是设计目标。

正确目标应该是：

如果当前有高收益订单，且接完后今天仍然有足够时间完成连续休息，就可以接单；
只有当接单会导致当天无法完成连续休息时，才应明显偏向 rest。
2. 当前问题根因
2.1 wait_rest_480 候选语义错误

当前代码中，continuous_rest 约束会生成类似：

wait_rest_480

但实际动作通常是：

{
  "action": "wait",
  "duration_minutes": 60
}

也就是说：

候选名字表示休息 480 分钟
实际只 wait 60 分钟

更严重的是，候选 facts 中可能写了类似：

satisfies_continuous_rest = true

这会误导 Advisor 认为：

选择这个 wait_rest_480 就能满足 8 小时连续休息

但实际上它只等待 60 分钟，并不一定满足连续休息要求。

正确做法

不要再生成语义模糊的：

wait_rest_480

应该生成更准确的候选：

start_rest_60
continue_rest_60

并明确：

当前连续休息多久
这次 wait 后连续休息多久
还差多久
这次 wait 后是否真正满足 continuous_rest
2.2 continuous_rest 不能用“当天累计 wait”

当前 continuous_rest 可能仍然使用：

today_wait = sum(wait intervals)

这是“当天累计等待时间”。

但评分规则通常要求：

连续停车休息
连续熄火休息
连续休息不少于 X 分钟

累计 wait 与连续 wait 不等价。

例如：

08:00 wait 60
12:00 wait 60
18:00 wait 60

累计 wait 是 180 分钟，但最长连续休息只有 60 分钟。
如果规则要求连续休息 180 分钟，这并不满足。

正确做法

需要维护：

current_rest_streak_minutes
max_rest_streak_today
remaining_rest_minutes

而不是只看当天 wait 总和。

2.3 rest risk 判断过于激进

当前逻辑可能等价于：

今天还没休够
-> 所有 take_order 都有高额 rest risk

这会导致 Advisor 认为：

订单收益 - rest penalty < 0
所以先休息

然后每天就变成：

先休息满，再接单

这不是合理策略。

正确判断方式

对 take_order 候选，应该判断：

如果接这个订单后，今天剩余时间仍然足够完成 required continuous rest，
则不应该给高额 rest risk。

也就是说，rest risk 应该基于：

candidate_finish_minute
day_end_minute
remaining_day_minutes
required_rest_minutes
max_rest_streak_today

而不是简单基于：

当前还没休够

示例逻辑：

if max_rest_streak_today >= required_minutes:
    no rest risk
else:
    finish_minute = candidate.facts.get("finish_minute")
    remaining_day_minutes = day_end_minute - finish_minute

    if remaining_day_minutes >= required_minutes:
        no or low rest risk
    else:
        soft risk: may_fail_continuous_rest_today
2.4 大量货源被 hard_invalid，需要定位原因

日志中出现：

visible_cargo_count 很多
hard_invalid_count 接近全部货源数量

这非常不正常。

可能原因：

1. load_time_window_unreachable 过滤过严
2. remove_time 被错误当作严格装货截止
3. current_minute 与 deadline_minute 时间基准不一致
4. LOAD_WINDOW_BUFFER_MINUTES 过大
5. area_bounds / geometry 判断过严

当前日志只显示 hard_invalid_count，不知道具体原因分布。

因此必须先增加 hard_invalid reason 统计。

3. 本次修复目标

本次目标不是重构主流程，也不是恢复旧 MissionExecutor。

本次只修：

1. rest 候选语义错误
2. continuous_rest 连续状态错误
3. rest risk 过度惩罚订单
4. hard_invalid 过多缺少原因统计

修复后希望达到：

1. D001 不再每天无脑先 wait_rest
2. Advisor 能同时看到真实可接订单和真实 rest 候选
3. rest 候选不会谎称 wait 60 就满足 480
4. rest risk 只在订单会导致当天无法完成连续休息时显著出现
5. hard_invalid_count 过高时能看到具体原因
4. 不要做的事情

本次不要做：

1. 不恢复 MissionExecutor
2. 不恢复 MissionReplanner
3. 不恢复 LlmMissionPlanner
4. 不恢复 TaskGraphBuilder
5. 不让 Python 直接 force wait
6. 不让 Python 直接 force take_order
7. 不让 Python 因为 soft rest risk 删除候选
8. 不写 driver_id 特化
9. 不写公开数据 cargo_id 特化
10. 不大改 Advisor 主流程

Python 只应：

计算状态
生成候选
标注风险
记录日志

Advisor 仍然选择 candidate_id。

5. 需要修改的文件

优先修改：

demo/agent/state_tracker.py
demo/agent/constraint_evaluator.py
demo/agent/planner.py
demo/agent/model_decision_service.py

可能涉及：

demo/agent/agent_models.py
demo/agent/preference_constraints.py
demo/agent/llm_decision_advisor.py
6. 修复方案一：修 rest runtime state
6.1 需要计算的状态

需要在 state 或 runtime context 中提供：

current_rest_streak_minutes
max_rest_streak_today

含义：

current_rest_streak_minutes:
  当前正在连续休息的时长。
  如果最近动作是 wait，并且前面也是连续 wait，则累加。
  如果最近动作是 take_order / reposition，则为 0。

max_rest_streak_today:
  今天最长连续休息时长。
6.2 计算规则

基于当天历史动作：

1. 按时间排序
2. 遇到 wait，累加当前 streak
3. 遇到 take_order / reposition，当前 streak 清零
4. max_rest_streak_today 记录最大 streak
5. 如果最后一段是 wait，current_rest_streak_minutes 等于最后这段连续 wait 总时长

注意：

不能用当天 wait 总和。
7. 修复方案二：重写 continuous_rest 评估
7.1 不再使用累计 wait

在 ConstraintEvaluator 中，禁止使用类似：

today_wait = sum(...)

来判断 continuous_rest 是否满足。

改为使用：

max_rest_streak_today
current_rest_streak_minutes
7.2 对 take_order / reposition 的风险判断

对于会打断休息的候选，例如：

take_order
reposition

判断方式：

required = constraint.required_minutes
max_rest = runtime.max_rest_streak_today

if max_rest >= required:
    no risk
else:
    finish_minute = candidate.facts.get("finish_minute") or candidate.facts.get("action_interval.end_minute")
    day_end = (state.current_day + 1) * 1440
    remaining_after_candidate = day_end - finish_minute

    if remaining_after_candidate >= required:
        no or low risk
    else:
        soft risk: may_fail_continuous_rest_today

也就是说：

接单后今天仍然有足够时间连续休息，就不要给高额 rest risk。
7.3 对 wait candidate 的满足判断

对于 wait candidate：

wait_duration = candidate.params["duration_minutes"]
rest_after_wait = current_rest_streak_minutes + wait_duration

如果：

rest_after_wait >= required_minutes

则：

actually_satisfies_after_this_wait = true

否则：

actually_satisfies_after_this_wait = false

facts 中必须包含：

{
  "current_rest_streak_minutes": 120,
  "max_rest_streak_today": 120,
  "required_minutes": 480,
  "wait_duration": 60,
  "rest_streak_after_wait": 180,
  "remaining_rest_minutes_after_wait": 300,
  "actually_satisfies_after_this_wait": false
}
8. 修复方案三：重命名 rest satisfy candidate
8.1 不再生成 wait_rest_480

不要再生成：

wait_rest_480

因为它暗示这个候选会休息 480 分钟。

8.2 改成 start / continue rest

如果当前没有连续休息：

start_rest_60

如果当前已经在连续休息：

continue_rest_60

示例：

{
  "candidate_id": "continue_rest_60_daily_rest_xxx",
  "action": "wait",
  "params": {
    "duration_minutes": 60
  },
  "source": "constraint_satisfy",
  "facts": {
    "satisfies_constraint_type": "continuous_rest",
    "current_rest_streak_minutes": 180,
    "required_minutes": 480,
    "rest_streak_after_wait": 240,
    "remaining_rest_minutes_after_wait": 240,
    "actually_satisfies_after_this_wait": false,
    "avoids_estimated_penalty": 300
  }
}

只有当这次 wait 后真的满足要求，才可以：

{
  "actually_satisfies_after_this_wait": true
}
9. 修复方案四：避免 rest 候选挤掉订单
9.1 不要把 rest risk 当 hard invalid

continuous_rest 不应导致订单变成 hard_invalid，除非偏好明确是 hard constraint。

通常应作为：

soft_risk

给 Advisor 做 trade-off。

9.2 不要让所有订单都带高额 rest penalty

只有当：

接这个订单后今天无法再完成 required continuous rest

才标显著 rest risk。

否则最多标轻微提示：

rest_still_pending

不要把它当作高额 penalty exposure。

9.3 Advisor 应同时看到订单和 rest

最终候选池应该同时包含：

take_order candidates
start_rest / continue_rest candidates
wait candidates

Advisor 决定。

10. 修复方案五：增加 hard_invalid reason 统计
10.1 当前问题

日志里只有：

{
  "hard_invalid_count": 37
}

但不知道这 37 个为什么 invalid。

这使得无法判断：

是否 load window 过滤过严
是否 area_bounds 过严
是否 geometry 解析错误
10.2 需要新增日志字段

在 agent_decisions.jsonl 中增加：

{
  "top_hard_invalid_reasons": {
    "load_time_window_unreachable": 32,
    "invalid_cargo_geometry": 5
  }
}

同时建议增加 sample：

{
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

sample 不需要很多，3 个即可。

11. 检查 load window 是否过严

如果新增日志后发现：

hard_invalid 主要来自 load_time_window_unreachable

需要检查：

1. remove_time 是否真的应该作为 load deadline
2. parse_time_to_minute 是否与 state.current_minute 同基准
3. arrival_minute 是否计算过大
4. buffer 是否过大

短期可以考虑：

1. 明确 load_time_window_end / pickup_deadline 优先作为 deadline
2. remove_time 只用于判断货源当前是否仍可见
3. 将 buffer 从 5 降为 0 做对比实验

不要盲目把所有接近 deadline 的货源都 hard_invalid。

12. 日志验收

修复后 D001 前 30 步应能看到：

1. visible_cargo_count > 0 时，不应几乎全部 hard_invalid
2. top_hard_invalid_reasons 可解释
3. rest candidate 名称为 start_rest_60 / continue_rest_60
4. rest candidate facts 不再谎称 wait 60 满足 480
5. take_order candidates 仍然进入 Advisor
6. Advisor 不再整天连续选择 rest
13. 行为验收

跑 D001 前 50 步：

1. D001 应出现 take_order
2. gross_income > 0
3. 不应每天前半段固定先 rest 480
4. continuous_rest 使用连续 streak，不是累计 wait
5. validation_error = 0
6. hard_invalid_count 不应无解释地接近 visible_cargo_count

如果仍然大量 wait，需要检查：

1. 是否 take_order 都被 hard_invalid
2. 是否 rest penalty exposure 过大
3. Advisor 是否只看到 wait/rest candidates
14. 不要误解本次修复

本次不是说：

不要考虑休息

而是说：

休息应该作为一个有真实状态、有真实剩余需求、有真实机会成本的候选；
不能用错误 facts 误导 Advisor 每天先休满。

正确逻辑：

如果现在接单后仍有足够时间完成连续休息，可以接单；
如果现在再接单会导致今天无法完成连续休息，rest candidate 应该更有吸引力；
最终由 Advisor 选择。
15. 完成后请输出

请输出：

1. 修改了哪些文件
2. current_rest_streak_minutes 如何计算
3. max_rest_streak_today 如何计算
4. continuous_rest 是否不再使用累计 wait
5. wait_rest_480 是否已删除或重命名
6. start_rest / continue_rest facts 示例
7. top_hard_invalid_reasons 日志示例
8. D001 前 50 步结果
9. 是否仍然出现无收入 / 全 wait
10. 是否发现 load window 过滤过严
16. 最终原则

保持 agentic：

Python 计算状态
Python 生成候选
Python 标注风险
Advisor 选择 candidate_id
SafetyGate 拦截硬非法

不要变成：

if rest_not_enough:
    return wait()

也不要变成：

rest candidate facts 错误，导致 Advisor 被迫 wait