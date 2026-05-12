# Phase 1.5：框架瘦身计划

## 0. 背景说明

Phase 1 已经完成了一部分 Agentic 改造，例如：

- 引入了候选分层
- 引入了 structured Advisor output
- 开始区分 `valid_candidates`、`soft_risk_candidates`、`hard_invalid_candidates`
- Qwen3.5-Flash 模型已经可以接入
- 部分场景下 Advisor 开始接受 soft risk

但是当前仍然存在一个核心问题：

> 决策权仍然会从 LLM Advisor 回到 Python。

具体表现包括：

```text
1. fallback 在有候选时直接 take_order，绕过 Advisor
2. CandidateSafetyFilter 仍然在 moved to blocked，可能误杀 soft risk
3. MissionExecutor 直接生成动作，但最终链路又可能不执行，形成多套决策系统打架
4. SafetyGate / Planner / fallback / mission 之间职责重叠
5. Python 中仍存在 recovery、wait、budget、risk 等策略性动作选择
```
Phase 1.5 的目标不是继续加功能，而是瘦身框架、收回权限、简化主流程。
## 详细解释
1. Phase 1.5 总目标

Phase 1.5 的核心目标是：

把整个决策框架简化为：
Observer -> CandidateFactBuilder -> CandidateGrouper -> Advisor -> SafetyGate -> MinimalFallback

也就是：

1. Python 只负责观察事实
2. Python 只负责构造候选事实
3. Python 只负责分组候选
4. Advisor 是唯一策略主脑
5. SafetyGate 只做硬合法校验
6. Fallback 只做异常兜底

最终要达到：

只要存在可执行候选，就必须先交给 Advisor 决策。
Python 不允许在 Advisor 之前直接选择 take_order / wait / reposition。
2. Phase 1.5 不做什么

本阶段不要做以下事情：

1. 不做 Phase 2 的完整任务图重构
2. 不做 Runtime Memory
3. 不做学习系统
4. 不做复杂长期规划器
5. 不新增具体司机特化策略
6. 不新增具体 cargo_id 特化策略
7. 不新增公开数据坐标 / 日期 / 货源规律特化
8. 不继续扩大 SafetyGate 权限
9. 不继续扩大 fallback 权限
10. 不把更多策略写回 Python

本阶段只做一件事：

瘦身框架，明确权责，防止 Python 再次抢回决策权。
3. 改造后的目标主流程

最终主流程应该变成：

1. Observer 获取当前状态、货源、历史、偏好
2. CandidateFactBuilder 生成所有候选动作及事实
3. CandidateGrouper 按 hard_invalid / soft_risk / valid 分组
4. Advisor 查看完整候选池并做策略取舍
5. SafetyGate 校验 Advisor 选择的动作是否合法
6. 如果 SafetyGate 拒绝，把 rejection 反馈给 Advisor 重试一次
7. 如果重试仍失败，MinimalFallback 返回最小安全动作

推荐伪代码：

def decide(driver_id: str):
    observation = observer.observe(driver_id)

    candidates = candidate_fact_builder.build(
        observation=observation,
        preferences=observation.preferences,
        history=observation.history,
    )

    grouped = candidate_grouper.group(candidates)

    advisor_context = build_advisor_context(
        observation=observation,
        valid_candidates=grouped.valid_candidates,
        soft_risk_candidates=grouped.soft_risk_candidates,
        hard_invalid_summary=grouped.hard_invalid_summary,
        recent_rejections=get_recent_rejections(driver_id),
    )

    advisor_result = advisor.decide(advisor_context)

    gate_result = safety_gate.validate(
        action=advisor_result.final_action,
        observation=observation,
        visible_cargo=observation.visible_cargo,
    )

    if gate_result.accepted:
        return gate_result.final_action

    record_rejection(driver_id, gate_result)

    retry_context = build_retry_context(
        original_context=advisor_context,
        rejection=gate_result,
    )

    retry_result = advisor.decide(retry_context)

    retry_gate_result = safety_gate.validate(
        action=retry_result.final_action,
        observation=observation,
        visible_cargo=observation.visible_cargo,
    )

    if retry_gate_result.accepted:
        return retry_gate_result.final_action

    return minimal_fallback.safe_wait(
        reason="safety_rejection_retry_failed"
    )
4. 模块职责重新定义
4.1 Observer
保留职责

Observer 只负责获取事实：

1. 当前司机状态
2. 当前时间
3. 当前坐标
4. 当前可见货源
5. 历史动作
6. 当前偏好
7. 当前任务上下文
8. 最近 SafetyGate rejection
禁止行为

Observer 不允许：

1. 不允许选择动作
2. 不允许过滤 soft risk 货源
3. 不允许根据偏好决定接单或等待
4. 不允许根据 wait_streak 决定动作
5. 不允许根据 budget_pressure 决定动作

Observer 只回答：

现在发生了什么？
4.2 CandidateFactBuilder
目标

将原来的 PlannerScorer 或类似模块降权为：

CandidateFactBuilder

它只负责生成候选动作和对应事实。

应该生成的候选类型

CandidateFactBuilder 至少生成：

1. take_order candidates
2. wait candidates
3. reposition candidates
4. mission candidates

其中：

take_order candidates:
  来源于当前可见货源

wait candidates:
  例如 wait 30 / wait 60 / wait 120

reposition candidates:
  可以是少量通用 reposition 目标，不允许基于公开数据特化

mission candidates:
  来自 MissionContext / MissionCandidateBuilder，不再由 MissionExecutor 直接执行
每个候选必须包含

推荐结构：

{
  "candidate_id": "take_order_C123",
  "source": "cargo",
  "action_type": "take_order",
  "final_action": {
    "type": "take_order",
    "cargo_id": "C123"
  },
  "facts": {
    "price": 4200,
    "pickup_deadhead_km": 12.4,
    "haul_distance_km": 180.0,
    "estimated_gross_income": 4200,
    "estimated_cost": 576,
    "estimated_net_before_penalty": 3624,
    "pickup_arrival_minute": 30120,
    "finish_minute": 30580,
    "can_reach_pickup_window": true,
    "will_finish_before_month_end": true
  },
  "hard_invalid_reasons": [],
  "soft_risk_reasons": [],
  "preference_impacts": [],
  "debug": {
    "builder": "CandidateFactBuilder",
    "sort_key_for_prompt_only": 3624
  }
}
可以做的事

CandidateFactBuilder 可以：

1. 计算距离
2. 计算时间
3. 计算收入
4. 计算成本
5. 计算预估净收益
6. 判断是否物理可达
7. 判断是否会导致 hard invalid
8. 标注 soft risk
9. 标注 preference impact
10. 为 prompt 排序候选
禁止行为

CandidateFactBuilder 不允许：

1. 不允许直接返回最终动作
2. 不允许因为 soft risk 删除候选
3. 不允许因为 preference penalty 删除候选
4. 不允许因为 budget_pressure 返回 wait
5. 不允许因为 wait_streak 强制接单
6. 不允许因为 rule.kind 写策略分支
7. 不允许因为 mission_id 写策略分支
8. 不允许因为 driver_id 写策略分支
9. 不允许因为 cargo_id 写特化策略
10. 不允许根据公开测试数据坐标写 reposition 策略
特别注意

如果一个候选：

物理上可执行，但可能带来偏好罚分

它必须保留为：

soft_risk_candidate

不能删除。

4.3 CandidateGrouper
目标

将原来的 CandidateSafetyFilter 降权或改名为：

CandidateGrouper

它只负责分组，不负责过滤策略。

输入
所有候选 candidates
输出
@dataclass
class GroupedCandidates:
    valid_candidates: list
    soft_risk_candidates: list
    hard_invalid_candidates: list
    summary: dict
分组规则
hard_invalid_candidates:
  hard_invalid_reasons 非空

soft_risk_candidates:
  hard_invalid_reasons 为空
  soft_risk_reasons 非空

valid_candidates:
  hard_invalid_reasons 为空
  soft_risk_reasons 为空
CandidateGrouper 可以做
1. 按 hard_invalid_reasons 分组
2. 按 soft_risk_reasons 分组
3. 统计各类候选数量
4. 生成 hard_invalid_summary
5. 生成 soft_risk_summary
6. 截断传给 Advisor 的候选数量
CandidateGrouper 不允许做
1. 不允许调用 SafetyGate
2. 不允许 moved to blocked
3. 不允许删除 soft risk 候选
4. 不允许把 soft risk 变成 hard invalid
5. 不允许返回 wait 动作
6. 不允许替 Advisor 选择候选
7. 不允许根据风险类型做策略取舍
必须删除或禁用的行为

如果当前代码里有：

safety filter: candidates moved to blocked

必须改掉。

新的日志不能再出现：

moved to blocked from risky

除非明确是：

hard_invalid_reasons 非空

并且日志必须写明原因。

推荐日志
{
  "module": "CandidateGrouper",
  "total_candidates": 87,
  "valid_count": 12,
  "soft_risk_count": 35,
  "hard_invalid_count": 40,
  "top_soft_risk_reasons": {
    "finite_budget_soft_risk": 20,
    "daily_rest_soft_penalty": 15
  },
  "top_hard_invalid_reasons": {
    "pickup_window_unreachable": 30,
    "cargo_not_visible": 10
  }
}
4.4 Advisor
目标

Advisor 是唯一策略主脑。

所有收益、风险、偏好、任务、等待机会成本之间的取舍，都应该由 Advisor 决定。

Advisor 输入必须包含
1. 当前司机状态
2. 当前时间
3. 当前坐标
4. 当前可见货源摘要
5. valid_candidates
6. soft_risk_candidates
7. hard_invalid_summary
8. wait_streak
9. budget_status
10. preference_context
11. mission_context
12. recent_safety_rejections
13. recent_actions_summary
Advisor 必须看到 soft risk

如果存在 soft_risk_candidates，Advisor context 中必须包含：

1. top soft risk candidates
2. 每个 soft risk 的 risk_code
3. 每个 soft risk 的 severity
4. 每个 soft risk 的 estimated_penalty，如果有
5. 每个 soft risk 的 estimated_net_before_penalty
6. 是否 hard invalid: false
Advisor 输出 schema
{
  "decision": "choose_candidate",
  "selected_candidate_id": "take_order_C123",
  "policy_mode": "budget_tradeoff",
  "accepted_risks": [
    {
      "risk_code": "finite_budget_soft_risk",
      "reason": "The expected profit is higher than the estimated penalty."
    }
  ],
  "rejected_alternatives": [
    {
      "candidate_id": "wait_60",
      "reason": "Waiting will not restore the monthly budget."
    }
  ],
  "wait_rationale": null,
  "safety_notes": [],
  "final_action": {
    "type": "take_order",
    "cargo_id": "C123"
  },
  "reason": "Choose this order because it gives the best trade-off between profit and soft budget risk."
}
Advisor prompt 必须强调
1. Hard invalid candidates must never be selected.
2. Soft risk candidates are allowed.
3. Soft risk means trade-off, not prohibition.
4. Monthly cumulative budget does not recover by waiting.
5. Waiting has opportunity cost.
6. If all profitable candidates have soft risk, choose the best trade-off.
7. If choosing wait, explain exactly what will improve after waiting.
8. If waiting will not improve anything, do not keep waiting.
9. If SafetyGate rejected a previous action, do not repeat the same invalid choice.
10. Return ONLY valid JSON.
Advisor 不应该被绕过

只要存在以下任意候选：

1. valid_candidates 非空
2. soft_risk_candidates 非空
3. mission_candidates 非空
4. wait_candidates 非空
5. reposition_candidates 非空

就必须调用 Advisor。

例外只有：

1. LLM API 不可用
2. LLM 输出 JSON 无法解析
3. Advisor 连续失败
4.5 SafetyGate
目标

SafetyGate 必须保留，但只做极窄的硬合法校验。

它只回答：

Advisor 选出的 final_action 能不能提交给仿真接口？
SafetyGate 可以拒绝
1. action type 不合法
2. action schema 不合法
3. cargo_id 不在当前 visible cargo 中
4. cargo 已过 remove_time
5. pickup 时间窗物理不可达
6. finish_time 超出仿真结束时间
7. wait duration 非法
8. reposition 坐标非法
9. 当前司机状态不允许执行该动作
SafetyGate 不允许拒绝
1. 可能产生 soft penalty
2. 可能超过 soft budget
3. 可能影响后续偏好
4. 收益不够高
5. 看起来不划算
6. 等待可能更好
7. daily rest soft risk
8. finite budget soft risk
9. mission soft risk
10. preference soft risk

除非某条偏好被明确标为：

severity = hard

否则不能作为 SafetyGate 拒绝理由。

SafetyGate 禁止行为
1. 不允许静默改成 wait
2. 不允许替 Advisor 选第二好的 cargo
3. 不允许因为 soft risk 改动作
4. 不允许因为不确定改动作
5. 不允许调用 fallback take_order
6. 不允许根据 wait_streak 决策
7. 不允许根据 budget_pressure 决策
SafetyGate 返回结构

通过：

{
  "accepted": true,
  "final_action": {
    "type": "take_order",
    "cargo_id": "C123"
  },
  "warnings": []
}

拒绝：

{
  "accepted": false,
  "rejection_type": "hard_invalid",
  "rejection_code": "cargo_not_visible",
  "rejection_reason": "The selected cargo_id is not in current visible cargo list.",
  "original_action": {
    "type": "take_order",
    "cargo_id": "C123"
  },
  "repair_context": {
    "visible_cargo_count": 72,
    "top_visible_candidate_ids": [
      "take_order_C456",
      "take_order_C789"
    ]
  }
}
4.6 MinimalFallback
目标

Fallback 只能保命，不能赚钱。

它只能在系统异常时兜底，不能在正常候选存在时主动做策略。

允许 fallback 的情况
1. LLM API 调用失败
2. LLM JSON 解析失败
3. Advisor 输出 candidate_id 不存在
4. Advisor 输出 final_action schema 非法
5. SafetyGate 拒绝 Advisor 动作后，重试一次仍失败
6. 没有任何可提交动作
Fallback 允许的动作

默认只允许：

wait 30
wait 60

除非仿真接口要求必须返回其他动作，否则 fallback 不应该主动：

take_order
reposition
Fallback 禁止行为
1. 不允许从 valid_candidates 中选最高分订单
2. 不允许从 soft_risk_candidates 中选最高收益订单
3. 不允许主动 take_order
4. 不允许主动 reposition
5. 不允许根据 score 做策略
6. 不允许根据 budget_pressure 做策略
7. 不允许根据 wait_streak 做策略
必须记录 fallback_reason

每次 fallback 必须记录：

{
  "fallback_used": true,
  "fallback_reason": "llm_json_parse_failed",
  "fallback_action": {
    "type": "wait",
    "duration_minutes": 60
  }
}

允许的 fallback_reason：

llm_api_failed
llm_json_parse_failed
advisor_invalid_candidate
advisor_invalid_action_schema
safety_rejection_retry_failed
no_submitable_action
unexpected_exception

禁止出现：

fallback_reason = has_valid_candidate
fallback_reason = best_score_candidate
fallback_reason = budget_pressure
fallback_reason = no_safe_candidate_but_soft_risk_exists
5. 需要删除、降权或合并的模块
5.1 fallback_from_candidates
处理建议

强烈降权，或者删除。

原因

它最容易绕过 Advisor。

必须改

如果当前存在类似：

if valid_candidates:
    return fallback_from_candidates(valid_candidates)

必须删除。

改成：

if valid_candidates or soft_risk_candidates:
    advisor_result = advisor.decide(context)
禁止
不允许 fallback_from_candidates 主动 take_order。
5.2 CandidateSafetyFilter
处理建议

改名为：

CandidateGrouper

或合并进 CandidateFactBuilder 后的简单分组函数。

原因

当前它名字里有 SafetyFilter，容易继续过滤候选，导致 soft risk 被误杀。

必须改

从：

filter candidates

改成：

group candidates

禁止再出现：

moved to blocked

除非该候选有明确 hard_invalid_reasons。

5.3 PlannerScorer
处理建议

改名为：

CandidateFactBuilder

如果暂时不方便改名，也要在代码注释中明确：

This class only builds candidate facts. It must not choose final actions.
原因

Scorer 这个名字会诱导后续代码根据 score 直接决策。

必须改

将 score 改成：

sort_key_for_prompt_only

避免 Python 使用它作为最终决策依据。

5.4 MissionExecutor
处理建议

降级为：

MissionCandidateBuilder

或：

MissionContextProvider
原因

MissionExecutor 如果直接输出动作，就会和 Advisor 抢最终决策权。

必须改

从：

mission -> final action

改成：

mission -> mission candidate

推荐候选结构：

{
  "candidate_id": "mission_reposition_visit_point_001",
  "source": "mission",
  "action_type": "reposition",
  "final_action": {
    "type": "reposition",
    "latitude": 23.3,
    "longitude": 113.52
  },
  "facts": {
    "mission_id": "mission_point_4b64d926",
    "mission_step": "go_visit",
    "deadline_minute": 32000,
    "distance_to_target_km": 18.2,
    "mission_priority": "soft"
  },
  "hard_invalid_reasons": [],
  "soft_risk_reasons": [],
  "preference_impacts": []
}
禁止
1. MissionExecutor 不允许直接 return final action
2. MissionExecutor 不允许绕过 Advisor
3. MissionExecutor 不允许强制 reposition
4. MissionExecutor 不允许根据 mission_id 写特化策略
5.5 SafetyGate
处理建议

保留，但极窄化。

必须改

删除所有策略判断，只保留 hard validation。

禁止
1. 禁止因为 soft risk 拒绝
2. 禁止静默改 wait
3. 禁止替 Advisor 修动作
6. 风险类型必须明确 hard / soft

当前一个很大的问题是：

LLM 看到 daily_rest_risk / finite_budget_risk / urgent，就可能误以为是 hard constraint。

因此所有 risk 必须结构化。

6.1 推荐 risk 结构
{
  "risk_code": "finite_budget_soft_risk",
  "severity": "soft",
  "is_hard_invalid": false,
  "estimated_penalty": 300,
  "explanation": "This action may exceed the monthly deadhead budget."
}

如果是 hard：

{
  "risk_code": "pickup_window_unreachable",
  "severity": "hard",
  "is_hard_invalid": true,
  "estimated_penalty": null,
  "explanation": "The driver cannot arrive before the pickup window closes."
}
6.2 禁止模糊字段

不要只写：

daily_rest_risk
budget_risk
urgent_risk
mission_risk

必须写清楚：

severity = hard / soft
is_hard_invalid = true / false
estimated_penalty = number or null
7. area_bounds 的处理原则

如果存在类似：

司机必须在某城市 / 某区域内工作

不要把它当 mission。

7.1 正确归类

area_bounds 应该是：

location constraint

而不是：

mission
7.2 CandidateFactBuilder 应该做

对每个候选判断：

1. pickup 是否在 bounds 内
2. destination 是否在 bounds 内
3. reposition target 是否在 bounds 内
4. 当前动作是否会离开 bounds
7.3 hard / soft 取决于偏好定义

如果偏好明确是硬要求：

{
  "risk_code": "area_bounds_hard_violation",
  "severity": "hard",
  "is_hard_invalid": true
}

如果只是偏好罚分：

{
  "risk_code": "area_bounds_soft_penalty",
  "severity": "soft",
  "is_hard_invalid": false
}
7.4 禁止
1. 不要让 mission_planner 处理 area_bounds
2. 不要出现 cannot build mission from rule: area_bounds
3. 不要让 fallback 绕过 area_bounds
8. wait / budget / recovery 逻辑处理原则

这些信息可以保留，但只能作为 facts 给 Advisor。

8.1 wait_streak

允许：

{
  "wait_streak": 7,
  "advisor_warning": "The driver has waited 7 consecutive times. Waiting again has high opportunity cost."
}

禁止：

if wait_streak > 7:
    return take_order
8.2 budget_status

允许：

{
  "budget_status": "exhausted",
  "advisor_warning": "Monthly cumulative budget does not recover by waiting."
}

禁止：

if budget_status == "exhausted":
    return wait
8.3 recovery

允许：

{
  "recovery_context": {
    "recent_rejections": 2,
    "recent_waits": 5,
    "needs_recovery_decision": true
  }
}

禁止：

if needs_recovery:
    return fallback_take_order()
9. 日志要求

Phase 1.5 必须新增或规范 JSONL 决策日志。

推荐文件：

demo/results/logs/agent_decisions.jsonl

每一步一行 JSON。

9.1 必须记录字段
{
  "driver_id": "D003",
  "step": 35,
  "day": 7,
  "minute_of_day": 460,

  "visible_cargo_count": 82,
  "total_candidate_count": 87,
  "valid_candidate_count": 12,
  "soft_risk_candidate_count": 35,
  "hard_invalid_candidate_count": 40,

  "top_soft_risk_reasons": {
    "finite_budget_soft_risk": 20,
    "daily_rest_soft_penalty": 15
  },
  "top_hard_invalid_reasons": {
    "pickup_window_unreachable": 30
  },

  "advisor_called": true,
  "advisor_model": "qwen/qwen3.5-flash-02-23",
  "advisor_policy_mode": "budget_tradeoff",
  "advisor_selected_candidate_id": "take_order_C123",
  "advisor_accepted_risks": [
    "finite_budget_soft_risk"
  ],
  "advisor_rejected_alternatives": [
    "wait_60",
    "take_order_C456"
  ],
  "advisor_wait_rationale": null,

  "safety_gate_accepted": true,
  "safety_rejection_code": null,

  "fallback_used": false,
  "fallback_reason": null,

  "final_action": {
    "type": "take_order",
    "cargo_id": "C123"
  },

  "llm_prompt_tokens": 1200,
  "llm_completion_tokens": 300,
  "llm_reasoning_tokens": 0,
  "llm_json_parse_ok": true
}
9.2 必须能从日志看出
1. Advisor 有没有被调用
2. fallback 有没有绕过 Advisor
3. soft risk 有没有进入 Advisor
4. SafetyGate 有没有拒绝
5. SafetyGate 有没有静默改动作
6. wait 是否有 rationale
7. final_action 来源是什么
9.3 禁止日志模糊

不要只记录：

final action source=fallback action=take_order

必须记录：

为什么 fallback？
为什么没有调用 Advisor？
是否存在 valid / soft_risk candidates？
10. 必须全局搜索并处理的关键词

请运行：

rg "fallback_from_candidates|fallback_take_order|source=fallback|moved to blocked|CandidateSafetyFilter|PlannerScorer|MissionExecutor|wait_streak|budget_pressure|rule.kind|mission_id|driver_id|cargo_id|force_|hard daily|urgent rest|daily_rest_risk|finite_budget_risk" demo/agent

对结果按下面规则处理：

10.1 可以保留
1. 日志字段
2. candidate facts
3. advisor context
4. hard validation
5. soft risk 标注
10.2 必须删除或降权
1. 直接 return action
2. 直接 return wait
3. 直接 return take_order
4. 直接过滤 soft risk
5. 根据 rule.kind 决策
6. 根据 mission_id 决策
7. 根据 driver_id / cargo_id 特化
8. fallback 主动选择候选
11. Phase 1.5 验收标准
11.1 架构验收

必须满足：

1. 有候选时必须调用 Advisor
2. fallback 不再主动 take_order
3. CandidateSafetyFilter 不再过滤 soft risk
4. CandidateGrouper 只分组，不决策
5. PlannerScorer 降权为 CandidateFactBuilder
6. MissionExecutor 不再直接输出最终动作
7. Mission 只作为候选进入 Advisor
8. SafetyGate 不再静默改 wait
9. SafetyGate 只拒绝 hard invalid
10. ModelDecisionService 只编排，不做策略
11.2 行为验收

必须满足：

1. 日志中不应再出现有候选却 source=fallback action=take_order
2. 日志中不应再出现 soft risk moved to blocked
3. Advisor 能看到 soft_risk_candidates
4. Advisor 选择 soft risk 时会写 accepted_risks
5. Advisor 选择 wait 时会写 wait_rationale
6. SafetyGate 拒绝后会 retry Advisor 一次
7. retry 失败后才 fallback
8. fallback 默认只能 wait
11.3 日志验收

每一步必须能回答：

1. 当前有多少候选？
2. 有多少 valid？
3. 有多少 soft risk？
4. 有多少 hard invalid？
5. Advisor 是否被调用？
6. Advisor 选了哪个 candidate？
7. SafetyGate 是否接受？
8. 是否用了 fallback？
9. final action 来源是什么？
10. 为什么最终是这个动作？
12. 建议修改顺序

请按顺序执行，不要一次性全改乱。

Step 1：禁用 fallback 主动赚钱

目标：

fallback 不能主动 take_order
有候选必须调用 Advisor

优先修改：

demo/agent/model_decision_service.py
fallback 相关文件

验收：

不再出现 source=fallback action=take_order，除非明确是 LLM 完全失败且没有其他选择。
Step 2：CandidateSafetyFilter 改成 CandidateGrouper

目标：

只分组，不过滤 soft risk

优先修改：

demo/agent/candidate_safety_filter.py

建议重命名：

candidate_grouper.py

如果不方便重命名，也要在代码注释中明确：

This module groups candidates only. It must not filter soft-risk candidates.
Step 3：PlannerScorer 降权为 CandidateFactBuilder

目标：

只构造候选事实，不做策略

优先修改：

demo/agent/planner.py

建议：

score -> sort_key_for_prompt_only

禁止根据 score 直接选动作。

Step 4：MissionExecutor 降级

目标：

mission -> mission candidate

优先修改：

demo/agent/mission_executor.py
demo/agent/model_decision_service.py

如果短期不好改，至少做到：

MissionExecutor 的 action 不直接返回，只注入候选池。
Step 5：SafetyGate 极窄化

目标：

只做硬校验，不做策略

优先修改：

demo/agent/safety_gate.py

验收：

SafetyGate 不再因为 soft risk 拒绝。
SafetyGate 不再静默改 wait。
Step 6：补 JSONL 决策日志

目标：

后续能清楚分析每一步决策。

优先修改：

demo/agent/model_decision_service.py
日志工具文件
13. 建议 commit 顺序
git checkout -b phase1-5-framework-slimming

git add demo/agent/model_decision_service.py
git commit -m "phase1.5: require advisor before fallback"

git add demo/agent/candidate_safety_filter.py
git commit -m "phase1.5: convert safety filter into candidate grouper"

git add demo/agent/planner.py
git commit -m "phase1.5: slim planner into candidate fact builder"

git add demo/agent/mission_executor.py demo/agent/model_decision_service.py
git commit -m "phase1.5: emit mission actions as advisor candidates"

git add demo/agent/safety_gate.py
git commit -m "phase1.5: narrow safety gate to hard validation"

git add demo/agent/model_decision_service.py
git commit -m "phase1.5: add structured agent decision jsonl logs"
14. 改完后请输出总结

完成 Phase 1.5 后，请输出：

1. 修改了哪些文件
2. 删除或降权了哪些模块
3. fallback 是否还会主动 take_order
4. CandidateSafetyFilter 是否已改成只分组
5. soft_risk_candidates 是否一定进入 Advisor
6. MissionExecutor 是否还会直接输出最终动作
7. SafetyGate 是否还会静默改 wait
8. SafetyGate 是否还会拒绝 soft risk
9. 新增了哪些 JSONL 日志字段
10. 如何运行仿真测试
11. 当前仍然存在的风险
15. 最终判断标准

Phase 1.5 成功的标准不是收益立刻最高，而是：

Python 不再抢方向盘。

更具体地说：

1. Python 可以构造事实
2. Python 可以标注 hard / soft risk
3. Python 可以拒绝非法动作
4. Python 不能替 Advisor 做收益/偏好/风险取舍
5. Python 不能在 Advisor 之前直接接单
6. Python 不能因为 soft risk 删除候选
7. Python 不能把 Advisor 的动作静默改成 wait

一句话：

Fallback 只能保命，不能赚钱。
CandidateGrouper 只能分组，不能过滤。
SafetyGate 只能守门，不能开车。
MissionExecutor 只能产出任务候选，不能直接驾驶。
Advisor 才是唯一策略主脑。