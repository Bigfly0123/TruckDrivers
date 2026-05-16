# Phase 3.4.6 规划：Decision Core 收敛与决策质量修复

> 版本目标：在不继续堆模块、不硬编码司机/任务、不扩大系统复杂度的前提下，修复 Phase 3.4.5 暴露出的核心决策质量问题。  
> 主目标：恢复并提升净收益，减少无效 wait，压制 penalty 恶化，让 goal / rest / forbid / opportunity / Advisor 回到统一收益口径下。  
> 次目标：适度约束 token，不追求极限降本，只避免继续从 2000 万 token 级别继续失控膨胀。

---

## 0. 背景结论

Phase 3.4.5 的意义不是收益提升，而是框架错误清理。

它已经修掉了几类原先非常危险的框架问题：

- Advisor 不再选择 unknown candidate。
- unknown candidate 不再直接退化为 wait。
- fallback wait 没有继续吞掉 profitable order。
- non-selectable / hard_invalid candidate 不再暴露给 Advisor 作为可选项。
- graph / final_action / day_plan 等基本流程完整，没有明显节点断裂。

但是，收益结果说明：框架合法化之后，真实决策质量问题暴露出来了。

Phase 3.4 到 Phase 3.4.5 的总账对比：

| 阶段 | net | gross | cost | penalty |
|---|---:|---:|---:|---:|
| Phase 3.4 | 117510.55 | 287143.49 | 82332.93 | 87300 |
| Phase 3.4.5 | 86067.54 | 293053.15 | 85335.61 | 121650 |

变化：

| 指标 | 变化 |
|---|---:|
| gross | +5909.66 |
| cost | +3002.68 |
| penalty | +34350 |
| net | -31443.01 |

这说明系统不是“冒险后收入显著提高”，而是“soft risk 放开后只多赚了一点 gross，却多吃了大量 penalty”。

因此，Phase 3.4.6 不能继续堆 Agent 模块，也不能继续扩大 hard/soft 放开范围。下一步应做的是：**收敛决策口径，修复 wait / goal / penalty / 时间窗 / 单位时间收益这几个关键问题。**

---

## 1. 本阶段最重要的原则

### 1.1 不继续堆模块

禁止新增如下类型的大模块：

- 新的 penalty-aware agent
- 新的 wait agent
- 新的 cargo watch agent
- 新的 committed plan agent
- 新的 reflection agent
- 新的 meta planner
- 新的多轮辩论式 Advisor

当前问题不是“缺更多智能模块”，而是已有模块之间职责边界不清、信号重复、决策权冲突。

本阶段只允许做：

- 现有字段收敛；
- 现有候选评分统一；
- 现有 goal / wait / penalty 逻辑降噪；
- 现有日志补充必要审计；
- 必要的小型 gate / demotion / scorer。

### 1.2 不硬编码司机、货物、任务

禁止写类似：

```python
if driver_id == "D009":
    ...
if driver_id == "D010":
    ...
if cargo_id == "...":
    ...
```

D009 / D010 只能作为问题样例，不能作为代码特判对象。

应抽象成通用机制：

- D009 类问题：`specific_cargo_watch_goal`
- D010 类问题：`ordered_window_hold_goal`
- 到达关键窗口后离开的问题：`window_hold_preservation`
- 目标货源消失的问题：`goal_materialization_persistence`

### 1.3 不让模块抢决策权

各模块职责必须收敛：

| 模块 | 允许做什么 | 不允许做什么 |
|---|---|---|
| Candidate Layer | 生成可执行候选，补齐候选字段 | 不直接替 Advisor 做最终策略解释 |
| Constraint Layer | 标注 hard / soft / expected_penalty | 不把大量 soft risk 直接丢给 Advisor 让其脑补 |
| Goal Layer | 给候选增加 goal_progress_delta，少量生成 hold/reposition | 不大规模生成 critical wait 抢收入 |
| Opportunity Layer | 计算 duration、rate、opportunity_cost | 不写长篇自然语言说服 Advisor |
| Reflection | 产生短 flag 或降级信号 | 不把长历史塞进 prompt |
| Advisor | 在统一评分后的 top candidates 中做最终选择 | 不在杂乱候选里凭自然语言重新理解规则 |
| SafetyGate | 拦截硬错误 | 不参与收益优化和策略偏好 |

### 1.4 不用复杂解释掩盖坏决策

所有策略判断最终必须回到总账：

- gross 是否增加？
- cost 是否可控？
- penalty 是否下降或至少不恶化？
- net 是否恢复？
- wait 是否减少？
- 单位时间收益是否提高？
- 目标罚分是否真实下降？

如果一个模块解释很多，但总账变差，应优先怀疑模块输出质量，而不是继续增加解释。

### 1.5 token 是次要目标，只做轻量约束

不要把 Phase 3.4.6 做成 token 优化专项。

token 目标：

- 不追求极限压缩；
- 不牺牲必要诊断；
- 不引入复杂 token budget 系统；
- 只避免继续无控制膨胀；
- 能稳定在 2000 万以内可以接受；
- 优先保证净收益和决策质量。

允许做的轻量 token 控制：

- Advisor 只看 Top-K 压缩候选；
- hard_invalid 明细不进入 Advisor；
- DayPlan 复用时不要重复塞全文；
- Reflection 用短 flag；
- 长日志写文件，不塞 prompt。

---

## 2. 当前核心问题诊断

### 2.1 soft risk 放开过多，但 penalty trade-off 没跟上

Phase 3.4.5 中 `hard_soft_boundary_reclassification_count = 104110`，说明大量原本被 hard 拦截的风险被放进了可权衡空间。

问题不是 soft risk 不能放，而是当前系统没有统一折算：

```text
soft risk -> expected_penalty -> net_after_expected_penalty -> rate
```

Advisor 看到的是风险解释，而不是统一后的收益效率。

结果是：

- gross 小幅增加；
- penalty 大幅增加；
- net 明显下降。

因此，下一步不能继续大范围 hard -> soft。必须先建立 penalty-aware 的统一收益口径。

### 2.2 wait 过多，而且 wait 缺少强约束

Phase 3.4.5 中：

- 总决策：1243
- wait：716
- take_order：507
- reposition：20

wait 已经超过 take_order。大量 wait 会直接降低周转和 gross。

wait 的来源包括：

- no_valid_order
- forbid_window_wait
- rest_progress_wait
- profitable_order_but_wait
- fallback_wait
- goal / hold wait

当前问题不是 wait 没有分类，而是分类后仍没有被用于强约束。很多 wait 局部有理由，但全局伤害收益。

### 2.3 Goal Layer 过强，容易制造 critical / must_do_now

Phase 3.4.5 中：

- selected_goal_candidate_count = 409
- selected_goal_must_do_now_count = 371
- stuck_goal_decisions = 627
- goal_overuse = 323

这说明 Goal Layer 很活跃，但并没有稳定转化为收益或罚分降低。

当前 Goal Layer 的风险：

- 把目标压力转换成 critical；
- 把 critical 转换成 wait/hold；
- 目标不可 materialize 时仍持续影响决策；
- 有利润订单时，goal 仍可能压过收入。

正确方向不是再加 committed plan agent，而是收窄 Goal Layer 权限，让目标只产生有限、可验证的候选和字段。

### 2.4 缺少单位时间收益，导致长单和低周转

当前 long_term_score 更像单次净收益，而不是月度收益效率。

如果只看单次 net，系统可能选择：

- 超长订单；
- 低周转路线；
- 长时间占用司机；
- 单次看似赚钱但月度总收益低的行为。

应增加核心字段：

```text
net_after_expected_penalty_per_hour
```

但注意：不是写死“永远选 per_hour 最高”，而是把它作为主排序指标之一，结合 total net、goal_progress、risk 做统一评分。

### 2.5 D009 / D010 暴露目标持久化问题

D009 类问题：

- specific cargo 目标没有真正持续 watch；
- 目标货源短暂 unavailable 后可能变成 untracked；
- 目标状态没有稳定持续到完成或确认失败。

D010 类问题：

- sequence_ok 可能为 true；
- 但到达关键 home window 后没有保持到窗口结束；
- 到达后离开导致 penalty；
- 缺少 window hold preservation。

这两类问题都不能用司机特判修。应抽象成通用目标机制。

### 2.6 hard_invalid / load_time_window_expired 仍然巨大

大量 profitable hard invalid 仍然存在，主要原因是：

- load_time_window_expired
- load_time_window_unreachable
- end_month_unreachable

这说明系统存在两个可能问题：

1. 货源池返回大量过期货；
2. 时间窗解析 / 当前时间 / ETA / 时区 / 分钟单位 / 禁行休息叠加判断有 bug；
3. 前序策略没有提前布局，导致看到时已经错过；
4. hard invalid 虽然不进 Advisor，但仍然说明真实可执行机会不足。

Phase 3.4.6 必须审计，但不要把这做成新大模块。

---

## 3. Phase 3.4.6 总体目标

### 3.1 主目标

1. 净收益恢复到 Phase 3.4 以上。
2. 短期目标：net > 120000。
3. 理想目标：net 进入 180000 ~ 220000 区间。
4. penalty 不高于 Phase 3.4.5，最好回落到 Phase 3.4 附近。
5. wait 占比明显下降。
6. take_order 周转提高。
7. goal_overuse / stuck_goal 明显下降。
8. advisor_ignored_best_long_term_count 下降。
9. profitable_order_but_wait 下降。
10. D009 / D010 类目标罚分问题有明确改善。

### 3.2 次目标：轻量 token 约束

1. token 不继续从 2000 万级别明显上升。
2. 不要求强行降到几百万。
3. 不为了省 token 牺牲关键诊断。
4. Advisor prompt 做 Top-K 压缩。
5. 重复 DayPlan / Reflection / hard_invalid 明细不再反复注入。

---

## 4. 设计方向：统一 Decision Core，而不是新增 Agent

### 4.1 新的决策流

推荐收敛为：

```text
Raw Orders / State
    ↓
Candidate Generation
    ↓
Constraint Annotation
    ↓
Penalty / Duration / Rate Scoring
    ↓
Goal Progress Annotation
    ↓
Wait / Goal Demotion Gate
    ↓
Top-K Candidate Summary
    ↓
Advisor
    ↓
SafetyGate
    ↓
Final Action
```

核心变化：

- Python 负责结构化计算；
- Advisor 只看压缩后的 Top-K；
- Goal / Reflection / DayPlan 不再大段说服 Advisor；
- 所有候选统一到同一套收益字段；
- wait / goal 不再天然安全或天然 critical。

---

## 5. 具体修改任务

---

# Task 1：统一候选收益字段

## 5.1 目的

让 Advisor 不再凭自然语言脑补收益、风险、目标，而是看到统一评分字段。

## 5.2 所有候选必须补齐字段

对所有进入 Advisor 的候选，统一包含：

```json
{
  "candidate_id": "...",
  "action_type": "take_order | wait | reposition | hold",
  "source": "cargo | goal | system",
  "gross": 0,
  "cost": 0,
  "base_net": 0,
  "expected_penalty": 0,
  "net_after_expected_penalty": 0,
  "duration_minutes": 0,
  "net_after_expected_penalty_per_hour": 0,
  "risk_flags": [],
  "hard_invalid": false,
  "soft_risk": false,
  "goal_progress_delta": 0,
  "wait_opportunity_cost": 0,
  "diagnostic_reason": ""
}
```

## 5.3 字段说明

### base_net

```text
base_net = gross - cost
```

### expected_penalty

soft risk 不再只是文字说明，必须折算成 expected_penalty。

示例：

```text
expected_penalty = sum(probability_i * penalty_i)
```

如果暂时没有概率模型，可以先用保守估计：

```text
expected_penalty = likely_penalty_if_violate
```

但必须明确来源，不能让 Advisor 自己判断。

### net_after_expected_penalty

```text
net_after_expected_penalty = base_net - expected_penalty
```

### net_after_expected_penalty_per_hour

```text
net_after_expected_penalty_per_hour =
    net_after_expected_penalty / max(duration_minutes / 60, 0.1)
```

### duration_minutes

对订单候选必须包含完整占用时间：

```text
当前状态 -> 装货地 -> 装货等待/服务 -> 卸货地 -> 卸货服务 -> 结束状态
```

如果暂时算不全，也要记录 approximate 字段，不能缺失。

## 5.4 验收

- 进入 Advisor 的候选 100% 有 `net_after_expected_penalty`。
- 进入 Advisor 的订单候选 100% 有 `duration_minutes`。
- 进入 Advisor 的订单候选 100% 有 `net_after_expected_penalty_per_hour`。
- Advisor summary 中不再只显示单次 net，必须显示 rate。

---

# Task 2：建立统一评分，但不要硬规则化

## 6.1 目的

减少“左右脑互搏”，让所有模块提供证据，最终通过统一评分形成候选排序。

## 6.2 推荐评分公式

先用简单线性分数，不要复杂模型：

```text
decision_score =
    A * normalized(net_after_expected_penalty_per_hour)
  + B * normalized(net_after_expected_penalty)
  + C * normalized(goal_progress_delta)
  - D * normalized(wait_opportunity_cost)
  - E * risk_uncertainty
```

建议初始权重：

```text
A = 0.45   # 单位时间收益
B = 0.25   # 总净收益
C = 0.20   # 目标推进
D = 0.20   # wait 机会成本惩罚
E = 0.10   # 风险不确定性惩罚
```

注意：

- 这不是最终调参结果；
- 不要在代码里写死难以调整的魔法数；
- 权重应放在 config；
- 日志要输出每个 candidate 的 score breakdown。

## 6.3 Advisor 的角色

Advisor 不再从全量候选里自由判断，而是在 Top-K 中选择。

Advisor 输入应包含：

```text
Top candidates sorted by decision_score:
1. candidate_id
2. action_type
3. net_after_expected_penalty
4. rate
5. duration
6. expected_penalty
7. goal_progress_delta
8. wait_opportunity_cost
9. risk_flags
10. score breakdown
```

Advisor 仍可选择不是第一名的候选，但必须说明：

```text
why_not_best_score_candidate
```

并且这个原因必须引用结构化字段，而不是泛泛说“长期更好”。

## 6.4 验收

- 每次决策有 best_score_candidate。
- 记录 `selected_vs_best_score_gap`。
- 如果 gap 超过阈值，记录 warning。
- `advisor_ignored_best_long_term_count` 应下降。
- `profitable_order_but_wait` 应下降。

---

# Task 3：Wait Gate，压制无效等待

## 7.1 目的

wait 不能再作为默认安全动作。wait 必须证明自己比可执行订单、reposition 或 hold 更好。

## 7.2 wait candidate 必须补齐字段

```json
{
  "wait_minutes": 0,
  "wait_purpose": "market_wait | rest_progress_wait | forbid_window_wait | goal_wait | goal_hold_wait | fallback_wait",
  "expected_progress": "",
  "best_alternative_candidate_id": "",
  "best_alternative_rate": 0,
  "best_alternative_net_after_penalty": 0,
  "wait_opportunity_cost": 0,
  "wait_allowed": true,
  "wait_reject_reason": ""
}
```

## 7.3 wait_allowed 规则

### market_wait

如果存在可执行订单，且：

```text
best_order_rate > min_profitable_rate
```

则 market_wait 降级或禁止。

### rest_progress_wait

只有在以下情况允许：

- 休息确实能推进合法状态；
- 不休息会导致硬约束失败；
- 或休息后能明显降低 penalty；
- 或当前没有正收益订单。

如果 rest 不紧急，且存在高 rate 订单，则 rest wait 降级。

### forbid_window_wait

必须比较：

```text
wait_until_window_end
vs
reposition_to_better_market
vs
take_short_order_if_legal
```

如果 reposition 有正收益或明显改善后续机会，不应默认 forbid wait。

### goal_wait

只有在目标有明确窗口、明确 deadline、明确 penalty，且 wait 能真实推进目标时允许。

不能因为 goal active 就生成普通 critical wait。

### fallback_wait

只允许在无可执行候选或 SafetyGate 无法恢复时出现。

## 7.4 禁止做法

禁止只用自然语言说：

```text
等待更安全
等待符合目标
等待有利于长期规划
```

必须有结构化字段支持。

## 7.5 验收

- wait 总数下降。
- `high_cost_wait_selected_count` 下降。
- `profitable_order_but_wait` 下降。
- D001 / D008 / D009 的 wait 比例下降。
- `fallback_wait_count` 不上升。

---

# Task 4：Goal Demotion，防止目标层抢决策权

## 8.1 目的

Goal Layer 不能无限制造 critical / must_do_now。目标必须能 materialize，否则要降级。

## 8.2 目标状态字段

每个 active goal 维护：

```json
{
  "goal_id": "...",
  "goal_type": "specific_cargo_watch | ordered_step | home_window | revenue_target | rest_requirement",
  "urgency": "low | medium | high | critical",
  "deadline": "...",
  "penalty_if_fail": 0,
  "materialized_candidate_count": 0,
  "stuck_count": 0,
  "unavailable_count": 0,
  "last_progress_time": "...",
  "last_materialized_time": "...",
  "demotion_reason": "",
  "can_generate_wait": false,
  "can_generate_hold": false,
  "can_generate_reposition": false
}
```

## 8.3 Demotion 规则

### 连续不可 materialize

如果一个 goal 连续 N 次没有可执行候选：

```text
urgency 降一级
```

如果连续 M 次仍无进展：

```text
不再生成候选，只保留 diagnostic
```

建议初始：

```text
N = 3
M = 6
```

### stuck goal

如果 goal 被标记 stuck：

- 不允许继续 critical；
- 不允许继续 must_do_now；
- 只能生成 diagnostic 或低优先级 hint；
- 除非出现新的 materialized candidate。

### critical 限制

critical 必须满足：

1. 有明确 deadline/window；
2. 有明确 penalty_if_fail；
3. 当前动作能直接避免 penalty；
4. wait/hold 有明确结束时间；
5. 不执行会造成高罚分。

否则不能 critical。

## 8.4 Goal candidate 输出限制

Goal 只允许生成三类候选：

```text
1. take_order_to_progress_goal
2. reposition_to_progress_goal
3. hold_to_preserve_goal
```

不允许泛化生成：

```text
generic_goal_wait
generic_critical_wait
```

## 8.5 验收

- `selected_goal_must_do_now_count` 下降。
- `stuck_goal_decisions` 下降。
- `goal_overuse` 下降。
- selected goal candidate 中 wait 占比下降。
- goal 相关 penalty 不上升。
- D009/D010 类问题改善。

---

# Task 5：Specific Cargo Watch 通用机制

## 9.1 目的

解决 D009 类目标货源追踪断裂问题，但不能硬编码 D009。

## 9.2 通用抽象

定义目标类型：

```text
specific_cargo_watch_goal
```

适用场景：

- 某司机必须完成某个特定货源；
- 或必须完成满足特定属性的货源；
- 该货源可能暂时不可见；
- 不能因为一次不可见就丢失目标。

## 9.3 状态机

```text
WATCHING
  ↓ target visible
MATERIALIZED
  ↓ candidate selected
COMMITTED
  ↓ cargo completed
COMPLETED

WATCHING
  ↓ target unavailable
UNAVAILABLE_TRACKED
  ↓ repeated unavailable beyond threshold
DEMOTED_OR_FAILED
```

## 9.4 关键规则

- target unavailable 不能直接变 untracked。
- 每次决策都要记录 watch state。
- 如果目标货源不可见，记录 unavailable_count。
- 如果目标重新可见，恢复 materialized。
- 如果 deadline 接近，urgency 可上升，但必须有 materialized candidate 才能生成强候选。
- 如果长期不可见，不生成 critical wait，只生成 diagnostic。

## 9.5 日志字段

```json
{
  "goal_id": "...",
  "watch_state": "WATCHING | MATERIALIZED | COMMITTED | COMPLETED | UNAVAILABLE_TRACKED | DEMOTED_OR_FAILED",
  "target_visible": true,
  "target_candidate_id": "...",
  "unavailable_count": 0,
  "last_seen_time": "...",
  "deadline": "...",
  "action_taken": "..."
}
```

## 9.6 验收

- specific cargo 目标不再从 unavailable 直接消失为 untracked。
- 目标失败时能解释是不可见、不可达、被更高优先级动作覆盖，还是 missed deadline。
- D009 类 penalty 有下降趋势。

---

# Task 6：Ordered Window Hold 通用机制

## 10.1 目的

解决 D010 类“到达关键窗口后又离开”问题，但不能硬编码 D010。

## 10.2 通用抽象

定义目标类型：

```text
ordered_window_hold_goal
```

适用场景：

- 必须按顺序完成若干步骤；
- 某一步不仅要求到达，还要求在窗口内保持；
- 离开窗口会导致 penalty。

## 10.3 状态机

```text
NOT_STARTED
  ↓ previous step completed
APPROACHING_WINDOW
  ↓ arrived before/in window
IN_WINDOW_HOLD
  ↓ hold until window end
WINDOW_SATISFIED
  ↓ next step
NEXT_STEP_ALLOWED
```

## 10.4 关键规则

当目标进入 `IN_WINDOW_HOLD`：

- 生成 `hold_to_preserve_goal` candidate；
- hold candidate 有明确结束时间；
- 破坏 hold 的动作必须增加 expected_penalty；
- Advisor 仍可选择离开，但必须证明收益覆盖 penalty；
- 不允许普通收入订单无惩罚地打断 hold。

## 10.5 不允许做法

不要写：

```python
if driver_id == "D010":
    force_hold()
```

要写：

```python
if goal.type == "ordered_window_hold_goal" and goal.state == "IN_WINDOW_HOLD":
    generate_hold_to_preserve_goal()
```

## 10.6 验收

- 到达关键窗口后离开导致的 penalty 下降。
- ordered_steps_regression 不上升。
- window hold 有明确 action log。
- hold 不泛化为普通 wait。

---

# Task 7：审计 load_time_window_expired

## 11.1 目的

确认大量 hard_invalid 是否来自：

1. 货源 API 返回过期货；
2. 时间解析 bug；
3. ETA 判断过严；
4. 休息/禁行叠加错误；
5. 前序策略没有提前布局。

## 11.2 增加审计字段

对每个因 `load_time_window_expired` 或 `load_time_window_unreachable` 被挡掉的候选，抽样或聚合记录：

```json
{
  "candidate_id": "...",
  "driver_id": "...",
  "current_time": "...",
  "load_window_start": "...",
  "load_window_end": "...",
  "travel_eta_to_load_minutes": 0,
  "service_time_minutes": 0,
  "forbid_window_delay_minutes": 0,
  "rest_required_delay_minutes": 0,
  "arrival_time_if_go_now": "...",
  "expired_by_minutes": 0,
  "unreachable_by_minutes": 0,
  "first_seen_time": "...",
  "first_seen_expired": true,
  "reason_class": "already_expired_when_seen | missed_due_to_previous_action | unreachable_due_to_distance | unreachable_due_to_rest_forbid | parse_or_time_bug_suspected"
}
```

## 11.3 聚合报告

每轮输出：

```text
expired_total
expired_when_first_seen
expired_after_seen
unreachable_due_to_distance
unreachable_due_to_rest_forbid
parse_or_time_bug_suspected
top lanes by expired count
top drivers by expired count
```

## 11.4 注意

不要把所有 expired 明细塞进 Advisor prompt。

只写日志和 validation report。

Advisor 最多看到压缩摘要：

```text
blocked_summary:
- many profitable candidates blocked by load_time_window_expired
- no blocked candidate is selectable
```

## 11.5 验收

- 能判断 expired 来源。
- 如果存在时间基准 bug，能定位。
- 如果是货源池问题，后续候选生成应提前过滤。
- 如果是策略错过，后续由 reposition / rate / wait gate 修复。

---

# Task 8：Advisor 输入收敛，轻量控制 token

## 12.1 目的

token 不是本阶段主目标，但不能继续无控制膨胀。

## 12.2 Advisor 只看 Top-K

默认：

```text
Top 3 cargo candidates
Top 1 wait candidate
Top 1 reposition/hold candidate
```

最多 5~7 个候选。

如果候选不足，就不补假候选。

## 12.3 hard_invalid 不进 Advisor 明细

hard_invalid 明细只进入日志。

Advisor 只看到：

```text
blocked_summary: <= 3 lines
```

## 12.4 DayPlan 复用压缩

DayPlan 创建时可以完整生成。复用时只传：

```json
{
  "day_plan_id": "...",
  "brief": [
    "prefer revenue rate",
    "avoid unnecessary wait",
    "watch active deadline goal"
  ]
}
```

最多 3 条。

## 12.5 Reflection 压缩成 flags

不要塞长篇失败历史。

改为：

```json
{
  "recent_goal_overuse": true,
  "recent_profitable_wait": true,
  "reduce_goal_urgency": true,
  "watch_specific_cargo": true
}
```

## 12.6 验收

- token 不继续明显超过 Phase 3.4.5。
- Advisor prompt 平均长度下降。
- 不为省 token 删除关键评分字段。
- 不建立复杂 token 优化模块。

---

# Task 9：Validation Report 增加关键指标

## 13.1 新增收益效率指标

```text
total_net
total_gross
total_cost
total_penalty
net_per_order
gross_per_order
avg_order_duration_minutes
avg_net_after_penalty_per_hour
```

## 13.2 新增 wait 指标

```text
wait_count
wait_ratio
wait_by_purpose
high_cost_wait_selected_count
profitable_order_but_wait_count
wait_allowed_false_but_selected_count
avg_wait_opportunity_cost
```

## 13.3 新增 goal 指标

```text
active_goal_count
selected_goal_candidate_count
selected_goal_must_do_now_count
stuck_goal_decisions
goal_overuse_count
goal_demoted_count
goal_materialized_count
goal_unavailable_tracked_count
goal_untracked_after_unavailable_count
```

## 13.4 新增 penalty trade-off 指标

```text
soft_risk_order_selected_count
soft_risk_expected_penalty_sum
soft_risk_actual_penalty_sum
net_after_expected_penalty_sum
selected_negative_after_penalty_count
selected_low_rate_order_count
```

## 13.5 新增 Advisor 偏离指标

```text
selected_vs_best_score_gap_avg
selected_vs_best_score_gap_max
selected_not_top1_count
selected_not_top1_reason_count
advisor_selected_wait_when_best_order_rate_high
```

## 13.6 新增 token 轻量指标

```text
total_tokens
avg_tokens_per_decision
advisor_prompt_tokens_avg
advisor_prompt_tokens_max
```

不需要复杂分节点 token 系统，除非实现成本很低。

---

## 14. 实施顺序

### Step 1：先加字段，不改行为

先补齐：

- net_after_expected_penalty
- duration_minutes
- net_after_expected_penalty_per_hour
- wait_opportunity_cost
- goal_progress_delta
- expected_penalty

只记录，不改变决策。

目的：确认字段合理。

### Step 2：加 validation 指标

新增 report 指标，确认当前问题的真实分布。

不要急着修 Advisor。

### Step 3：Top-K Advisor summary

把 Advisor 输入改为压缩 Top-K。

注意：这一步可能影响决策，要单独跑一轮。

### Step 4：Wait Gate

对明显无效 wait 做降级。

先从 market_wait / rest_not_urgent / profitable_order_but_wait 入手。

### Step 5：Goal Demotion

处理 stuck / overuse / unavailable。

注意不要把所有目标都削弱，只削弱不可 materialize 的目标。

### Step 6：Specific Cargo Watch + Ordered Window Hold

抽象修 D009/D010 类问题。

只做通用状态机，不做司机特判。

### Step 7：load_time_window_expired 审计

加审计，不进 prompt。

确认是否有时间解析或货源池问题。

### Step 8：最终合并跑全量实验

对比 Phase 3.4 和 Phase 3.4.5。

---

## 15. 验收标准

### 必须通过

```text
node_error = 0
final_action_missing = 0
advisor_unknown_candidate_count = 0
unknown_candidate_direct_wait_count = 0
fallback_with_profitable_order_count = 0
non_selectable_candidate_id_exposed_count = 0
```

### 收益目标

最低目标：

```text
net > 117510.55
```

理想目标：

```text
net >= 180000
```

阶段目标：

```text
稳定向 200000 靠近
```

不把 300000 作为 Phase 3.4.6 验收目标。

### penalty 目标

```text
penalty <= 121650
```

更理想：

```text
penalty 回落到 90000 附近
```

### wait 目标

```text
wait_ratio 下降
high_cost_wait_selected_count 下降
profitable_order_but_wait 下降
D001/D008/D009 wait 明显下降
```

### goal 目标

```text
selected_goal_must_do_now_count 下降
stuck_goal_decisions 下降
goal_overuse 下降
specific cargo untracked 问题消失
window hold 被破坏次数下降
```

### efficiency 目标

```text
avg_net_after_penalty_per_hour 上升
超长低效率订单减少
selected_low_rate_order_count 下降
```

### token 目标

```text
不继续明显超过 Phase 3.4.5
最好稳定在 2000 万以内
Advisor 平均 prompt 有下降
```

---

## 16. 禁止事项清单

本阶段明确禁止：

1. 禁止新增大型 Agent 模块。
2. 禁止通过更多 prompt 解释修复收益问题。
3. 禁止硬编码 D009 / D010。
4. 禁止 hard/soft 大范围继续放开。
5. 禁止让 Goal Layer 直接生成大量 critical wait。
6. 禁止让 wait 作为默认安全动作。
7. 禁止把 hard_invalid 明细塞进 Advisor。
8. 禁止让 Reflection 长历史反复进入 prompt。
9. 禁止为了 token 删除关键收益字段。
10. 禁止以“局部合理解释”掩盖总账变差。

---

## 17. 给实现 Agent 的简短执行提示词

```text
请执行 Phase 3.4.6：Decision Core 收敛与决策质量修复。

当前 Phase 3.4.5 已修掉 unknown candidate、fallback profitable、non-selectable candidate exposed 等框架错误，但收益下降：net 从 Phase 3.4 的 117510.55 降到 86067.54，gross 只增加 5909.66，cost 增加 3002.68，penalty 增加 34350。说明现在的主要问题不是框架崩溃，而是决策质量：soft risk 放开后 penalty trade-off 不足，wait 过多，goal/critical wait 抢决策权，缺少单位时间收益，D009/D010 类目标持久化不足，大量 load_time_window_expired 仍需审计。

本阶段禁止新增大型 Agent 模块，禁止硬编码司机/任务，禁止继续大范围 hard/soft 放开，禁止用更长 prompt 解释修复问题。请在现有架构内收敛 Decision Core。

重点实现：
1. 给所有进入 Advisor 的候选补齐 expected_penalty、net_after_expected_penalty、duration_minutes、net_after_expected_penalty_per_hour、goal_progress_delta、wait_opportunity_cost。
2. 建立统一 decision_score，优先考虑 net_after_expected_penalty_per_hour、total net、goal_progress、wait opportunity cost、risk uncertainty。权重放 config，不写死。
3. Advisor 只看 Top-K 压缩候选：Top 3 cargo + Top 1 wait + Top 1 reposition/hold，最多 5~7 个。
4. wait 必须有 wait_allowed、expected_progress、best_alternative_rate、wait_opportunity_cost。market_wait/rest_not_urgent/forbid_window_wait/goal_wait 如果被高收益可执行候选压过，应降级。
5. Goal Layer 做 demotion：连续不可 materialize 或 stuck 的目标降级，不允许长期 critical/must_do_now。goal 只能生成 take_order_to_progress_goal、reposition_to_progress_goal、hold_to_preserve_goal，不能泛化生成 generic critical wait。
6. 抽象修复 D009/D010 类问题：specific_cargo_watch_goal 不能从 unavailable 直接变 untracked；ordered_window_hold_goal 在进入关键窗口后要生成 hold_to_preserve_goal，并给破坏动作增加 expected_penalty。不要写 driver_id 特判。
7. 审计 load_time_window_expired，记录 current_time、load_window、ETA、first_seen_time、expired_by_minutes、reason_class，判断是货源池问题、时间解析问题、策略错过还是休息/禁行导致。
8. token 只是次要目标。简单控制即可：hard_invalid 明细不进 Advisor，DayPlan 复用只传 brief，Reflection 用短 flags，Advisor 输入 Top-K。不要做复杂 token 专项。
9. 更新 validation report，新增 wait、goal、rate、penalty trade-off、selected_vs_best_score_gap 等指标。
10. 验收：net 至少恢复到 Phase 3.4 以上，penalty 不继续恶化，wait/high_cost_wait/profitable_order_but_wait/goal_overuse/stuck_goal 下降，unknown/fallback/non-selectable 框架指标保持为 0 或安全水平。
```

---

## 18. 最终一句话

Phase 3.4.6 的本质不是“更聪明的 Agent”，而是“更清晰的决策核心”。

不要继续让系统变大。  
先让系统变稳、变清楚、变会算账。  
只有当净收益恢复到 20w 上下，且 wait / goal / penalty 不再互相拉扯后，才考虑下一阶段冲 30w。
