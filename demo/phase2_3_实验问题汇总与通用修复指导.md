# Phase 2.3 实验问题汇总与通用修复指导

## 1. 背景

当前 TruckDrivers agent 的目标不是为某个司机写定制规则，而是建立一套通用的 Agentic 决策框架：

```text
Preference Text
-> PreferenceRule
-> ConstraintSpec
-> CandidateFactBuilder
-> ConstraintEvaluator
-> Advisor
-> SafetyGate
-> Action
```
Python 层负责：

获取事实；
生成候选；
计算候选收益、时间、位置、约束影响；
区分 hard invalid / soft risk / valid；
做最终硬安全校验。

Advisor 层负责：

在 valid + soft risk 候选中做收益与偏好风险权衡；
选择 selected_candidate_id；
给出简短理由。

Fallback 只能保命，SafetyGate 只能守门，不能重新接管赚钱决策。

本次实验中，D001 的行为暴露出多个通用机制问题。D001 不应被写成特判，但它能作为通用约束系统的测试样例：如果通用机制正确，D001 的“不出深圳”和“连续休息”应自然生效。

2. 本次实验观察到的主要现象
2.1 D001 不是完全没货，而是大量货源被 hard invalid

日志显示，D001 在早期 step 中可见货源并不少。

例如：

step 1:
visible_cargo_count = 37
candidate_count = 41
valid_count = 5
hard_invalid_count = 36
top_hard_invalid_reasons = {"constraint_operate_within_area": 36, ...}
step 2:
visible_cargo_count = 52
candidate_count = 56
valid_count = 4
hard_invalid_count = 52
top_hard_invalid_reasons = {"constraint_operate_within_area": 52, ...}
step 5:
visible_cargo_count = 100
candidate_count = 104
valid_count = 7
soft_risk_count = 4
hard_invalid_count = 93
top_hard_invalid_reasons = {
  "constraint_operate_within_area": 87,
  "load_time_window_expired": 17,
  "constraint_forbid_cargo_category": 11,
  "load_time_window_unreachable": 8
}

这说明系统不是“看不到货”，而是大量货源被约束层过滤掉了。对 D001 而言，operate_within_area 过滤大量出深圳订单是合理的，因为其原始约束是不能出深圳。但这也带来了一个压力测试：当硬区域约束导致合法订单变少时，agent 仍然需要在剩余合法订单中积极寻找收益机会，而不是默认优先休息。日志中 D001 的 hard invalid reason 主要由 constraint_operate_within_area 主导，同时 step 6、step 7 中 Advisor 选择继续 rest/wait。

2.2 Advisor 经常把 partial rest 当成最安全选择

日志中 D001 多次选择：

start_rest_60_constraint_0_daily_rest
continue_rest_60_constraint_0_daily_rest

典型理由包括：

Continuing rest avoids penalty; order profit doesn't outweigh rest violation risk.

以及：

Rest needed to avoid 300 penalty.
Orders lose money after penalty.
Wait satisfies constraint progress.

这说明 Advisor 确实理解了“休息可以避免罚款”，但它可能仍然过度重视 partial rest。尤其是当一次 continue_rest_60 并不能立即完成 480 分钟连续休息时，它只是 progress，不应该被理解为“现在就避免了 300 元罚金”。日志中 step 6 的 reason 甚至出现换行，导致 JSONL 被拆成多行，这也暴露出日志清洗问题。

2.3 continuous_rest 风险评估仍然过保守

当前 constraint_evaluator.py 中，对 take_order / reposition 的 continuous_rest 风险判断逻辑大致是：

if max_streak >= required:
    return None

finish_minute = candidate_finish_minute
day_end_minute = (state.current_day + 1) * 1440
remaining_day_minutes = day_end_minute - finish_minute

if remaining_day_minutes >= required:
    return None
else:
    return risk

问题在于，这里使用的是：

remaining_day_minutes >= required

也就是接单后当天还剩不剩完整的 480 分钟。

但正确的通用判断应该是：

remaining_need = max(0, required - max_streak_today)
remaining_day_minutes >= remaining_need

如果司机今天已经连续休息过 300 分钟，那么剩余需求不是 480 分钟，而是 180 分钟。当前逻辑会把这类订单过度标记为 continuous_rest risk，从而让 Advisor 更倾向于继续休息。代码中确实可以看到 remaining_day_minutes >= required 的判断，以及 risk detail 中记录了 remaining_day_minutes、required、max_streak。

2.4 rest satisfy candidate 的 facts 已经有进步，但语义还需要更强约束

planner.py 中，rest satisfy candidate 已经包含：

satisfy_status = "complete" if completes else "progress"
actually_satisfies_after_this_wait = completes
avoids_estimated_penalty = penalty if completes else 0.0
penalty_if_rest_not_completed = penalty
remaining_rest_minutes_after_wait = remaining_after

这比旧的 wait_rest_480 好很多，因为它区分了 complete 和 progress。

但是，从实验行为看，Advisor 仍可能受到以下字段影响：

source = constraint_satisfy
satisfies_constraint_type = continuous_rest
penalty_if_rest_not_completed = 300

这些字段会让模型倾向于认为“休息候选更安全”。因此，不仅 facts 要写清楚，Advisor prompt 和 candidate summary 也要明确：

partial rest != penalty avoided
actually_satisfies_after_this_wait=false means this wait is only progress
profitable order should be preferred if enough time remains for remaining rest later

Advisor prompt 里已经写了“partial progress, not full satisfaction”，但实验结果说明这条约束还不够强，需要进一步强化。

2.5 operate_within_area 的方向是对的，但还缺少通用完整性

当前 operate_within_area 对 take_order 会检查 pickup 和 destination 是否在 area_bounds 内；如果 constraint priority 是 hard，则返回 violation，否则返回 risk。这个设计方向是对的，因为它不是按 driver_id 特判，而是按 constraint.priority 决定 hard / soft。

但是还需要补齐几个通用点：

operate_within_area 不应只处理 take_order；
对 reposition，目标点也必须检查是否在范围内；
对 wait，如果当前位置已经不在范围内，也不能盲目 valid；
对 hard 区域约束，范围内候选必须保留给 Advisor，不能被误杀；
对 soft 区域偏好，只能产生 risk / penalty，不能 hard invalid。

D001 的“不出深圳”应该自然编译为 hard operate_within_area，但其他“尽量在某区域跑”的司机应该自然编译为 soft operate_within_area。

2.6 日志格式存在严重问题：JSONL 被 reason 换行污染

当前 agent_decisions.jsonl 中，LLM reason 里出现了换行：

"reason": "Rest needed to avoid 300 penalty.
Orders lose money after penalty.
Wait satisfies constraint progress."

这会破坏严格 JSONL 格式。后续如果用：

for line in f:
    json.loads(line)

可能直接解析失败。

这是一个工程问题，但会严重影响调试和自动评估。

3. 本次实验还能额外看出的潜在问题

除了前面已经讨论过的区域约束和连续休息约束，本次实验还暴露出以下问题。

3.1 valid_count 很低时，系统缺少“机会质量诊断”

日志能看到：

visible_cargo_count
candidate_count
valid_count
soft_risk_count
hard_invalid_count
top_hard_invalid_reasons

这些已经很好。

但仍然不够判断：

剩下的 valid 候选到底有没有赚钱机会？
Advisor 是因为没有好单才休息？
还是有好单但被 rest 逻辑压制了？

建议新增：

valid_order_count
valid_profitable_order_count
best_valid_order_net
best_valid_order_id
best_soft_risk_order_net_after_penalty
best_soft_risk_order_id
selected_candidate_estimated_net_after_penalty
selected_candidate_penalty_exposure

这样才能快速判断：

如果 valid_profitable_order_count > 0 且 selected_action = wait
=> 重点查 Advisor / rest risk
3.2 hard invalid reason 现在是多标签计数，容易误读

日志中一个候选可能同时有多个 hard invalid reason，例如：

["load_time_window_expired", "constraint_operate_within_area"]

因此：

hard_invalid_count = 93
top_hard_invalid_reasons 中各项相加可能 > 93

这是合理的多标签统计，但需要在日志说明中明确，否则容易误以为计数不一致。

建议新增两种统计：

hard_invalid_primary_reason_counts
hard_invalid_all_reason_counts

其中：

primary_reason 用固定优先级选择一个主因；
all_reason_counts 保留当前多标签统计。

建议 primary reason 优先级：

1. load_time_window_expired
2. load_time_window_unreachable
3. hard preference violation
4. forbid cargo category
5. area violation
6. others

这样可以更清楚地区分“订单本来就接不了”和“偏好过滤导致接不了”。

3.3 load_time_window 问题仍然存在，但不一定是主因

日志中 load_time_window_expired 和 load_time_window_unreachable 仍然频繁出现，例如 step 5 中分别有 17 和 8 次。

这说明之前的装货时间窗修复已经在生效，但还需要确认：

pickup_arrival_minute
cargo_deadline_minute
load_window_buffer_minutes
deadline_source

是否都符合仿真环境的真实判定。

尤其要检查：

load_time 是绝对分钟还是日内分钟；
跨天订单 deadline 是否被正确展开；
buffer 5 minutes 是否过严；
query_cargo 返回的 cargo 是否可能已经过期；
SafetyGate 和 CandidateFactBuilder 是否使用同一套时间窗逻辑。

如果时间窗逻辑过严，会进一步压缩合法订单池，加剧 wait/rest 倾向。

3.4 forbid_cargo_category 与 area violation 叠加，可能导致候选池进一步缩小

日志中也出现了：

constraint_forbid_cargo_category

例如 step 5 有 11 次，step 6 有 21 次。

这本身不一定是 bug，但需要确认：

货物 category 字段是否标准化？
偏好中的禁运品类是否被过度匹配？
是否存在中英文、同义词、大小写、空格导致的误判？

建议对 forbid_cargo_category 加日志：

cargo_id
cargo_category_raw
cargo_category_normalized
matched_forbidden_category
constraint_id
3.5 Advisor 的“收益比较”可能还不够显式

当前 prompt 中有：

Choose the candidate with the best expected net outcome
Prefer lower penalty exposure when profits are similar

也有 continuous rest 的说明。

但实验说明，在 rest 压力存在时，Advisor 仍可能过度选择 wait。建议强化为：

A partial continuous-rest wait has opportunity cost.
If actually_satisfies_after_this_wait=false, it does not avoid the penalty now.
If a profitable valid order leaves enough time to complete remaining rest later today, prefer the order.
Choose wait/rest only when:
1. no profitable valid/acceptable soft-risk order exists, or
2. taking an order would make required rest impossible, or
3. wait immediately completes a high-penalty hard/soft requirement.
3.6 Advisor reason 长度控制没有真正生效

Prompt 要求：

Keep reason under 100 characters.

但日志中仍出现多行 reason。

说明仅靠 prompt 不可靠。必须在代码层清洗：

def clean_reason(reason: Any, max_len: int = 160) -> str:
    text = str(reason or "")
    text = " ".join(text.split())
    return text[:max_len]

写日志前、返回前都应该清洗。

3.7 be_at_location_by_deadline satisfy candidate 可能也会干扰决策

日志中 satisfy_candidate_types 一直包含：

["continuous_rest", "be_at_location_by_deadline"]

这说明系统持续生成“去某地”类 satisfy candidate。

需要确认：

D001 是否真的有 location deadline 类偏好；
该候选是否总是生成，即使 deadline 还很远；
它是否占用了 Advisor 的注意力；
它是否会与 operate_within_area 冲突；
它是否应该只在 deadline approaching 时生成。

建议通用规则：

be_at_location_by_deadline candidate 只有在以下情况生成：
- 当前不在目标附近；
- deadline 存在；
- 距离 deadline 已进入 planning horizon；
- 如果不移动，后续可能无法按时到达。

否则它会变成噪声候选。

4. 通用修复原则
原则 1：不要写 driver_id 特判

禁止：

if driver_id == "D001":
    ...

应该通过：

Preference text
-> ConstraintSpec
-> priority / severity / penalty / scope

自然表达不同司机约束。

D001 的“不出深圳”应该自然产生：

ConstraintSpec(
    constraint_type="operate_within_area",
    priority="hard",
    area_bounds=深圳市范围,
    scope="vehicle_position"
)

而不是 D001 专属逻辑。

原则 2：constraint_type 不决定 hard / soft，priority 才决定 hard / soft

错误做法：

if constraint_type == "operate_within_area":
    hard_invalid

正确做法：

if impact.status == "violation":
    hard_invalid
elif impact.status == "risk":
    soft_risk

同一种 constraint_type 可以有 hard 和 soft 两种语义。

例如：

“必须不出深圳” -> hard operate_within_area
“尽量在深圳附近跑” -> soft operate_within_area
原则 3：hard invalid 只用于真实不可执行或硬约束违反

hard invalid 应只包括：

1. 仿真环境一定会拒绝的动作；
2. 明确 hard preference violation；
3. 时间窗已经过期或不可达；
4. 安全门一定会拒绝的动作。

soft preference risk 不应提前删除候选。

原则 4：continuous_rest 应评估“剩余所需休息”，不是重新要求完整休息

错误：

remaining_day_minutes >= required_rest_minutes

正确：

remaining_need = max(0, required_rest_minutes - max_rest_streak_today)
remaining_day_minutes >= remaining_need

并且需要区分：

current_rest_streak: 当前连续休息段
max_rest_streak_today: 今天已经达到过的最大连续休息段
remaining_need: 距离满足要求还差多少
原则 5：partial satisfy candidate 只是进度，不是收益

对于：

start_rest_60
continue_rest_60

如果：

actually_satisfies_after_this_wait == False

则它只代表 progress，不能代表 penalty avoided。

Advisor 选择它时，必须考虑机会成本。

原则 6：日志必须服务于调试

每次实验都应该能回答：

1. 有多少货源？
2. 有多少候选？
3. 多少 hard invalid？
4. hard invalid 主因是什么？
5. 多少 valid order？
6. 多少 profitable valid order？
7. Advisor 为什么没有选 best order？
8. 选 wait 是因为没有订单，还是因为 rest risk？
9. 约束是否真的完成，还是只是在 progress？
5. 具体修改建议
5.1 修复 continuous_rest 风险评估

位置：

demo/agent/constraint_evaluator.py

当前问题逻辑：

if remaining_day_minutes >= required:
    return None

建议改为：

remaining_need = max(0, required - max_streak)

if remaining_day_minutes >= remaining_need:
    return None

risk detail 建议改成：

detail = (
    f"may_fail_continuous_rest_today: "
    f"action={candidate.action}, "
    f"finish_minute={finish_minute}, "
    f"day_end_minute={day_end_minute}, "
    f"remaining_day_minutes={remaining_day_minutes}, "
    f"required={required}, "
    f"max_streak={max_streak}, "
    f"remaining_need={remaining_need}"
)
5.2 强化 rest candidate 语义

位置：

demo/agent/planner.py

当前已有：

"actually_satisfies_after_this_wait": completes,
"avoids_estimated_penalty": penalty if completes else 0.0,
"penalty_if_rest_not_completed": penalty,

建议新增：

"is_partial_progress_only": not completes,
"remaining_need_before_wait": max(0, required - max_streak),
"remaining_need_after_wait": remaining_after,
"opportunity_cost_sensitive": not completes,

并确保 candidate summary 中也传给 Advisor。

5.3 强化 Advisor prompt

位置：

demo/agent/llm_decision_advisor.py

建议在 CONTINUOUS REST 部分加入：

- Do not choose a partial rest candidate only because rest is incomplete.
- If actually_satisfies_after_this_wait=false, the wait does not avoid the penalty now; it only makes progress.
- A profitable valid order should be preferred if after finishing it there is still enough time to complete remaining_rest_need today.
- Choose partial rest over cargo only when cargo would make the rest requirement impossible or when no profitable valid/acceptable cargo exists.

同时保留：

Advisor 仍然可以选择 soft_risk candidate，如果收益足以覆盖 penalty exposure。
5.4 补齐 operate_within_area 的 action scope

位置：

demo/agent/constraint_evaluator.py

当前重点检查 take_order 的 pickup 和 destination。

建议通用扩展：

if candidate.action == "take_order":
    check pickup
    check destination

elif candidate.action == "reposition":
    check target latitude / longitude

elif candidate.action == "wait":
    check current vehicle location

并保持：

status = "violation" if constraint.priority == "hard" else "risk"

D001 的 hard 深圳约束应该继续 hard invalid；其他 soft 区域偏好则应保留为 soft risk。

5.5 增强候选质量日志

位置：

demo/agent/model_decision_service.py

建议新增通用日志字段：

"log_candidate_quality": {
    "valid_order_count": ...,
    "valid_profitable_order_count": ...,
    "soft_risk_order_count": ...,
    "soft_risk_profitable_order_count": ...,
    "best_valid_order_id": ...,
    "best_valid_order_net": ...,
    "best_soft_risk_order_id": ...,
    "best_soft_risk_order_net_after_penalty": ...,
    "selected_candidate_id": ...,
    "selected_candidate_source": ...,
    "selected_candidate_estimated_net_after_penalty": ...,
    "selected_candidate_penalty_exposure": ...
}

建议新增 rest 相关日志：

"rest_debug": {
    "current_rest_streak": ...,
    "max_rest_streak_today": ...,
    "required_rest_minutes": ...,
    "remaining_need": ...,
    "rest_risk_candidate_count": ...,
    "partial_rest_candidate_count": ...,
    "complete_rest_candidate_count": ...
}

建议新增 area 相关日志：

"area_debug": {
    "operate_within_area_constraints": ...,
    "area_valid_order_count": ...,
    "area_invalid_order_count": ...,
    "area_invalid_pickup_count": ...,
    "area_invalid_destination_count": ...
}
5.6 区分 primary hard invalid reason 和 all hard invalid reasons

建议保留现有：

top_hard_invalid_reasons

但改名或补充：

hard_invalid_all_reason_counts
hard_invalid_primary_reason_counts

primary reason 可按优先级确定：

PRIMARY_REASON_PRIORITY = [
    "load_time_window_expired",
    "load_time_window_unreachable",
    "constraint_forbid_cargo_category",
    "constraint_operate_within_area",
    "constraint_avoid_zone",
    "constraint_max_distance",
]

这样可以避免误读多标签 reason 统计。

5.7 修复日志 JSONL 清洗

位置：

demo/agent/model_decision_service.py

建议写日志前递归清洗字符串：

def _clean_for_jsonl(value):
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, dict):
        return {k: _clean_for_jsonl(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean_for_jsonl(v) for v in value]
    return value

写入时：

log_entry = _clean_for_jsonl(log_entry)
f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

同时对 Advisor reason 单独截断：

reason = " ".join(str(reason or "").split())[:160]
5.8 检查 be_at_location_by_deadline candidate 的生成条件

位置：

demo/agent/planner.py

建议 satisfy candidate 不要无条件生成。

生成条件应包括：

1. 当前不在目标附近；
2. deadline 存在；
3. 当前距离 deadline 已进入 planning horizon；
4. 如果继续接单/等待，后续可能无法按时到达；
5. reposition 目标本身不违反 operate_within_area 等 hard constraints。

否则它可能成为 Advisor 的噪声候选。

6. 推荐修复优先级
P0：必须立即修
修复 continuous_rest 风险判断：
remaining_need = max(0, required - max_streak_today)
清洗日志 reason，保证 JSONL 每行合法。
增加 valid_profitable_order_count、best_valid_order_net、selected_candidate_net 日志。
P1：下一轮必须修
强化 Advisor prompt 对 partial rest 的约束。
补齐 operate_within_area 对 reposition / wait 的通用检查。
区分 primary hard invalid reason 和 all hard invalid reason。
增强 rest_debug / area_debug。
P2：后续优化
检查 load_time_window 跨天和 buffer 逻辑。
检查 forbid_cargo_category 的标准化和误匹配。
优化 be_at_location_by_deadline satisfy candidate 的生成时机。
对 Advisor 增加 deterministic tie-breaker 或候选排序解释。
7. 验收标准

修复后，至少应满足以下标准。

7.1 通用机制标准
不出现 if driver_id == "D001" 特判；
hard / soft 由 ConstraintSpec.priority 决定；
SafetyGate 不负责赚钱决策；
Fallback 不主动接单赚钱；
Advisor 只从 valid + soft_risk candidates 中选。
7.2 D001 行为标准

D001 作为测试样例，应表现为：

1. 出深圳订单被 hard_invalid，这是正确的；
2. 深圳范围内合法订单被保留；
3. 如果存在 profitable valid order，且接单后仍能完成剩余连续休息，则应倾向接单；
4. 不应每天机械地先休满 480 分钟再开始接单；
5. partial rest 只有在没有好订单，或接单会导致 rest impossible 时才优先；
6. selected reason 不应长期是 “rest avoids penalty”。
7.3 日志标准

每一步日志应能回答：

是否有合法赚钱订单？
如果没选，为什么？
是 hard constraint 没货？
是 rest risk 太高？
是 Advisor 误判？
还是时间窗不可达？

最低应包含：

visible_cargo_count
candidate_count
valid_count
soft_risk_count
hard_invalid_count
valid_order_count
valid_profitable_order_count
best_valid_order_id
best_valid_order_net
selected_candidate_id
selected_candidate_source
selected_candidate_estimated_net_after_penalty
top_hard_invalid_reasons
hard_invalid_primary_reason_counts
rest_debug
area_debug

并且 agent_decisions.jsonl 必须严格满足一行一个 JSON object。