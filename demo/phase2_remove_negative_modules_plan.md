# Phase 2：移除负作用模块与中度精简主流程计划

## 0. 背景

当前项目已经经历了 Phase 1 和 Phase 1.5 的多轮改造，但实际效果并不好：

```text
1. 代码越来越多
2. 模块越来越复杂
3. 候选结构越来越混乱
4. 每次修改都在新增适配层，而不是减少复杂度
5. Python 决策权仍然会反复抢回 Advisor 的决策权
6. fallback 被限制后，系统又变成大量 wait
7. 最新结果出现 gross_income = 0、动作几乎全 wait、D009/D010 固定任务罚分
```
当前最大问题不是缺少功能，而是：

功能太多，但每个模块都在做一点决策。

现在主流程里同时存在：

Planner / CandidateFactBuilder
CandidateSafetyFilter / CandidateGrouper
FactCollector
MissionExecutor
MissionReplanner
LlmMissionPlanner
TaskGraphBuilder
SafetyGate
ActionContract
Fallback
Advisor

这些模块本来各自都有作用，但组合起来会造成：

1. Advisor 看不到完整候选
2. soft risk 被提前过滤
3. mission 逻辑打回 Advisor 选择
4. fallback 接管或全 wait
5. SafetyGate 拒绝 soft risk
6. 候选类型不统一
7. 日志和主流程不断崩溃

所以本阶段不是继续修补旧框架，而是：

从主流程中移除当前负作用明显的模块，只保留必要链路。
1. Phase 2 总目标

本阶段不是极端推翻重写，而是 中度精简。

目标主流程：

ModelDecisionService
  -> PreferenceCompiler
  -> CandidateFactBuilder
  -> 简单分组 valid / soft_risk / hard_invalid
  -> LlmDecisionAdvisor 选择 candidate_id
  -> SafetyGate 只做硬校验
  -> 返回动作

只保留核心职责：

PreferenceCompiler:
  偏好文本 -> 结构化约束

CandidateFactBuilder:
  当前状态 + 货源 + 约束 -> 统一候选事实

LlmDecisionAdvisor:
  从候选中选择 candidate_id

SafetyGate:
  校验动作是否能提交给仿真接口

ModelDecisionService:
  编排主流程

其他模块先不删除文件，但必须从主流程中断开调用。

2. 本阶段最重要原则
2.1 先弃用，不物理删除

为了避免 import 崩溃，本阶段先不要直接删除文件。

采用：

保留文件，但主流程不再调用。

也就是：

先断开调用，再观察是否还有依赖，最后再决定是否删除。
2.2 不再新增适配层

禁止继续新增这些中间结构：

CandidateView
AdvisorCandidate
FilteredCandidates
BlockedCandidate 兼容层
MissionReplanResult
更多 fallback reason 层
更多 mission lock 层

当前已经太复杂。
本阶段应该减少结构，而不是继续加结构。

2.3 Advisor 是唯一策略主脑

Python 不允许在 Advisor 之前做以下事情：

1. 选择接哪个订单
2. 选择是否等待
3. 选择是否移动
4. 判断 soft risk 值不值得冒
5. 判断 mission 是否值得牺牲收益
6. 因为 budget pressure / rest pressure / wait_streak 直接返回动作

Python 只允许：

1. 构造候选
2. 标注 hard invalid
3. 标注 soft risk
4. 校验接口合法
5. 记录日志
2.4 先恢复基本行为

本阶段优先级：

1. 不崩溃
2. 不全 wait
3. 有 take_order
4. gross_income > 0
5. validation_error = 0
6. 日志能看懂
7. 后续再恢复复杂 mission

不要一开始就追求最高分。

3. 当前必须从主流程弃用的模块
3.1 弃用 candidate_safety_filter.py / CandidateGrouper
当前问题

CandidateSafetyFilter 原本用于过滤候选，后来改成 CandidateGrouper。
但是它引入了多套候选结构：

CandidateScore
CandidateView
BlockedCandidate
FilteredCandidates
CandidatePool

结果导致：

1. 字段不统一
2. 日志函数反复兼容旧结构
3. Advisor 只看到部分候选
4. hard / soft 分组在多个模块重复
5. 主流程越来越臃肿
本阶段处理

从主流程中移除：

self._candidate_safety_filter
self._candidate_grouper
CandidateGrouper.apply()
CandidateGrouper.split()
FilteredCandidates
CandidateView
替代方式

由 CandidateFactBuilder 直接输出统一候选：

@dataclass
class Candidate:
    candidate_id: str
    action: str
    params: dict
    source: str
    facts: dict
    hard_invalid_reasons: list[str]
    soft_risk_reasons: list[str]

然后在 ModelDecisionService.decide() 中直接分组：

valid_candidates = [
    c for c in candidates
    if not c.hard_invalid_reasons and not c.soft_risk_reasons
]

soft_risk_candidates = [
    c for c in candidates
    if not c.hard_invalid_reasons and c.soft_risk_reasons
]

hard_invalid_candidates = [
    c for c in candidates
    if c.hard_invalid_reasons
]

不需要单独的 Grouper 模块。

3.2 弃用 mission_executor.py
当前问题

MissionExecutor 名字和职责都容易导致它直接执行动作。
它会和 Advisor 抢最终决策权。

之前日志中已经出现过：

MissionExecutor 输出 reposition
但最终动作不是 reposition

说明它已经成为第二套决策系统。

本阶段处理

从主流程移除：

self._mission_executor
MissionExecutor.execute(...)
mission -> final action
替代方式

后续如果需要 mission，只能生成候选：

mission -> candidate

例如：

Candidate(
    candidate_id="mission_reposition_home",
    action="reposition",
    params={"latitude": 23.1, "longitude": 113.2},
    source="mission",
    facts={"penalty_if_missed": 9000},
    hard_invalid_reasons=[],
    soft_risk_reasons=[],
)

但本阶段第一步可以先不恢复复杂 mission，先保证普通接单链路。

3.3 弃用 mission_replanner.py
当前问题

当前基础链路还没稳定，replanner 会增加二次决策：

mission failed -> replanner -> new action

这会造成：

1. 决策路径更多
2. 日志更难分析
3. Advisor 权限再次被拆分
4. fallback / replanner / advisor 互相冲突
本阶段处理

从主流程移除：

self._mission_replanner
MissionReplanner
request_replan
blocked_report -> replanner
3.4 暂时弃用 llm_mission_planner.py
当前问题

LlmMissionPlanner 是第二个 LLM 决策模块。
它会在 Advisor 之前生成任务计划，导致：

1. 多一次 LLM 输出格式风险
2. 多一套任务 JSON
3. area_bounds 这种约束可能被误判成 mission
4. Advisor 之前已经被另一个 LLM 改写了问题

D001 里出现过：

cannot build mission from rule: kind=area_bounds

这说明任务规划层已经把约束和任务混淆了。

本阶段处理

从主流程移除：

self._mission_planner
LlmMissionPlanner.plan(...)

后续需要任务时，用简单规则生成 candidate，不再使用单独 LLM mission planner。

3.5 暂时弃用 task_graph_builder.py
当前问题

完整任务图是高级能力，但当前主链路还没有跑顺。

TaskGraphBuilder 会引入：

MissionStep
MissionPlan
locked_steps
deadline lock
stay logic
go_to_point logic

当前阶段这些都容易打回普通接单，导致全 wait。

本阶段处理

从主流程移除：

TaskGraphBuilder
build_missions_from_rules
locked_steps
MissionStep

后续需要处理 D009/D010 时，先用简单 mission candidate，不恢复复杂任务图。

3.6 弃用 fact_collector.py
当前问题

FactCollector 收集大量压力字段：

h_press
r_press
b_press
deadlock
over_cons
hard_lock
complex

这些字段看起来是事实，但实际容易触发 Python 策略：

r_press urgent -> wait
budget pressure -> 不接单
deadlock -> fallback
hard_lock -> 拒绝 Advisor 动作
本阶段处理

从主流程移除：

self._fact_collector
FactCollector.collect(...)
facts.to_log_dict()
替代方式

在 ModelDecisionService 中只构造简单 context：

decision_context = {
    "driver_id": driver_id,
    "day": current_day,
    "minute_of_day": minute_of_day,
    "location": current_location,
    "visible_cargo_count": len(items),
    "wait_streak": wait_streak,
    "recent_actions": recent_actions,
    "valid_candidate_count": len(valid_candidates),
    "soft_risk_candidate_count": len(soft_risk_candidates),
    "hard_invalid_candidate_count": len(hard_invalid_candidates),
}
3.7 冻结复杂 ActionContract 修复逻辑
当前问题

如果 ActionContract 只是 schema 标准化，可以保留。
但如果它会修正、替换、fallback 动作，就会增加一层隐式策略。

本阶段处理

只允许 ActionContract 做格式标准化：

wait -> {"action": "wait", "params": {"duration_minutes": X}}
take_order -> {"action": "take_order", "params": {"cargo_id": X}}
reposition -> {"action": "reposition", "params": {"latitude": X, "longitude": Y}}

禁止：

1. 替 Advisor 选择其他 cargo
2. 把 take_order 改成 wait
3. 根据偏好重写动作
4. 根据风险重写动作

如果 ActionContract 里有复杂逻辑，本阶段主流程先绕开，只在返回前做最小 schema normalize。

4. 保留但必须降权的模块
4.1 保留 planner.py，但改成唯一 CandidateFactBuilder
当前问题

planner.py 过去承担了评分、策略、过滤等多种职责。

本阶段要求

将其职责限制为：

当前状态 + 可见货源 + 偏好约束 -> 候选事实

它可以做：

1. 计算距离
2. 计算时间
3. 计算价格
4. 计算成本
5. 判断 remove_time 是否过期
6. 判断 pickup 是否可达
7. 标注 hard invalid
8. 标注 soft risk
9. 生成 wait 候选

它不能做：

1. 选择最终动作
2. 因为 soft risk 删除候选
3. 因为 wait_streak 强制接单
4. 因为 budget_pressure 强制 wait
5. 调用 mission executor
6. 调用 SafetyGate
7. 输出 BlockedCandidate
8. 输出 CandidateView
统一输出

只输出：

@dataclass
class Candidate:
    candidate_id: str
    action: str
    params: dict
    source: str
    facts: dict
    hard_invalid_reasons: list[str]
    soft_risk_reasons: list[str]

禁止继续在新主流程中使用：

CandidateScore
BlockedCandidate
CandidatePool
4.2 保留 preference_compiler.py
职责

只做：

偏好文本 -> 结构化约束
不允许
1. 直接生成动作
2. 直接生成 mission execution step
3. 强制 wait
4. 强制 reposition
5. 把 area_bounds 交给 mission planner
area_bounds 处理

area_bounds 必须作为 constraint：

area_bounds -> location constraint

不是 mission。

4.3 保留 llm_decision_advisor.py
职责

Advisor 是唯一策略主脑。

本阶段要简化 Advisor：

Advisor 只选择 candidate_id
Advisor 不再自由生成 action
输入
{
  "state": {},
  "preferences": [],
  "valid_candidates": [],
  "soft_risk_candidates": [],
  "recent_actions": [],
  "instruction": "Choose exactly one candidate_id."
}
输出
{
  "selected_candidate_id": "take_order_123",
  "reason": "...",
  "accepted_risks": [],
  "rejected_alternatives": []
}
禁止
1. 不要让 Advisor 输出任意 action JSON
2. 不要让 Advisor 编造 cargo_id
3. 不要让 Advisor 选择 hard_invalid candidate

如果 Advisor 输出不存在的 candidate_id，retry 一次。
retry 失败后 fallback wait。

4.4 保留 safety_gate.py，但缩到极窄
职责

SafetyGate 只防 validation error。

只检查：

1. action 是否是 wait / take_order / reposition
2. wait duration 是否合法
3. take_order cargo_id 是否在当前 visible items
4. cargo 是否未过期
5. pickup 是否物理可达
6. reposition 坐标是否合法
不允许检查
1. mission risk
2. daily rest risk
3. budget risk
4. home preference
5. area_bounds soft risk
6. preference penalty
7. 收益是否划算

如果 area_bounds 是明确 hard constraint，可以由 CandidateFactBuilder 标成 hard_invalid，不需要 SafetyGate 再判断。

5. 新主流程设计
5.1 ModelDecisionService.decide() 应该简化为
def decide(driver_id: str) -> dict:
    # 1. observe
    status = api.get_driver_status(driver_id)
    state = state_tracker.build(status)
    items = api.query_cargo(...)
    history = api.query_decision_history(driver_id, -1)

    # 2. compile preference
    preferences = status.get("preferences") or []
    rules = preference_compiler.compile(preferences)

    # 3. build candidates
    candidates = candidate_fact_builder.build(
        state=state,
        items=items,
        rules=rules,
        history=history,
    )

    # 4. simple grouping
    valid_candidates = [...]
    soft_risk_candidates = [...]
    hard_invalid_candidates = [...]

    # 5. if no executable candidate, wait
    executable_candidates = valid_candidates + soft_risk_candidates
    if not executable_candidates:
        return wait_remaining_or_60()

    # 6. advisor chooses candidate_id
    advisor_result = advisor.choose_candidate(
        state=state,
        preferences=preferences,
        valid_candidates=valid_candidates,
        soft_risk_candidates=soft_risk_candidates,
        recent_actions=history,
    )

    # 7. map candidate_id -> candidate
    selected = find_candidate(advisor_result.selected_candidate_id)

    # 8. safety validation
    gate_result = safety_gate.validate(selected, state, items)

    # 9. accepted -> return selected action
    if gate_result.accepted:
        return to_action(selected)

    # 10. retry once
    retry_result = advisor.choose_candidate(..., rejection=gate_result)
    retry_selected = find_candidate(...)
    retry_gate = safety_gate.validate(...)

    if retry_gate.accepted:
        return to_action(retry_selected)

    # 11. final fallback
    return wait_remaining_or_60()
5.2 主流程禁止调用
self._candidate_safety_filter
self._candidate_grouper
self._fact_collector
self._mission_executor
self._mission_replanner
self._mission_planner
self._task_graph_builder
self._action_breaks_mission
self._constrain_advisor_candidates
self._mission_action_is_commitment
复杂 _advisor_trigger gate
6. 候选生成要求
6.1 每一步必须生成 wait 候选

至少：

wait_30
wait_60

这样 Advisor 选择 wait 时是选择已有候选，而不是自由生成。

6.2 每个可见货源生成 take_order 候选

候选格式：

{
  "candidate_id": "take_order_123",
  "action": "take_order",
  "params": {"cargo_id": "123"},
  "source": "cargo",
  "facts": {
    "price": 3000,
    "estimated_cost": 500,
    "estimated_net": 2500,
    "pickup_deadhead_km": 20,
    "haul_distance_km": 200
  },
  "hard_invalid_reasons": [],
  "soft_risk_reasons": []
}
6.3 hard invalid 不进入 Advisor

这些不进入 Advisor：

remove_time_expired
pickup_window_unreachable
cargo_not_visible
invalid_action_schema
6.4 soft risk 必须进入 Advisor

这些必须进入 Advisor：

daily_rest_soft_risk
budget_soft_risk
area_bounds_soft_risk
mission_soft_risk
home_preference_soft_risk

Advisor 决定是否接受。

7. 日志要求

日志也要精简，不要再记录过多字段。

每步记录：

{
  "driver_id": "D001",
  "step": 12,
  "day": 1,
  "minute": 640,
  "visible_cargo_count": 32,
  "candidate_count": 34,
  "valid_count": 12,
  "soft_risk_count": 8,
  "hard_invalid_count": 14,
  "advisor_called": true,
  "selected_candidate_id": "take_order_123",
  "selected_action": "take_order",
  "safety_accepted": true,
  "fallback_used": false,
  "reason": "..."
}

不要让日志函数影响决策。

如果日志失败：

只打印 logger.exception
不能影响 action 返回
8. 本阶段验收标准
8.1 主流程验收
1. ModelDecisionService 主流程不再调用负作用模块
2. CandidateGrouper / CandidateSafetyFilter 不再参与
3. MissionExecutor / MissionReplanner / LlmMissionPlanner 不再参与
4. FactCollector 不再参与
5. Advisor 只选择 candidate_id
6. SafetyGate 只做硬校验
8.2 行为验收
1. 程序跑完 10 个司机
2. validation_error = 0
3. gross_income_all_drivers > 0
4. actions 中出现 take_order
5. 不再全 wait
6. fallback_used 不主导全月动作
8.3 D001 验收
1. D001 出现 take_order
2. D001 gross_income > 0
3. D001 不再因为 area_bounds 全 wait
8.4 D009 / D010 暂时验收

本阶段可以不完全解决 D009 / D010。
但不能因为 mission 系统导致所有司机全 wait。

后续再单独恢复简单 mission candidate。

9. 修改顺序
Step 1：改 ModelDecisionService

目标：

主流程断开负作用模块。

先不要删除文件，只是不调用。

Step 2：改 planner.py

目标：

输出统一 Candidate。

不再输出 CandidateScore / CandidateView / BlockedCandidate。

Step 3：改 llm_decision_advisor.py

目标：

Advisor 只选 candidate_id。

不要让 Advisor 自由生成 action。

Step 4：改 safety_gate.py

目标：

只做硬校验。
Step 5：跑 D001

目标：

D001 出现 take_order，gross_income > 0。
Step 6：跑 10 个司机

目标：

总 gross_income > 0，validation_error = 0。
10. 不要做的事
1. 不要继续修 CandidateGrouper
2. 不要继续修 MissionExecutor
3. 不要继续修 MissionReplanner
4. 不要继续修 LlmMissionPlanner
5. 不要继续修 TaskGraphBuilder
6. 不要新增 CandidateView / AdvisorCandidate / FilteredCandidates
7. 不要新增复杂 fallback
8. 不要让 Python 根据 score 直接接单
9. 不要让 Advisor 自由生成 action
10. 不要让 SafetyGate 拒绝 soft risk
11. 完成后请输出总结

请输出：

1. 主流程现在调用了哪些模块
2. 哪些模块已经从主流程弃用
3. Candidate 是否已经统一
4. Advisor 是否只选择 candidate_id
5. SafetyGate 是否只做硬校验
6. D001 是否出现 take_order
7. gross_income 是否大于 0
8. fallback_used 是否下降
9. 是否还有 validation_error
10. 哪些复杂功能暂时没有恢复
12. 最终目标

本阶段不是追求最高分。

本阶段只解决一个问题：

代码太臃肿、模块互相抢权、系统全 wait。

成功标准：

主流程变短；
候选结构统一；
Advisor 真正决策；
SafetyGate 只守门；
系统恢复接单和收入。