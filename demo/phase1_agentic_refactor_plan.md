Phase 1：止血与收权详细计划
1. Phase 1 的核心目标

当前系统的问题不是没有 Agent，而是 Python 规则层仍然替 LLM 做了太多策略判断。

Phase 1 的目标是先把这些过度硬编码的策略逻辑收回来，让 LLM Advisor 重新获得真实选择空间。

本阶段不追求一次性把架构做完，也不追求立刻把收益拉到最高。
本阶段优先解决这些问题：

1. soft risk 被当成 hard invalid
2. Planner 过度过滤候选
3. CandidateSafetyFilter 过滤太强
4. SafetyGate 静默把动作改成 wait
5. LLM Advisor 看不到完整候选池
6. 连续 wait 死循环
7. 代码里存在大量 rule.kind / mission_id / driver_id 式硬编码策略
8. reason_tokens 为 0 时影响判断或日志解释

Phase 1 完成后的理想状态：

Python 只负责构造事实、硬约束校验、动作合法性检查
LLM Advisor 负责在收益、偏好、风险、等待机会成本之间做取舍
SafetyGate 只拒绝非法动作，不替 Advisor 选策略
2. Phase 1 不做什么

Phase 1 不做以下事情：

1. 不重构完整任务图系统
2. 不做 Runtime Memory
3. 不做复杂长期学习
4. 不新增针对具体司机的特化策略
5. 不新增针对具体 cargo_id 的特化策略
6. 不新增针对公开数据坐标、时间、订单规律的特化策略
7. 不急着把所有 rule.kind 全部删干净
8. 不急着大规模改 preference_compiler
9. 不急着把 MissionExecutor 完全重写

Phase 1 的重点是：

先止血
先减少硬编码
先恢复 Advisor 的选择空间
先让日志能看清楚为什么做这个动作
3. Phase 1 主要改动文件

优先级从高到低：

demo/agent/llm_client.py
demo/agent/llm_decision_advisor.py
demo/agent/model_decision_service.py
demo/agent/planner.py
demo/agent/candidate_safety_filter.py
demo/agent/safety_gate.py

可选涉及：

demo/agent/config.py
demo/server/config.py
.env
demo/agent/types.py
demo/agent/state_tracker.py

其中最核心的是：

planner.py
candidate_safety_filter.py
safety_gate.py
llm_decision_advisor.py
model_decision_service.py
4. Phase 1 总体执行顺序

建议按下面顺序改，不要一起乱改：

Step 1：先切换 / 修正 LLMClient，保证 Qwen3.5-Flash 可以稳定返回 JSON
Step 2：改 Advisor 输出结构，让它不只返回 action
Step 3：改 Planner，把候选从“策略评分”改成“事实构造”
Step 4：改 CandidateSafetyFilter，只过滤 hard invalid
Step 5：改 SafetyGate，不再静默重写策略
Step 6：改 ModelDecisionService，串起新的候选池、Advisor、SafetyGate rejection
Step 7：跑仿真，看日志和收益

原因是：

如果 LLMClient / Advisor 输出不稳定，后面候选池改得再好也没法判断。
如果 Planner 还在删候选，Advisor 就看不到真实选择空间。
如果 SafetyGate 还在静默改 wait，Advisor 的决策就会被吞掉。
5. Step 1：先处理模型切换和 LLMClient
5.1 目标

从当前 Mimo 模型切到推荐的 Qwen3.5-Flash，同时不要再依赖 reason_tokens 判断模型有没有推理。

当前 reason_tokens = 0 不能直接说明模型没有思考，可能只是：

1. provider 不返回 reasoning token
2. 模型不暴露 reasoning 字段
3. 当前请求没有 include_reasoning
4. 当前代码没有读取 reasoning 字段
5. 响应封装时把 reasoning metadata 丢掉了

所以 Phase 1 里要先做到：

reason_tokens 可以为 0
但不能影响 Agent 决策流程
5.2 必须检查的文件
demo/agent/llm_client.py
demo/agent/config.py
demo/server/config.py
.env

如果项目里模型名写在其他位置，也一起检查：

rg "model|MODEL|mimo|qwen|base_url|api_key|reason"
5.3 配置建议

如果走 OpenRouter，可参考：

LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=qwen/qwen3.5-flash-02-23
LLM_API_KEY=你的key

如果走阿里云 / DashScope，就用阿里云平台实际给你的 endpoint 和 model name。

注意：

不要把 API key 写死进代码
不要提交 .env
不要把 config.py 里真实 key 上传 GitHub
5.4 LLMClient 统一返回结构

建议统一封装返回，不要让上层直接依赖 provider 原始字段。

推荐结构：

@dataclass
class LlmResponse:
    content: str
    reasoning_content: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    reasoning_tokens: int | None
    total_tokens: int | None
    raw_model: str | None
    raw_response: dict

上层判断模型是否可用时，不要看：

reasoning_tokens > 0

而是看：

1. content 是否存在
2. JSON 是否可解析
3. Advisor 输出字段是否完整
4. selected_candidate_id 是否存在
5. final_action 是否合法
5.5 Qwen3.5-Flash 请求参数建议

决策类调用建议：

temperature = 0.2
top_p = 0.9
max_tokens = 1500

偏好解析类调用建议：

temperature = 0.1
top_p = 0.9
max_tokens = 1500

任务规划类调用建议：

temperature = 0.2
top_p = 0.9
max_tokens = 2000

如果 provider 支持 JSON 模式，优先使用：

{
  "response_format": {
    "type": "json_object"
  }
}

如果不支持，就在 prompt 里强制：

Return ONLY valid JSON.
Do not use markdown.
Do not include explanations outside JSON.
5.6 Step 1 验收标准

完成后先单独跑一个最小测试，不要直接跑完整仿真。

验收标准：

1. Qwen3.5-Flash 能正常返回
2. content 里能拿到 JSON
3. JSON 能 parse
4. reason_tokens 为 0 时流程不报错
5. 日志记录 model、token、latency、parse_ok
6. API key 没有写死进代码

建议日志字段：

{
  "module": "LlmDecisionAdvisor",
  "model": "qwen/qwen3.5-flash-02-23",
  "prompt_tokens": 1234,
  "completion_tokens": 456,
  "reasoning_tokens": 0,
  "latency_ms": 820,
  "json_parse_ok": true
}
6. Step 2：改 LlmDecisionAdvisor 输出结构
6.1 当前问题

当前 Advisor 如果只输出 action，会导致后面难以判断：

1. 它为什么选这个订单
2. 它是否知道有 soft risk
3. 它有没有比较 wait 的机会成本
4. 它有没有接受某些风险
5. 它为什么没选其他候选
6. 它是否被 SafetyGate 拒绝后学到了

Phase 1 里要先让 Advisor 输出更结构化。

6.2 推荐输出 schema

Advisor 输出建议统一为：

{
  "decision": "choose_candidate",
  "selected_candidate_id": "take_order_C123",
  "policy_mode": "profit",
  "accepted_risks": [],
  "rejected_alternatives": [],
  "wait_rationale": null,
  "safety_notes": [],
  "final_action": {
    "type": "take_order",
    "cargo_id": "C123"
  },
  "reason": "Choose this cargo because it has the best estimated net value and no hard invalid risk."
}

字段说明：

decision:
  choose_candidate | wait | reposition | request_replan | fallback

selected_candidate_id:
  被选中的候选 ID

policy_mode:
  profit | protect_preference | budget_tradeoff | mission | recovery | low_confidence

accepted_risks:
  Advisor 明确接受的 soft risk

rejected_alternatives:
  为什么没选其他主要候选

wait_rationale:
  如果选择 wait，必须说明等待会改善什么

safety_notes:
  对 SafetyGate 的提醒，比如 cargo 必须 visible

final_action:
  最终动作

reason:
  简短解释
6.3 policy_mode 取值建议
profit:
  以净收益为主

protect_preference:
  保护高优先级偏好

budget_tradeoff:
  收益和累计预算/罚分之间做取舍

mission:
  执行任务或 deadline 相关目标

recovery:
  从连续 wait、SafetyGate 拒绝、无候选等异常状态恢复

low_confidence:
  信息不足时的保守决策
6.4 Advisor prompt 必须强调

加入这些硬性要求：

1. Hard invalid actions must never be selected.
2. Soft risk is not forbidden. Compare estimated profit and estimated penalty.
3. Waiting has opportunity cost.
4. If waiting will not improve the situation, do not keep waiting repeatedly.
5. Monthly cumulative budget does not recover by waiting.
6. If all profitable candidates have soft risk, choose the best trade-off instead of defaulting to wait.
7. If SafetyGate rejected a similar action recently, avoid repeating the same invalid action.
8. Return only valid JSON.

中文理解就是：

soft risk 不是不能做
hard invalid 才是真的不能做
wait 不是万能解
等待不能恢复累计预算
6.5 Step 2 禁止行为

不要让 Advisor prompt 里写成：

Avoid all preference risks.
Never violate preference.
When unsure, wait.
Always protect budget.

这些会导致模型过度保守，继续 wait 死循环。

应该改成：

Respect preferences, but soft preference penalties can be traded off against profit.
Only hard constraints are absolute.
6.6 Step 2 验收标准
1. Advisor 输出 JSON 稳定
2. 每次有 selected_candidate_id 或明确 wait/reposition
3. policy_mode 不为空
4. 选择 wait 时 wait_rationale 不为空
5. 有 soft risk 时 accepted_risks 可以记录
6. rejected_alternatives 至少记录 1~3 个主要替代项
7. 不依赖 reason_tokens 判断 Advisor 是否有效
7. Step 3：改 Planner，从策略评分改成事实构造
7.1 当前问题

planner.py 或 PlannerScorer 当前很可能做了太多策略判断，比如：

1. 因为某种 preference risk 直接降低或删除候选
2. 因为 budget pressure 直接倾向 wait
3. 因为 wait_streak 直接决定接单
4. 因为 rule.kind 进入特定策略
5. 因为 mission_id 进入特定执行逻辑

这些都应该逐步收权。

7.2 Phase 1 的目标

Phase 1 不一定要马上把类名改掉。
为了减少改动风险，可以先保留 PlannerScorer 名字，但改变职责。

从：

PlannerScorer = 候选评分 + 策略判断 + 过滤

改成：

PlannerScorer = CandidateFactBuilder = 候选事实构造器

如果后面稳定了，再正式重命名。

7.3 Planner 应该输出什么

每个候选动作都应该带这些事实：

{
  "candidate_id": "take_order_C123",
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
    "will_finish_before_month_end": true,
    "current_location_to_pickup_km": 12.4
  },
  "hard_invalid_reasons": [],
  "soft_risk_reasons": [],
  "preference_impacts": [],
  "debug": {
    "source": "planner",
    "score_used_for_sort_only": 3624
  }
}

注意：

score 可以保留，但只能用于排序展示，不应该直接决定最终动作。
7.4 Planner 可以做的排序

可以保留简单排序，帮助 Advisor 看重点候选：

1. estimated_net_before_penalty 高的排前面
2. pickup_deadhead_km 低的排前面
3. hard_invalid 少的排前面
4. finish_time 合理的排前面

但要注意：

排序不是最终决策
排序不能删除 soft risk 候选
排序不能替 Advisor 做 trade-off
7.5 Planner 必须保留 soft risk 候选

如果一个订单可能导致偏好罚分，但物理上能执行，那么它应该进入：

soft_risk_candidates

而不是直接被删。

例如：

某单可能超过月度空驶预算
但收益很高

这是典型的 LLM trade-off 场景。
不能在 Planner 里直接过滤。

7.6 Planner 里要重点删除 / 降权的逻辑

搜索这些关键词：

rg "rule.kind|mission_id|wait_streak|budget_pressure|home|family|special|force|fallback|penalty|risk|filter|blocked" demo/agent/planner.py

重点检查：

1. 是否根据 rule.kind 决定动作
2. 是否根据 mission_id 决定动作
3. 是否因为 soft penalty 删除候选
4. 是否因为预算压力直接 wait
5. 是否因为等待次数直接选择固定动作
6. 是否对某类偏好写了专门策略

处理方式：

hard invalid 判断：保留
soft risk 判断：改成 soft_risk_reasons
策略取舍判断：交给 Advisor
7.7 Step 3 验收标准
1. Planner 输出候选事实表
2. soft risk 候选没有被删除
3. Planner 不直接决定最终动作
4. Planner 不因为 rule.kind 做策略分支
5. Planner 不因为 budget pressure 直接 wait
6. Planner 日志能显示候选数量、soft risk 数量、hard invalid 数量

建议日志：

{
  "driver_id": "D001",
  "visible_cargo_count": 82,
  "candidate_count": 20,
  "valid_candidate_count": 12,
  "soft_risk_candidate_count": 6,
  "hard_invalid_candidate_count": 2
}
8. Step 4：改 CandidateSafetyFilter，只过滤 hard invalid
8.1 当前问题

CandidateSafetyFilter 如果拿候选动作直接跑 SafetyGate.validate()，然后把被改成 wait 或被拒绝的候选全部 blocked，就可能把 soft risk 候选也过滤掉。

这会导致：

Advisor 看不到高收益但有风险的候选
最后只能 wait 或接低收益单
8.2 改造目标

候选分三类：

valid_candidates
soft_risk_candidates
hard_invalid_candidates

分类标准：

hard_invalid:
  物理不可执行 / 接口非法 / 货源不可见 / 时间窗绝对赶不上 / 坐标非法

soft_risk:
  可能产生偏好罚分 / 可能超过预算 / 可能影响后续任务 / 可能错过偏好窗口

valid:
  没有 hard invalid，也没有明显 soft risk
8.3 CandidateSafetyFilter 不应该做什么

禁止：

1. 不要因为 soft risk 删除候选
2. 不要因为 preference penalty 删除候选
3. 不要因为 budget pressure 删除候选
4. 不要因为 quiet hour 风险直接删除，除非它是 hard constraint
5. 不要因为任务 deadline 风险直接删除，除非必然失败
6. 不要把所有风险候选都 blocked
7. 不要替 Advisor 决定 wait
8.4 推荐输出结构
@dataclass
class FilteredCandidates:
    valid_candidates: list[Candidate]
    soft_risk_candidates: list[Candidate]
    hard_invalid_candidates: list[Candidate]
    summary: dict

summary 示例：

{
  "valid_count": 8,
  "soft_risk_count": 5,
  "hard_invalid_count": 3,
  "top_hard_invalid_reasons": [
    "pickup_window_unreachable",
    "cargo_not_visible"
  ],
  "top_soft_risk_reasons": [
    "monthly_deadhead_budget_risk",
    "may_delay_home_task"
  ]
}
8.5 Advisor 应该看到什么

传给 Advisor 的不应该只有 valid candidates。

应该传：

1. top valid candidates
2. top soft risk candidates
3. hard invalid summary
4. hard invalid representative examples

建议数量：

top valid candidates: 8~12 个
top soft risk candidates: 5~8 个
hard invalid examples: 3~5 个

避免 prompt 太长，但必须让 Advisor 知道风险候选存在。

8.6 Step 4 验收标准
1. soft_risk_candidates 非空时会进入 Advisor context
2. hard_invalid_candidates 不会被 Advisor 选中
3. CandidateSafetyFilter 不直接输出 wait
4. CandidateSafetyFilter 不调用会静默改动作的 SafetyGate
5. 日志中能看到三类候选数量
9. Step 5：改 SafetyGate，不再静默重写策略
9.1 当前问题

SafetyGate 如果把 Advisor 选的动作直接改成 wait，会造成一个严重问题：

日志上看像是系统选择了 wait
但实际上是 Advisor 的动作被 SafetyGate 吞掉了

这样后面无法调试，也会造成 wait 死循环。

9.2 Phase 1 目标

SafetyGate 从：

validate_and_rewrite(action) -> final_action

改成：

validate(action) -> accepted / rejected + reason

也就是说：

SafetyGate 只负责否决非法动作
不负责选择替代策略
9.3 SafetyGate 可以拒绝什么

可以拒绝：

1. action type 不合法
2. cargo_id 不在当前可见货源里
3. cargo 已过 remove_time
4. pickup 时间窗绝对赶不上
5. finish 时间超过仿真范围
6. reposition 坐标非法
7. wait duration 非法
8. 当前状态下接口不允许这个动作
9.4 SafetyGate 不应该拒绝什么

不要因为以下原因直接拒绝：

1. 可能产生 soft penalty
2. 可能超过 soft budget
3. 可能影响后续偏好
4. 收益不够高
5. 看起来不划算
6. 等待可能更好
7. 这个动作和 mission 偏好有冲突但不是 hard invalid

这些应该交给 Advisor。

9.5 SafetyGate 返回结构

推荐：

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

如果通过：

{
  "accepted": true,
  "final_action": {
    "type": "take_order",
    "cargo_id": "C123"
  },
  "warnings": [
    "This action has soft risk: monthly_deadhead_budget_risk."
  ]
}
9.6 被拒绝后怎么处理

不要直接改成 wait。

推荐流程：

Advisor action
  ↓
SafetyGate validate
  ↓
如果 accepted:
    执行动作
如果 rejected:
    记录 rejection
    把 rejection 加入 Advisor context
    允许 Advisor 再决策一次
如果第二次仍 rejected:
    使用最小安全 fallback

最小安全 fallback 可以是：

wait 30 或 wait 60

但必须记录：

fallback_reason = safety_rejection_retry_failed
9.7 Step 5 验收标准
1. SafetyGate 不再静默改 wait
2. SafetyGate rejected 时有 rejection_code
3. rejection 会进入下一次 Advisor context
4. 同类 rejection 不应连续重复很多次
5. fallback wait 必须有明确 fallback_reason
10. Step 6：改 ModelDecisionService 串联流程
10.1 目标

ModelDecisionService.decide() 应该成为清晰的编排器，而不是隐藏策略中心。

推荐流程：

1. observe 当前司机状态
2. query 当前可见货源
3. query 历史动作
4. build state facts
5. build candidate facts
6. split candidates: valid / soft_risk / hard_invalid
7. call Advisor
8. validate Advisor action by SafetyGate
9. if rejected, retry Advisor once with rejection context
10. if still rejected, fallback to minimal safe action
11. log everything
12. return final action
10.2 推荐伪代码
def decide(driver_id: str):
    obs = observe(driver_id)
    state = build_state(obs)

    raw_candidates = candidate_fact_builder.build(state)
    candidate_groups = candidate_filter.split(raw_candidates)

    advisor_context = build_advisor_context(
        state=state,
        valid_candidates=candidate_groups.valid_candidates,
        soft_risk_candidates=candidate_groups.soft_risk_candidates,
        hard_invalid_summary=candidate_groups.summary,
        recent_rejections=get_recent_rejections(driver_id),
    )

    advisor_result = advisor.decide(advisor_context)

    gate_result = safety_gate.validate(
        action=advisor_result.final_action,
        state=state,
        visible_cargo=obs.visible_cargo,
    )

    if gate_result.accepted:
        log_decision(...)
        return gate_result.final_action

    record_rejection(driver_id, gate_result)

    retry_context = advisor_context.with_rejection(gate_result)
    retry_result = advisor.decide(retry_context)

    retry_gate_result = safety_gate.validate(
        action=retry_result.final_action,
        state=state,
        visible_cargo=obs.visible_cargo,
    )

    if retry_gate_result.accepted:
        log_decision(...)
        return retry_gate_result.final_action

    fallback_action = build_minimal_safe_fallback(state)
    log_fallback(...)
    return fallback_action
10.3 ModelDecisionService 不应该做什么

不要在这里重新加策略：

1. 不要 if rule.kind == xxx
2. 不要 if driver_id == xxx
3. 不要 if cargo_id == xxx
4. 不要 if wait_streak > N 就固定接单
5. 不要 if budget_pressure == urgent 就固定 wait
6. 不要 if Advisor 选 soft risk 就直接覆盖

ModelDecisionService 只做编排。

10.4 Step 6 验收标准
1. decide() 流程清晰
2. 每一步都有日志
3. Advisor 决策不会被静默覆盖
4. SafetyGate 拒绝有重试
5. fallback 有明确原因
6. 没有新增 rule.kind 策略分支
11. Phase 1 日志要求

Phase 1 必须加强日志，否则后面没法调试。

每次决策至少记录：

{
  "driver_id": "D001",
  "time": 30120,
  "location": [116.1, 39.9],
  "visible_cargo_count": 82,
  "candidate_count": 20,
  "valid_candidate_count": 10,
  "soft_risk_candidate_count": 7,
  "hard_invalid_candidate_count": 3,
  "advisor_model": "qwen/qwen3.5-flash-02-23",
  "advisor_policy_mode": "budget_tradeoff",
  "advisor_selected_candidate_id": "take_order_C123",
  "advisor_accepted_risks": [
    "monthly_deadhead_budget_risk"
  ],
  "advisor_rejected_alternatives": [
    "wait_60",
    "take_order_C456"
  ],
  "safety_gate_accepted": true,
  "safety_rejection_code": null,
  "final_action": {
    "type": "take_order",
    "cargo_id": "C123"
  },
  "fallback_used": false,
  "reason_tokens": 0,
  "json_parse_ok": true
}

重点看：

1. soft risk 是否进入 Advisor
2. Advisor 有没有接受风险
3. SafetyGate 有没有拒绝
4. final_action 是否被覆盖
5. wait 是否有真实理由
6. reason_tokens 为 0 是否影响流程
12. Phase 1 禁止新增的硬编码

本阶段尤其禁止新增这些东西：

if driver_id == "...":
    ...

if cargo_id == "...":
    ...

if rule.kind == "home_nightly":
    ...

if rule.kind == "family_task":
    ...

if "home" in mission_id:
    ...

if current_city == "某公开数据城市":
    ...

if date == "公开数据某一天":
    ...

if wait_streak > 5:
    return fixed_action

如果确实需要处理连续 wait，只能作为事实交给 Advisor：

{
  "wait_streak": 7,
  "warning": "The driver has waited 7 consecutive times. Waiting again has high opportunity cost."
}

不能在 Python 里直接说：

if wait_streak > 7:
    force_take_order()
13. Phase 1 允许保留的硬规则

这些可以保留：

1. cargo 不可见，不能接
2. cargo 已过期，不能接
3. 时间窗绝对赶不上，不能接
4. 坐标非法，不能 reposition
5. wait duration 非法，不能 wait
6. action schema 不合法，不能提交
7. 仿真结束前无法完成，不能接
8. 当前接口状态不允许的动作，不能提交

判断标准：

会导致接口报错 / 物理不可能 / 明确违反 hard constraint

这类规则可以放在 SafetyGate 或 CandidateFactBuilder 的 hard_invalid 中。

14. Phase 1 的调试方式
14.1 先小跑，不要直接大跑

建议先跑少量司机或少量天数。

如果代码没有内置参数，可以先用现有主流程跑，但主要观察前几十步日志。

目标不是马上看最终收益，而是看：

1. JSON 是否稳定
2. Advisor 是否拿到候选
3. SafetyGate 是否频繁拒绝
4. final_action 是否合理
5. 有没有 wait 死循环
14.2 重点检查命令

检查硬编码：

rg "rule.kind|mission_id|driver_id|cargo_id|home_nightly|family_task|special_cargo|wait_streak|force|fallback" demo/agent

检查模型配置：

rg "mimo|qwen|model|base_url|reason|reasoning|response_format" demo

检查是否还有静默重写 wait：

rg "return .*wait|type.*wait|action.*wait|fallback.*wait" demo/agent/safety_gate.py demo/agent/model_decision_service.py

检查是否删除 soft risk：

rg "soft|penalty|risk|budget|filter|blocked|invalid" demo/agent/planner.py demo/agent/candidate_safety_filter.py
15. Phase 1 验收标准

Phase 1 完成后，至少满足这些：

15.1 架构验收
1. Planner 主要输出候选事实，不直接做最终策略
2. CandidateSafetyFilter 只 hard filter
3. soft_risk_candidates 会进入 Advisor
4. SafetyGate 不静默重写动作
5. SafetyGate 拒绝有结构化 reason
6. Advisor 输出结构化 JSON
7. ModelDecisionService 只是编排，不新增特化策略
8. reason_tokens 为 0 不影响流程
15.2 行为验收
1. wait 决策必须有 wait_rationale
2. 连续 wait 明显减少
3. 高收益 soft risk 候选不会被提前删掉
4. Advisor 会明确说明 accepted_risks
5. Advisor 会说明 rejected_alternatives
6. SafetyGate 拒绝后不会无限重复同一错误
7. fallback wait 只在重试失败后出现
15.3 结果验收
1. 仿真可以完整跑完
2. validation_error 不上升
3. monthly_income 不明显低于原 baseline
4. preference_penalty 不失控
5. 日志能解释每次关键决策

注意：Phase 1 的收益不一定马上最高。
如果 Phase 1 后收益略有波动，但日志变清晰、候选池正常、wait 死循环减少，这是可以接受的。

16. Phase 1 的回滚策略

为了安全，建议每完成一个 Step 就 commit 一次。

推荐分支：

git checkout -b phase1-agentic-refactor

推荐 commit 顺序：

git add demo/agent/llm_client.py demo/agent/config.py
git commit -m "phase1: switch llm client to qwen json response"

git add demo/agent/llm_decision_advisor.py
git commit -m "phase1: add structured advisor decision schema"

git add demo/agent/planner.py
git commit -m "phase1: convert planner scoring into candidate facts"

git add demo/agent/candidate_safety_filter.py
git commit -m "phase1: keep soft-risk candidates visible"

git add demo/agent/safety_gate.py
git commit -m "phase1: return structured safety rejections"

git add demo/agent/model_decision_service.py
git commit -m "phase1: wire advisor retry and safety rejection context"

如果某一步出问题，可以只回滚那一步，不会全乱。

17. Phase 1 完成后要给我的信息

你执行完 Phase 1 后，最好把这些结果发给我：

1. 修改后的核心文件
2. 一小段决策日志
3. monthly_income_202603.json
4. run_summary_202603.json
5. 是否还有 validation_error
6. 是否还有连续 wait 很多次的司机
7. Qwen3.5-Flash 的日志里 reason_tokens / content / parse_ok 情况

我后面就可以继续帮你看：

1. 哪些模块还在偷偷做策略
2. Advisor 是否真的做了 trade-off
3. SafetyGate 是否过严
4. soft risk 是否被正确保留
5. wait 死循环是否还存在
6. 下一步 Phase 2 应该怎么改
18. Phase 1 最终判断标准

这一阶段的核心不是“代码变多”，而是“权责变清楚”。

最终判断一句话：

Python 不再替司机做收益/偏好取舍；
Python 只提供事实和硬安全；
LLM Advisor 看到完整候选后做最终决策；
SafetyGate 只拒绝非法动作，并把拒绝原因反馈回去。