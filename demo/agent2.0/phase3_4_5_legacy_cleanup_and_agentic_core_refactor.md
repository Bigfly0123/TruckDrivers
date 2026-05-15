# Phase 3.4.5 Legacy Cleanup & Agentic Core Refactor 规划

## 0. 阶段定位

Phase 3.4.5 的目标不是继续加 Agent，不是继续扩展 Opportunity，也不是给某个司机写特化逻辑。

本阶段目标是：

> 在 Phase 3 agentic graph 已经初步搭起来的基础上，清理旧框架遗留的 Candidate / Constraint / Safety / fallback wait 逻辑，重新划定模块边界，让新框架真正接管主决策链路。

当前系统的真实状态不是完整的新 Agentic 架构，而是：

```text
Agentic graph 外壳
+ legacy candidate generation
+ legacy constraint classification
+ LLM Advisor selection
+ opportunity evidence
+ legacy safety fallback
```

这导致以下问题持续存在：

```text
1. 可见订单不少，但 Advisor 实际可选候选很少。
2. 大量订单被 hard_invalid 提前打掉，LLM 没有权衡机会。
3. wait 很多，但 wait 没有目标语义，所以罚分仍然很高。
4. Opportunity evidence 暴露了不可选 candidate_id，诱导 Advisor 选 unknown candidate。
5. unknown candidate / safety rejected 后直接 fallback wait，浪费了本来可盈利的订单。
6. Reflection / DayPlan / Opportunity 信息堆进 prompt 后，candidate 边界变得混乱。
7. 老框架中的一些模块已经不是“保守兜底”，而是在负向影响新框架。
```

因此 Phase 3.4.5 是一次 **Legacy Cleanup + Core Boundary Refactor**。

---

## 1. 本阶段核心原则

### 1.1 不新增特定 Agent

本阶段禁止新增：

```text
CargoWatchAgent
RestAgent
HomeAgent
MarketAgent
D009Agent
NightRuleAgent
```

原因：

```text
当前问题不是 Agent 不够多，而是主链路边界不干净。
如果继续加 Agent，只会让系统重新变成规则模块拼装。
```

允许做的是：

```text
1. 清理 legacy adapter。
2. 修正 candidate boundary。
3. 修正 hard / soft / evidence 分类。
4. 修正 fallback wait。
5. 给 wait 增加目标语义。
6. 控制 Advisor prompt 输入。
```

---

### 1.2 不写司机特判

禁止：

```python
if driver_id == "D009":
    ...
```

禁止：

```python
if cargo_id == 240646:
    ...
```

D009 暴露的问题应该抽象成通用问题：

```text
specific cargo target
home deadline
night no-order/no-empty-run window
high penalty goal
future reachability
```

也就是说，D009 不能被单独修；要修的是：

```text
目标货源可达性
高罚分目标保护
时间窗口目标保护
目标驱动 wait / hold / reposition
```

---

### 1.3 不让 Python 抢决策权

禁止把 Python 改成新的策略大脑：

```python
if candidate.long_term_score > threshold:
    choose(candidate)
```

允许 Python 做：

```text
1. 事实计算。
2. 可执行性判断。
3. penalty exposure 估计。
4. future feasibility evidence。
5. wait purpose 标注。
6. deterministic recovery for invalid LLM output。
```

最终正常路径仍然是：

```text
Candidate / Constraint / Opportunity 提供 evidence
Advisor 选择 executable candidate
SafetyGate 做最终硬校验
Emit 执行动作
```

---

### 1.4 hard_invalid 只能表示真正不可执行

新的边界必须明确：

```text
hard_invalid = 物理或仿真层面不可执行
soft_risk = 可以执行，但可能产生罚分或未来风险
evidence = 帮助 Advisor 判断长期收益的信息
```

不能再让偏好类风险随便进入 hard_invalid。

---

### 1.5 fallback wait 必须变成最后手段

当前 fallback wait 太容易触发，尤其是：

```text
unknown candidate -> fallback wait
missing selected candidate -> fallback wait
safety rejected -> fallback wait
```

Phase 3.4.5 必须把 fallback wait 降级为真正最后手段。

---

## 2. 当前问题复盘

### 2.1 100 个订单不是 bug

仿真规定司机只能看到当前可见的 100 个订单，这个不能改。

所以问题不是：

```text
为什么只看 100 个订单？
```

而是：

```text
在这 100 个可见订单中，为什么真正进入 Advisor 的可执行候选那么少？
```

因此 Phase 3.4.5 不应该扩大可见订单数量，而应该提高当前 100 个可见订单的利用率。

---

### 2.2 Opportunity candidate 边界污染

Phase 3.4 最大新增 bug：

```text
Opportunity summary 中的 top / best long-term candidate 包含 hard_invalid candidate。
Advisor 看到高分 candidate_id 后选择它。
Adapter 发现它不在 valid + soft_risk 可选池里。
selected_candidate_id = None。
系统 fallback wait。
```

这导致：

```text
advisor selected unknown candidate_id: 155 次
其中很多时候当时存在 profitable valid order
```

这说明 Opportunity 不是简单“不够强”，而是污染了 Advisor 的候选边界。

---

### 2.3 hard_invalid 边界可能过宽

当前 hard_invalid 中包含：

```text
constraint_forbid_action_in_time_window
constraint_max_distance
constraint_operate_within_area
load_time_window_expired
load_time_window_unreachable
```

其中一部分是真硬约束，比如时间窗已经过期、物理上无法到达。

但一部分可能来自司机偏好，例如：

```text
夜间不接单
区域偏好
最大空驶距离
回家窗口
连续休息
```

如果这些被直接 hard 掉，Advisor 就没有权衡机会。

正确做法是：

```text
会被仿真拒绝的才 hard_invalid。
会被罚钱但仍可执行的，应该 soft_risk。
会影响未来目标的，应该 evidence。
```

---

### 2.4 wait 很多，但没有完成目标

当前 wait 数量高，不代表系统在正确休息。

wait 可能只是：

```text
原地等 30 分钟
原地等 60 分钟
fallback wait
unknown wait
```

但偏好真正需要的是：

```text
连续休息 4 / 5 / 8 小时
23 点前到家
夜间留在家附近
禁行窗口内不接单不空驶
等待目标货源且保持可达
月度目标访问
```

所以问题不是 wait 不够，而是：

```text
wait 没有 purpose。
wait 没有 target constraint。
wait 没有 expected progress。
wait 不保证地点正确。
wait 不保证连续性。
wait 不保证后续不会被打断。
```

---

### 2.5 Safety fallback 仍然继承旧框架问题

SafetyGate 应该只是最终硬校验。

但当前表现更像：

```text
前面出错 -> Safety fallback wait
```

这会吞掉大量本来可盈利订单。

尤其是 unknown candidate 的情况，这不是业务上应该 wait，而是系统内部 candidate_id 边界错误。

正确做法应该是：

```text
Advisor 输出 unknown candidate
↓
记录异常
↓
从 executable candidates 中 deterministic recovery
↓
再交 SafetyGate
↓
recovery 也失败才 fallback wait
```

---

## 3. Phase 3.4.5 总目标

本阶段完成后，系统应该达到：

```text
1. Advisor 只能看到 executable candidate。
2. hard_invalid 不再混入 Advisor-facing opportunity summary。
3. unknown candidate 不再直接 fallback wait。
4. hard / soft / evidence 边界更清楚。
5. wait 候选必须带目标语义。
6. fallback wait 数量显著下降。
7. valid + soft_risk 的可执行订单利用率上升。
8. 老框架中负作用逻辑被隔离、替换或删除。
9. 新 agentic graph 的主链路变得干净。
```

---

## 4. 任务一：修复 Opportunity candidate 边界污染

### 4.1 问题

Opportunity 可以评估所有候选，包括 hard_invalid，用于诊断。

但 Advisor-facing summary 不能暴露 hard_invalid candidate_id。

否则 Advisor 会选不可选 candidate，导致 unknown candidate 和 fallback wait。

---

### 4.2 修改要求

将 Opportunity summary 拆成两类：

```text
advisor_opportunity_summary
diagnostic_opportunity_summary
```

---

### 4.3 advisor_opportunity_summary

只允许统计：

```text
valid_candidates
soft_risk_candidates
```

也就是 Advisor 真正可以选择的候选。

建议字段：

```json
{
  "executable_candidate_count": 0,
  "top_executable_candidates_by_long_term_score": [],
  "best_executable_long_term_candidate_id": null,
  "best_executable_long_term_score": null,
  "best_executable_candidate_action": null,
  "best_executable_candidate_estimated_net": null,
  "best_executable_candidate_estimated_net_after_penalty": null,
  "best_executable_candidate_wait_cost": null
}
```

---

### 4.4 diagnostic_opportunity_summary

可以包含 hard_invalid，但必须明确标记 non-selectable。

建议字段：

```json
{
  "all_candidate_count": 0,
  "hard_invalid_candidate_count": 0,
  "high_value_hard_invalid_count": 0,
  "top_non_selectable_candidate_reasons": {},
  "top_hard_invalid_by_long_term_score": [],
  "non_selectable_candidate_id_exposed_to_advisor": false
}
```

---

### 4.5 强制规则

Advisor prompt 中禁止出现：

```text
best_long_term_candidate_id = hard_invalid candidate
top_candidates_by_long_term_score 包含 hard_invalid candidate_id
```

如果需要提示不可选高价值订单，只能摘要：

```text
There are high-value non-selectable candidates, mainly blocked by time-window unreachable and area constraints.
```

不能把 candidate_id 暴露给 Advisor。

---

### 4.6 验收指标

```text
advisor_unknown_candidate_count 明显下降，目标为 0。
best_long_term_candidate_selectable = true。
non_selectable_candidate_id_exposed_to_advisor = false。
fallback_reason = llm_api_failed / unknown candidate 显著下降。
```

---

## 5. 任务二：unknown candidate deterministic recovery

### 5.1 问题

Advisor 返回 unknown candidate 时，当前系统直接 fallback wait。

这是错误的。

unknown candidate 是系统内部错误，不代表业务上应该 wait。

---

### 5.2 新逻辑

当 Advisor 返回 candidate_id 不在 executable pool：

```text
1. 记录 advisor_unknown_candidate = true。
2. 记录 unknown_candidate_id。
3. 检查 executable pool 是否为空。
4. 如果 executable pool 不为空，进入 deterministic recovery。
5. recovery candidate 再交 SafetyGate。
6. 如果 recovery 失败，再 fallback wait。
```

---

### 5.3 recovery candidate 选择顺序

不要复杂化，先用稳定的 deterministic recovery：

```text
1. 最高 long_term_score_hint 的 executable candidate。
2. 如果没有 long_term_score_hint，选最高 estimated_net_after_penalty。
3. 如果没有 estimated_net_after_penalty，选最高 estimated_net。
4. 如果没有 order，选 goal_satisfy wait。
5. 如果没有 goal_satisfy wait，选 rest_progress wait / home_window wait。
6. 最后才普通 fallback wait。
```

注意：

```text
这不是 Python 正常抢决策权。
这是异常恢复路径，只在 LLM 输出不可用 candidate_id 时触发。
```

---

### 5.4 新增日志

```json
{
  "advisor_unknown_candidate": true,
  "unknown_candidate_id": "take_order_xxx",
  "executable_candidate_count_when_unknown": 12,
  "profitable_order_existed_when_unknown": true,
  "recovery_used": true,
  "recovery_candidate_id": "take_order_yyy",
  "recovery_candidate_action": "take_order",
  "recovery_reason": "highest_executable_long_term_score",
  "recovery_candidate_estimated_net": 850.0,
  "recovery_candidate_long_term_score": 1300.0,
  "recovery_passed_safety": true
}
```

---

### 5.5 验收指标

```text
unknown candidate 不再直接导致 fallback wait。
llm_failed_with_profitable_order_count 显著下降。
recovery_used_count 有记录。
recovery_passed_safety_rate 较高。
wait_count 下降。
take_order_count 上升。
```

---

## 6. 任务三：hard_invalid 边界审计与重划

### 6.1 目标

把 hard_invalid 从“偏好/风险/约束混合桶”改成真正的“不可执行桶”。

---

### 6.2 hard_invalid 新定义

只能包括：

```text
1. 货源不可见或不存在。
2. 货源时间窗已经过期。
3. 物理上无法在装货截止前到达。
4. 动作 schema 非法。
5. 仿真 API 一定拒绝。
6. 明确不可破的硬规则。
```

---

### 6.3 soft_risk 新定义

以下不应该轻易 hard 掉：

```text
1. 会违反司机偏好。
2. 会产生 preference penalty。
3. 可能破坏连续休息。
4. 可能破坏回家窗口。
5. 可能影响夜间不接单偏好。
6. 可能影响 specific cargo 目标。
7. 可能导致空驶偏高。
8. 可能离目标区域更远。
9. 可能影响月度访问目标。
```

这些应该进入：

```text
soft_risk_reasons
penalty_exposure
future_feasibility_risk
goal_conflict_evidence
```

---

### 6.4 hard_invalid reason 分类报告

每次 run 后输出：

```json
{
  "hard_invalid_reason_counts": {},
  "hard_invalid_reason_classification": {
    "load_time_window_expired": "true_hard",
    "load_time_window_unreachable": "true_hard_or_needs_check",
    "constraint_forbid_action_in_time_window": "audit_required",
    "constraint_max_distance": "likely_should_be_soft_if_preference",
    "constraint_operate_within_area": "likely_should_be_soft_if_preference"
  },
  "profitable_hard_invalid_order_count": 0,
  "profitable_hard_invalid_order_net_sum": 0,
  "top_profitable_hard_invalid_examples": []
}
```

---

### 6.5 审计流程

对每个 hard_invalid reason 做三分类：

```text
A. true_hard：保持 hard_invalid。
B. should_be_soft：降级为 soft_risk。
C. unclear：先保留，但必须增加更细 reason。
```

例如：

```text
load_time_window_expired
```

通常是 true_hard。

```text
load_time_window_unreachable
```

如果是真的赶不到装货时间，是 true_hard。

```text
constraint_forbid_action_in_time_window
```

需要区分：

```text
仿真硬禁行：true_hard
司机偏好夜间不接单：should_be_soft
```

```text
constraint_max_distance
constraint_operate_within_area
```

如果来自司机偏好，大概率应该 soft_risk，而不是 hard_invalid。

---

### 6.6 验收指标

```text
hard_invalid reason 更细。
profitable hard_invalid 中 should_be_soft 的比例下降。
valid + soft_risk executable candidate count 上升。
Advisor executable pool 扩大。
take_order_count 上升。
fallback wait 下降。
```

---

## 7. 任务四：wait 语义重构

### 7.1 问题

当前 wait 太泛化。

wait 多，但罚分仍然高，说明 wait 没有真正服务于目标。

---

### 7.2 wait 类型重划

所有 wait candidate 必须有 purpose。

建议枚举：

```text
fallback_wait
unknown_wait
no_executable_order_wait
rest_progress_wait
home_window_wait
forbid_window_wait
goal_hold_wait
market_wait
target_cargo_wait
```

其中：

```text
fallback_wait 和 unknown_wait 是坏 wait。
rest_progress_wait / home_window_wait / goal_hold_wait 是目标 wait。
market_wait 必须有 opportunity 依据。
```

---

### 7.3 wait candidate 新字段

```json
{
  "action": "wait",
  "duration_minutes": 60,
  "wait_purpose": "rest_progress_wait",
  "target_constraint_id": "daily_continuous_rest",
  "target_goal_type": "continuous_rest",
  "expected_progress": {
    "current_rest_streak_minutes": 180,
    "rest_streak_after_wait_minutes": 240,
    "required_rest_minutes": 300,
    "will_complete_after_wait": false
  },
  "wait_location_valid_for_goal": true,
  "will_reduce_penalty_exposure": true,
  "penalty_exposure_before_wait": 500,
  "penalty_exposure_after_wait": 200
}
```

---

### 7.4 对 home / night window wait

```json
{
  "wait_purpose": "home_window_wait",
  "target_goal_type": "home_deadline_or_night_window",
  "distance_to_home_km": 0.6,
  "inside_required_home_radius": true,
  "window_start": "23:00",
  "window_end": "08:00",
  "will_remain_valid_through_window": true
}
```

---

### 7.5 对 target cargo wait

不要新增 D009 模块，而是通用 target cargo wait：

```json
{
  "wait_purpose": "target_cargo_wait",
  "target_goal_type": "specific_cargo",
  "target_cargo_id": "xxx",
  "target_pickup_location": "...",
  "target_available_time": "...",
  "current_reachability": "reachable",
  "reachability_after_wait": "reachable",
  "risk_of_missing_target": "low",
  "penalty_if_missed": 10000
}
```

---

### 7.6 wait 选择约束

Advisor 可以选 wait，但必须知道：

```text
1. 这个 wait 解决什么目标？
2. 它会不会减少罚分风险？
3. 它会不会错过当前可盈利订单？
4. 它是否在正确地点？
5. 它是否保持连续性？
```

---

### 7.7 验收指标

```text
fallback_wait_count 下降。
unknown_wait_count 下降。
goal_purpose_wait_count 上升。
wait_but_penalty_not_reduced_count 下降。
continuous_rest_violation_count 下降。
home_window_violation_count 下降。
```

---

## 8. 任务五：SafetyGate 降权与兜底清理

### 8.1 SafetyGate 正确职责

SafetyGate 只做：

```text
1. 最终动作 schema 校验。
2. 仿真硬约束校验。
3. 货源存在性校验。
4. 时间窗物理可行性校验。
```

SafetyGate 不应该：

```text
1. 做收益选择。
2. 做偏好权衡。
3. 遇到异常就直接 wait。
4. 替代 Advisor 进行策略决策。
```

---

### 8.2 fallback wait 新规则

只有以下情况允许 fallback wait：

```text
1. executable candidate pool 为空。
2. deterministic recovery 失败。
3. SafetyGate 拒绝所有 recovery candidate。
4. 当前确实没有任何可执行 order / reposition / goal wait。
```

---

### 8.3 fallback wait 必须记录来源

```json
{
  "fallback_used": true,
  "fallback_reason": "all_recovery_candidates_failed_safety",
  "fallback_wait_type": "true_last_resort",
  "executable_candidate_count_before_fallback": 0,
  "profitable_order_existed_before_fallback": false
}
```

---

### 8.4 验收指标

```text
fallback_used_count 下降。
fallback_with_profitable_order_count 接近 0。
safety_rejected_then_wait_count 下降。
unknown_candidate_then_wait_count 接近 0。
```

---

## 9. 任务六：Advisor prompt 输入清理

### 9.1 问题

当前 prompt 中混入过多信息：

```text
Reflection
DayPlan
Opportunity
hard_invalid candidate facts
memory hints
candidate_id
diagnostics
```

这会导致：

```text
1. LLM 选错 candidate_id。
2. LLM 被不可选 candidate 干扰。
3. token 成本上升。
4. 长期分数没有稳定转化成决策。
```

---

### 9.2 Advisor 只能看 executable candidates

Advisor candidate list 只能包含：

```text
valid_candidates
soft_risk_candidates
```

每个 candidate 只保留必要字段：

```json
{
  "candidate_id": "...",
  "action": "take_order",
  "estimated_net": 900,
  "estimated_net_after_penalty": 700,
  "long_term_score_hint": 1200,
  "wait_opportunity_cost": null,
  "top_risk_reasons": [],
  "critical_goal_impact": "low",
  "future_feasibility_risk": "medium"
}
```

---

### 9.3 hard_invalid 信息只能摘要

允许：

```text
High-value non-selectable candidates exist.
Main blocking reasons: load_time_window_unreachable, area preference risk.
```

禁止：

```text
hard_invalid candidate_id = take_order_123
best_long_term_candidate_id = take_order_123
```

---

### 9.4 Reflection / DayPlan 限长

Reflection 和 DayPlan 不能原文全塞。

只保留：

```text
1. 最近 1-3 条关键失败。
2. 当前司机最高罚分风险。
3. 当前必须避免的重复错误。
4. 不超过固定 token budget。
```

建议字段：

```json
{
  "critical_recent_lessons": [],
  "active_high_penalty_risks": [],
  "do_not_repeat": []
}
```

---

### 9.5 验收指标

```text
total_tokens 下降。
advisor_unknown_candidate_count 下降。
advisor_ignored_best_long_term_count 下降。
high_cost_wait_selected_count 下降。
```

---

## 10. 任务七：legacy adapter 清理计划

### 10.1 当前 legacy 组件

重点审计：

```text
LegacyCandidateAdapter
LegacyConstraintAdapter
LegacySafetyAdapter
CandidateFactBuilder
ConstraintEvaluator
fallback_wait
constraint_satisfy candidate generation
```

---

### 10.2 不要一次性删除

不建议一开始直接删掉所有 legacy 文件。

正确顺序：

```text
1. 先加边界日志。
2. 再修最明显负作用。
3. 再替换 legacy adapter 内部行为。
4. 最后删除无用旧逻辑。
```

---

### 10.3 替换目标

#### LegacyCandidateAdapter

目标替换成：

```text
AgenticCandidateBuilder
```

职责：

```text
1. 从可见 100 个订单生成候选。
2. 生成基础 wait / reposition / goal candidates。
3. 不做过早策略选择。
4. 不做偏好 hard filter。
```

#### LegacyConstraintAdapter

目标替换成：

```text
ConstraintEvidenceEvaluator
```

职责：

```text
1. 只判断 true hard invalid。
2. 把偏好冲突转成 soft_risk。
3. 输出 penalty exposure。
4. 输出 future feasibility risk。
```

#### LegacySafetyAdapter

目标替换成：

```text
MinimalHardSafetyGate
```

职责：

```text
1. 最终硬校验。
2. 不做收益选择。
3. 不直接吞掉候选。
4. 不轻易 fallback wait。
```

---

### 10.4 删除候选

可以删除或冻结的逻辑：

```text
1. 会直接生成无目的 fallback wait 的逻辑。
2. 会把偏好风险直接 hard_invalid 的逻辑。
3. 会把 constraint_satisfy wait 当默认安全动作的逻辑。
4. Advisor 不可见但 Opportunity 暴露 candidate_id 的逻辑。
5. 旧 Planner 中任何会抢最终动作决策权的逻辑。
```

---

## 11. 任务八：结果诊断报告重构

每次实验必须输出一个 Phase 3.4.5 diagnostic report。

建议文件：

```text
demo/results/phase3_4_5_diagnostics.json
demo/results/phase3_4_5_driver_summary.md
```

---

### 11.1 全局指标

```json
{
  "total_decisions": 0,
  "take_order_count": 0,
  "wait_count": 0,
  "reposition_count": 0,
  "fallback_wait_count": 0,
  "unknown_wait_count": 0,
  "goal_purpose_wait_count": 0,
  "advisor_unknown_candidate_count": 0,
  "unknown_candidate_recovery_count": 0,
  "unknown_candidate_direct_wait_count": 0,
  "fallback_with_profitable_order_count": 0,
  "hard_invalid_profitable_order_count": 0,
  "avg_executable_candidate_count": 0,
  "avg_valid_order_count": 0,
  "avg_soft_risk_order_count": 0,
  "avg_hard_invalid_count": 0
}
```

---

### 11.2 每司机指标

```json
{
  "driver_id": "D009",
  "net_income": 0,
  "gross_income": 0,
  "cost": 0,
  "penalty": 0,
  "take_order_count": 0,
  "wait_count": 0,
  "fallback_wait_count": 0,
  "unknown_candidate_count": 0,
  "recovery_count": 0,
  "hard_invalid_reason_counts": {},
  "top_penalty_sources": {},
  "wait_purpose_counts": {},
  "missed_goal_reasons": {}
}
```

---

### 11.3 关键诊断问题

每次跑完必须能回答：

```text
1. wait 为什么发生？
2. fallback wait 是不是最后手段？
3. Advisor 有没有选 unknown candidate？
4. unknown candidate 后有没有 recovery？
5. 有 profitable order 时为什么没接？
6. hard_invalid 中哪些其实应该 soft？
7. wait 是否减少了 penalty exposure？
8. D009 为什么仍然错过 specific cargo？
9. D010 为什么 sequence_ok 但仍然家事罚分？
10. gross 上不去是订单少、接单少、还是高收益订单被过滤？
```

---

## 12. 实施顺序

### Step 1：先修 Opportunity 边界污染

优先级最高。

原因：

```text
这是 Phase 3.4 新增的明确 bug。
修复后可以直接减少 unknown candidate 和 fallback wait。
```

完成标准：

```text
Advisor-facing summary 只包含 executable candidates。
hard_invalid candidate_id 不再进入 Advisor prompt。
```

---

### Step 2：加 unknown candidate recovery

原因：

```text
即使 prompt 修了，LLM 仍可能输出错误 candidate_id。
系统不能因为一次格式/边界错误就直接 wait。
```

完成标准：

```text
unknown candidate 不再直接 fallback wait。
```

---

### Step 3：重写 fallback wait 触发条件

原因：

```text
fallback wait 现在太强，会吞掉可盈利订单。
```

完成标准：

```text
fallback wait 必须证明 executable pool 为空或 recovery 全失败。
```

---

### Step 4：hard_invalid reason 审计

原因：

```text
这是收入规模上不去的关键。
```

完成标准：

```text
输出 true_hard / should_be_soft / unclear 分类。
```

---

### Step 5：把明显偏好类 hard_invalid 降为 soft_risk

原因：

```text
让 Advisor 看到更多真实可执行订单。
```

完成标准：

```text
executable order count 上升。
hard_invalid profitable order count 下降。
```

---

### Step 6：wait purpose 重构

原因：

```text
wait 多但罚分高，说明 wait 不是目标驱动。
```

完成标准：

```text
wait 都带 purpose。
fallback_wait / unknown_wait 单独统计。
```

---

### Step 7：Advisor prompt 清理

原因：

```text
降低 candidate_id 混乱和 token 成本。
```

完成标准：

```text
Advisor 只看 executable candidates。
Reflection / DayPlan / Opportunity 摘要化。
```

---

### Step 8：删除或冻结负作用 legacy 逻辑

原因：

```text
确认新边界稳定后，再删除老逻辑，避免一次性崩溃。
```

完成标准：

```text
legacy adapter 不再是主行为来源。
fallback wait 旧逻辑被替换。
无目的 constraint_satisfy wait 被删除或改造。
```

---

## 13. 验收标准

Phase 3.4.5 不要求直接冲到 30w，但必须看到结构性改善。

### 13.1 必须达成

```text
1. advisor_unknown_candidate_count 接近 0。
2. unknown_candidate_direct_wait_count = 0。
3. fallback_with_profitable_order_count 显著下降。
4. Advisor-facing opportunity 不再包含 hard_invalid candidate_id。
5. wait_purpose 覆盖率接近 100%。
6. fallback_wait_count 下降。
7. valid + soft_risk executable candidate count 上升。
8. hard_invalid reason 分类清楚。
```

---

### 13.2 收益预期

保守预期：

```text
net 从 117510.55 明显恢复一截。
```

主要来自：

```text
1. 修复 155 次 unknown candidate 导致的 fallback wait。
2. 增加 profitable order 的实际执行率。
3. 降低无目的 wait。
4. 降低部分偏好罚分。
```

但不要承诺直接 30w。

原因：

```text
当前 gross 只有 287143.49，即使 penalty 清零，net 也只有约 204810。
要冲 30w，后续还需要提高 gross，也就是提高高收益订单利用率、市场占位和长期路线质量。
```

---

## 14. 禁止事项

本阶段禁止：

```text
1. 不要新增特定司机 Agent。
2. 不要新增 D009 专用逻辑。
3. 不要用 driver_id / cargo_id 写死策略。
4. 不要让 Python 根据 long_term_score 直接正常路径选动作。
5. 不要绕过 SafetyGate。
6. 不要扩大仿真规定之外的可见订单数量。
7. 不要继续往 Advisor prompt 里塞完整 hard_invalid candidate 列表。
8. 不要让 fallback wait 作为默认恢复动作。
9. 不要把 Opportunity 做成新的决策器。
10. 不要一次性删除所有 legacy 文件，必须先替换主链路行为。
```

---

## 15. 推荐提交结构

建议这阶段分成多个小 commit：

```text
commit 1: split advisor/diagnostic opportunity summary
commit 2: prevent non-selectable candidate_id exposure
commit 3: add advisor unknown candidate recovery
commit 4: add fallback wait diagnostics
commit 5: add hard_invalid reason audit report
commit 6: refactor obvious preference-hard reasons to soft_risk
commit 7: add wait_purpose and wait progress facts
commit 8: trim Advisor prompt inputs
commit 9: freeze/remove negative legacy fallback paths
commit 10: run full March benchmark and write phase3_4_5 analysis
```

---

## 16. 最终目标

Phase 3.4.5 完成后，系统应该从：

```text
新 graph 包旧逻辑
```

变成：

```text
新 graph 真正接管主链路
```

也就是：

```text
Candidate 提供候选，不偷做策略。
Constraint 区分 hard / soft / evidence，不乱杀候选。
Opportunity 提供可执行候选的长期价值，不污染 Advisor。
Advisor 只在可执行候选中选择。
Safety 只做最终硬校验，不默认吞成 wait。
wait 必须有目标语义。
legacy 逻辑逐步退出主路径。
```

---

# 简短执行提示词

```text
请基于当前 Phase 3.4 结果实现 Phase 3.4.5：Legacy Cleanup & Agentic Core Refactor。

本阶段不要新增特定 Agent，不要新增司机特判，不要继续堆 Opportunity 子模块。目标是清理旧 Candidate / Constraint / Safety / fallback wait 逻辑，让新 agentic graph 真正接管主链路。

优先任务：
1. 修复 Opportunity candidate 边界污染：
   - Advisor-facing opportunity_summary 只能包含 valid + soft_risk executable candidates。
   - hard_invalid candidates 只能进入 diagnostic summary，不能暴露 candidate_id 给 Advisor。
   - 增加 best_long_term_candidate_selectable、non_selectable_candidate_id_exposed_to_advisor 等日志。

2. 修复 unknown candidate 直接 fallback wait：
   - Advisor 返回 unknown candidate_id 时，不要直接 wait。
   - 从 executable pool 中 deterministic recovery。
   - 优先最高 long_term_score_hint，其次 estimated_net_after_penalty，其次 estimated_net。
   - recovery candidate 再交 SafetyGate。
   - 只有 recovery 失败才 fallback wait。

3. 审计 hard_invalid 边界：
   - hard_invalid 只能表示物理不可执行或仿真 API 一定拒绝。
   - 偏好风险、未来罚分、目标冲突应降为 soft_risk + evidence。
   - 输出 hard_invalid reason 分类：true_hard / should_be_soft / unclear。

4. 重构 wait 语义：
   - 所有 wait 必须有 wait_purpose。
   - 区分 fallback_wait、unknown_wait、rest_progress_wait、home_window_wait、forbid_window_wait、goal_hold_wait、market_wait。
   - 记录 wait 是否真的推进目标和减少 penalty exposure。

5. 清理 Safety fallback：
   - SafetyGate 只做最终硬校验。
   - fallback wait 必须是最后手段。
   - 如果存在 profitable executable order，不能直接 fallback wait。

6. 清理 Advisor prompt：
   - Advisor 只看 executable candidates。
   - hard_invalid candidate_id 不得进入 prompt。
   - Reflection / DayPlan / Opportunity 只保留摘要，避免 candidate_id 干扰和 token 膨胀。

禁止：
- 不要写 driver_id 特判。
- 不要写 D009 专用模块。
- 不要让 Python 在正常路径根据分数直接选动作。
- 不要扩大仿真规定的 100 个可见订单。
- 不要绕过 SafetyGate。
- 不要一次性删除所有 legacy 文件，先替换主路径行为，再删除负作用逻辑。

完成后重新跑 March benchmark，并输出 phase3_4_5_diagnostics.json 和 phase3_4_5_driver_summary.md，重点分析 unknown candidate、fallback wait、hard_invalid reason、wait purpose、penalty reduction 和 gross improvement。
```
