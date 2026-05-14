# Phase 3.4 规划：Opportunity / FutureValue / Long-term Score

## 0. 文档定位

本文档用于指导 TruckDrivers 项目从 Phase 3.3 进入 Phase 3.4。

当前已经完成：

```text
Phase 3.0     Agentic Graph Skeleton
Phase 3.0.5   Tool Layer + Diagnostic Trace + Legacy Boundary
Phase 3.1     StrategicPlannerAgent + DayPlan
Phase 3.1.5   DayPlan Quality Hardening
Phase 3.2     Goal-based Candidate Layer Refactor
Phase 3.2.5   Goal Layer Boundary Stabilization
Phase 3.3     MemoryStore + ReflectionAgent Skeleton
```

Phase 3.4 的核心目标是：

```text
让系统开始理解“当前动作对未来收益机会的影响”，
不再只依赖 immediate_net、DayPlan、Goal urgency 和 Reflection hints 做单步选择。
```

一句话概括：

```text
Phase 3.4 不是继续补 bug；
Phase 3.4 是给候选动作补上 opportunity cost、destination value 和 future value evidence。
```

---

## 1. 为什么现在进入 Phase 3.4

### 1.1 当前不是“再补一点 bug 就能冲榜”的阶段

当前 Phase 3.3 完整实验结果大致为：

```text
gross:   272332.82
cost:     83005.98
penalty:  89025.00
net:     100301.84
```

相比 Phase 3.2：

```text
Phase 3.2 net:  68634.43
Phase 3.3 net: 100301.84
delta:         +31667.41
```

这个提升说明 Phase 3.2.5 + Phase 3.3 有效修复了一些灾难性行为，尤其 D010 的 ordered/family 目标明显恢复。

但当前净收益仍与榜单 30w+ 有巨大差距。这个差距不是靠继续修 Reflection 文本、继续修某个司机局部 bug 能解决的。

当前真正缺的是：

```text
未来机会价值；
等待的机会成本；
订单终点位置价值；
specific cargo 不可见时的机会判断；
当前订单对未来约束/收益的影响；
轻量 lookahead 的基础。
```

这些正是 Phase 3.4 的范围。

### 1.2 Phase 3.3 后的小尾巴如何处理

Phase 3.3 后还有一些小问题：

```text
Reflection hint 可能重复；
profitable_order_but_wait 的原因分类还不够细；
Advisor 是否真正使用 reflection hint 的日志还不够清楚；
部分 wait 是合理等待，部分是误判等待；
D009 specific_cargo 仍然失败；
D003 / D004 / D007 / D008 等司机仍有收益回退。
```

这些不建议继续开大的 Phase 3.3.x 来逐个修。

更合理的做法：

```text
把这些小尾巴作为 Phase 3.4 的前置清理项；
只做最小修正；
不要让 Memory / Reflection 继续膨胀成新的决策大脑。
```

---

## 2. Phase 3.4 前置小修

进入正式 Opportunity / FutureValue 前，先做四个小修。

### 2.1 Reflection hint 去重 / 衰减

规则：

```text
same driver_id + same failure_type + same condition/message
=> 合并，不重复新增。
```

更新字段：

```text
count
last_seen_step
confidence
severity
evidence_refs
expires_after_steps
```

目的：

```text
避免 memory_store / reflection_hints 快速膨胀；
避免 Advisor context 被重复 hint 干扰；
避免 Reflection 变成噪声源。
```

### 2.2 profitable_order_but_wait 分类

当前 profitable_order_but_wait 太粗，要拆成：

```text
true_profitable_order_but_wait
constraint_blocked_wait
dayplan_blocked_wait
rest_required_wait
forbid_window_wait
unknown_wait
```

每条记录至少包含：

```text
best_order_net
chosen_wait_reason
blocking_constraint
dayplan_goal
rest_feasibility_after_order
goal_urgency
```

目的：

```text
不要把合理的 forbid-window wait 误判成失败；
不要让 Reflection 学到错误经验；
为 wait opportunity cost 提供干净标签。
```

### 2.3 Advisor 显式记录 Reflection 使用情况

新增字段：

```text
reflection_hint_used
reflection_hint_effect
reflection_hint_ignored_reason
```

目的：

```text
判断 Advisor 是否真的使用了 Reflection；
避免收益变化无法归因；
防止 Reflection 变成不可解释的上下文噪声。
```

### 2.4 Wait reason 标准化

标准 wait reason：

```text
no_valid_order
hard_constraint_wait
critical_goal_wait
rest_required_wait
forbid_window_wait
dayplan_wait
profitable_order_but_wait
unknown_wait
```

目的：

```text
给 Phase 3.4 的 wait_opportunity_cost 分析提供统一入口。
```

---

## 3. Phase 3.4 的核心原则

### 3.1 Opportunity / FutureValue 只能提供 evidence

Phase 3.4 不是让 Python 重新开车。

禁止：

```python
if future_value > 500:
    force_take_order()

if wait_opportunity_cost > 1000:
    ban_wait()

if destination_score > 0.8:
    return candidate
```

允许：

```text
Python 计算 future_value / opportunity_cost / destination_score；
把这些值写进 candidate facts；
Advisor / DecisionSynthesizer 根据所有证据选择 candidate；
SafetyGate 最终校验。
```

### 3.2 不回到硬规则

正确边界：

```text
Python tools：计算事实、估计分数、提供 evidence
Advisor / DecisionSynthesizer：综合 evidence，选择 candidate_id
SafetyGate：最终 hard validation
Reflection：提供历史失败提示
DayPlan：提供当日策略方向
Goal Layer：生成目标相关候选
```

一句话：

```text
Python 算证据，不开车；
Advisor 选候选，但不能编造事实；
SafetyGate 守硬约束。
```

### 3.3 不硬堆架构

Phase 3.4 第一版不要同时新增很多 Agent。

不建议一开始新增：

```text
OpportunityAnalystAgent
MarketAgent
CargoWatchAgent
FutureValueAgent
RoutingAgent
MultiAgent debate
```

第一版优先新增一个证据层：

```text
OpportunityValueTool
```

等 evidence 有效后，再考虑包装为 OpportunityAnalystAgent。

---

## 4. Phase 3.4 要解决的问题

### 4.1 wait 太多，但不知道是否合理

wait 可以分成：

```text
合法等待：没有合法订单或必须满足 hard constraint；
目标等待：等待是为了完成 high/critical urgency goal；
无货等待：当前确实没有可接货；
误判等待：有高收益合法订单但仍 wait；
过度保守等待：软偏好 / DayPlan 过强导致 wait；
机会等待：等待目标货源或未来窗口，但当前缺乏证据。
```

Phase 3.4 不应简单减少 wait，而是：

```text
计算 wait 的机会成本；
区分合理 wait 与高成本 wait；
让 Advisor 看到 wait 会错过什么。
```

### 4.2 接单只看 immediate_net 不够

两个订单可能出现：

```text
A 当前净收益高，但终点偏远，之后附近没有货；
B 当前净收益略低，但终点附近货源密集，后续机会好。
```

旧系统容易选 A。Phase 3.4 要提供：

```text
destination_opportunity_score
future_value_estimate
future_position_quality
```

让 Advisor 有能力选择长期收益更高的 B。

### 4.3 D009 specific_cargo 需要 opportunity / cargo watch 证据

D009 的 specific_cargo 失败，不是靠 Reflection 文本能解决。

当目标货不可见时，系统至少需要知道：

```text
是否应该继续接普通订单；
是否应该保持当前位置；
是否应该靠近目标区域；
等待目标货是否值得；
当前订单是否会破坏未来可达性。
```

Phase 3.4 第一版不做复杂预测，但要提供：

```text
target_cargo_visibility_status
specific_cargo_wait_cost
specific_cargo_blocked_by_current_action_risk
cargo_watch_hint
```

这些仍然是 evidence，不是强制动作。

### 4.4 成本控制仍然重要

Phase 3.4 要让系统理解：

```text
reposition 不是免费；
接低收益长距离单可能把司机送到低机会区域；
空驶到某地必须有未来机会作为支撑。
```

因此需要计算：

```text
empty_mile_cost
destination_density
reposition_expected_gain
```

---

## 5. Phase 3.4 模块设计

建议新增目录：

```text
demo/agent/phase3/opportunity/
```

建议文件：

```text
opportunity_schema.py
market_snapshot.py
wait_cost_estimator.py
destination_value_estimator.py
future_value_estimator.py
opportunity_value_tool.py
opportunity_diagnostics.py
```

---

## 5.1 opportunity_schema.py

定义 Opportunity / FutureValue 相关数据结构。

建议结构：

```python
@dataclass
class CandidateOpportunityFacts:
    candidate_id: str
    action_type: str

    immediate_net: float | None
    destination_opportunity_score: float | None
    destination_visible_cargo_count: int | None
    destination_avg_nearby_order_net: float | None

    wait_opportunity_cost: float | None
    best_forgone_order_id: str | None
    best_forgone_order_net: float | None

    future_constraint_risk: str | None
    future_value_estimate: float | None
    long_term_score_hint: float | None

    explanation: str
```

---

## 5.2 market_snapshot.py

职责：

```text
构建当前市场快照。
```

输入：

```text
current driver state
visible cargo
base candidate list
current time
driver location
```

输出：

```text
visible_cargo_count
profitable_cargo_count
best_valid_order_net
nearby_cargo_density
nearby_avg_net
time_of_day_bucket
```

第一版只用当前可见货源和候选池，不做复杂预测。

---

## 5.3 wait_cost_estimator.py

职责：

```text
估计 wait 的机会成本。
```

第一版定义：

```text
wait_opportunity_cost = 当前合法可接订单中最高 estimated_net
```

或更保守：

```text
wait_opportunity_cost = top_k 合法订单净收益的加权值
```

同时记录：

```text
best_forgone_order_id
best_forgone_order_net
profitable_order_count
```

如果当前 wait 是因为 hard constraint / critical goal，opportunity_cost 仍记录，但 Advisor 可以选择忽略。

---

## 5.4 destination_value_estimator.py

职责：

```text
估计订单终点或 reposition 目标点的机会价值。
```

第一版可以只用当前可见货源做近似：

```text
在候选动作结束位置附近 R 公里内：
  有多少货源；
  平均净收益多少；
  最高净收益多少；
  是否存在可在到达后仍能接的货；
  货源时间窗是否还来得及。
```

输出：

```text
destination_visible_cargo_count
destination_profitable_cargo_count
destination_avg_nearby_order_net
destination_best_nearby_order_net
destination_opportunity_score
future_position_quality
```

---

## 5.5 future_value_estimator.py

职责：

```text
综合 immediate_net、destination value、wait cost、future risk，生成 long_term_score_hint。
```

第一版公式可以简单：

```text
long_term_score_hint =
    immediate_net
  + alpha * destination_opportunity_value
  - beta  * wait_opportunity_cost
  - gamma * future_constraint_risk_penalty
  + delta * goal_alignment_bonus
```

注意：

```text
这是 score hint，不是 final score；
Advisor 仍然可以不选最高 long_term_score_hint；
但必须解释为什么。
```

初始建议：

```text
alpha = 0.3 ~ 0.5
beta  = 0.5 ~ 1.0
gamma = 根据 low/medium/high 映射
delta = 小值，只用于辅助
```

不要一开始调得太激进。

---

## 5.6 opportunity_value_tool.py

统一入口。

建议接口：

```python
class OpportunityValueTool:
    def build_market_snapshot(state, candidates) -> MarketSnapshot:
        ...

    def annotate_candidates(state, candidates, constraints, goals) -> list[CandidateOpportunityFacts]:
        ...

    def build_opportunity_summary(state, candidates) -> dict:
        ...
```

它做：

```text
1. 读取 candidate list；
2. 对 take_order 估计终点机会；
3. 对 wait 估计机会成本；
4. 对 reposition 估计目标点机会；
5. 给 candidate facts 增加 opportunity / future fields；
6. 生成 summary 给 Advisor。
```

它不做：

```text
选择 candidate；
删除 candidate；
强制排序；
覆盖 Advisor；
绕过 SafetyGate。
```

---

## 5.7 opportunity_diagnostics.py

输出 Phase 3.4 的验证指标。

建议统计：

```text
candidate_count_with_future_value
wait_opportunity_cost_avg
wait_opportunity_cost_sum
high_cost_wait_count
take_order_destination_value_avg
selected_long_term_score_hint
best_long_term_score_hint
selected_vs_best_long_term_gap
selected_immediate_net_vs_best_immediate_net_gap
future_value_used_in_reason_count
advisor_ignored_best_long_term_count
specific_cargo_watch_active_count
target_cargo_unavailable_but_high_wait_cost_count
```

---

## 6. Graph 流程接入

当前流程：

```text
Observe
-> Preference
-> Runtime
-> Candidate
-> Constraint
-> Planning
-> Reflection
-> Advisor
-> Safety
-> Emit
-> MemoryUpdate
```

Phase 3.4 推荐：

```text
Observe
-> Preference
-> Runtime
-> Candidate
-> Constraint
-> Planning
-> Reflection
-> Opportunity
-> Advisor
-> Safety
-> Emit
-> MemoryUpdate
```

新增一个轻量节点：

```text
OpportunityNode
```

职责：

```text
调用 OpportunityValueTool；
把 opportunity facts 写入 AgentState；
增强 candidate summaries；
不做决策。
```

不要新增多个 node。

---

## 7. Advisor 如何使用 Phase 3.4 信息

Advisor payload 新增：

```text
opportunity_summary
candidate_opportunity_facts
top_candidates_by_long_term_score_hint
high_cost_wait_warnings
destination_value_notes
```

Advisor prompt 增加：

```text
Opportunity facts are evidence, not hard rules.
Use long_term_score_hint to compare candidates, but do not select illegal candidates.
If you ignore a candidate with much higher long_term_score_hint, explain why.
If you select wait while wait_opportunity_cost is high, explain the blocking constraint or critical goal.
```

Advisor 输出增加：

```json
{
  "selected_candidate_id": "...",
  "used_opportunity_signal": true,
  "opportunity_reason": "...",
  "why_not_best_long_term_candidate": "...",
  "wait_opportunity_cost_accepted_reason": "..."
}
```

---

## 8. 必须避免的问题

### 8.1 不让 OpportunityTool 决策

禁止：

```text
OpportunityTool 直接返回 final action；
OpportunityTool 删除 wait；
OpportunityTool 强制选择 long_term_score 最高 candidate；
OpportunityTool 直接覆盖 candidate source。
```

### 8.2 不写 driver / cargo 特判

禁止：

```python
if driver_id == "D009":
    ...
if cargo_id == "240646":
    ...
```

specific cargo 必须通过通用 cargo_watch / target_cargo_unavailable signal 处理。

### 8.3 不让 FutureValue 替代 SafetyGate

无论 future_value 多高，只要 hard invalid，就不能选。

### 8.4 不让 Reflection 和 Opportunity 抢权

Reflection 提供历史失败信号。  
Opportunity 提供未来收益信号。  
DayPlan 提供当日策略信号。  
Goal Layer 提供目标候选。  
Advisor / DecisionSynthesizer 仍是唯一选择者。

---

## 9. 实施顺序

### Step 1：完成 Phase 3.3 小收口

```text
hint 去重；
wait failure 分类；
reflection 使用字段；
wait reason 标准化。
```

### Step 2：新增 opportunity schema

```text
opportunity_schema.py
```

### Step 3：实现 market snapshot

```text
market_snapshot.py
```

### Step 4：实现 wait opportunity cost

```text
wait_cost_estimator.py
```

### Step 5：实现 destination value

```text
destination_value_estimator.py
```

### Step 6：实现 long_term_score_hint

```text
future_value_estimator.py
```

### Step 7：接入 OpportunityNode / AdvisorTool

把 opportunity facts 注入 Advisor payload。

### Step 8：增强 validation

输出 Phase 3.4 指标。

### Step 9：短测 3 个司机

先看：

```text
wait_opportunity_cost 是否合理；
Advisor 是否提到 opportunity；
take_order ratio 是否上升；
high_cost_wait 是否下降；
Safety 是否稳定。
```

### Step 10：跑 6 个司机 / 全司机

再观察总收益。

---

## 10. Phase 3.4 验收标准

### 10.1 架构验收

必须满足：

```text
OpportunityTool 不生成 final_action；
OpportunityTool 不删除候选；
Advisor 仍选择 candidate_id；
SafetyGate 仍最终校验；
Reflection 不变成 score override；
无 driver_id / cargo_id 特判。
```

### 10.2 日志验收

每条决策应能看到：

```text
opportunity_summary
candidate_opportunity_facts_count
selected_candidate_long_term_score_hint
best_long_term_score_hint
selected_vs_best_long_term_gap
wait_opportunity_cost
used_opportunity_signal
why_not_best_long_term_candidate
```

### 10.3 行为验收

希望看到：

```text
high_cost_wait_count 下降；
profitable_order_but_wait 下降；
take_order ratio 上升；
selected_vs_best_long_term_gap 不明显扩大；
D009 的 target_cargo_unavailable 有更清楚的 opportunity 诊断；
gross 上升；
cost 不明显上升；
penalty 不明显反弹。
```

### 10.4 不以一次净收益作为唯一标准

Phase 3.4.0 第一版可能收益波动。

第一验收是：

```text
future value evidence 进入候选；
Advisor 能解释 opportunity trade-off；
wait 的机会成本可观测；
不破坏现有边界。
```

---

## 11. 针对 D009 的边界处理

D009 specific cargo 是当前最大失败点之一。

Phase 3.4 可以做：

```text
target_cargo_unavailable 诊断；
specific_cargo_wait_cost；
当前接单是否会破坏未来可达性；
目标货不可见时是否存在高收益替代订单；
是否长期被低价值 wait 消耗。
```

Phase 3.4 不做：

```text
预测具体 cargo_id 出现；
硬编码 D009；
硬编码 cargo 240646；
强制等待目标货；
强制靠近某个点。
```

如果没有足够信息，只能给 Advisor 提供：

```text
目标货当前不可见；
等待目标货的机会成本较高/较低；
当前高收益订单是否值得先接；
未来需要 Opportunity / CargoWatch 更强模型。
```

---

## 12. 给代码 Agent 的执行提示词

```text
现在进入 Phase 3.4：Opportunity / FutureValue / Long-term Score。

背景：
Phase 3.3 完整实验 net 从 68,634.43 恢复到 100,301.84，说明 Phase 3.2.5 + Phase 3.3 有效修复了一些灾难性行为。但当前距离榜单 30w+ 仍然很远，继续增强 Memory/Reflection 不能解决核心差距。当前最大缺口是：系统缺少 future value、wait opportunity cost、destination opportunity 和 long-term score。

本阶段目标：
给候选动作增加未来机会和机会成本证据，让 Advisor 不再只看 immediate_net / DayPlan / Goal / Reflection，而能比较长期收益。

重要边界：
1. Opportunity / FutureValue 只能提供 evidence，不能直接选动作。
2. 不写 driver_id / cargo_id 特判。
3. 不让 Python 工具变成硬规则。
4. Advisor 仍然只从 candidate_id 中选择。
5. SafetyGate 仍然最终 hard validation。
6. 不新增大量 Agent，第一版以 Tool 为主。

前置小修：
1. Reflection hint 去重/衰减。
2. profitable_order_but_wait 分类。
3. Advisor 输出 reflection_hint_used / reflection_hint_effect / reflection_hint_ignored_reason。
4. 标准化 wait reason。

新增目录：
demo/agent/phase3/opportunity/

新增文件：
- opportunity_schema.py
- market_snapshot.py
- wait_cost_estimator.py
- destination_value_estimator.py
- future_value_estimator.py
- opportunity_value_tool.py
- opportunity_diagnostics.py

实现内容：
1. MarketSnapshot：
   基于当前 visible cargo / candidate pool，计算当前市场状态。
2. WaitCostEstimator：
   对 wait candidate 估计 wait_opportunity_cost、best_forgone_order_net、profitable_order_count。
3. DestinationValueEstimator：
   对 take_order / reposition candidate 估计 destination_opportunity_score、destination_visible_cargo_count、destination_avg_nearby_order_net。
4. FutureValueEstimator：
   生成 long_term_score_hint：
   immediate_net + alpha * destination_value - beta * wait_opportunity_cost - gamma * future_constraint_risk + delta * goal_alignment。
   注意：这是 hint，不是硬排序。
5. OpportunityValueTool：
   统一为 candidates 注入 opportunity facts。
6. OpportunityNode：
   在 Advisor 前调用 OpportunityValueTool，把 facts 写入 state / Advisor payload。

Advisor 修改：
1. payload 增加 opportunity_summary、candidate_opportunity_facts、top_candidates_by_long_term_score_hint。
2. prompt 强调：
   opportunity facts 是 evidence，不是 hard rule。
   如果选择 wait 且 wait_opportunity_cost 高，必须解释 blocking constraint 或 critical goal。
   如果不选最高 long_term_score_hint candidate，必须解释 why_not_best_long_term_candidate。
3. 输出增加：
   used_opportunity_signal
   opportunity_reason
   why_not_best_long_term_candidate
   wait_opportunity_cost_accepted_reason

Validation 增加：
- candidate_count_with_future_value
- wait_opportunity_cost_avg
- wait_opportunity_cost_sum
- high_cost_wait_count
- selected_long_term_score_hint
- best_long_term_score_hint
- selected_vs_best_long_term_gap
- future_value_used_in_reason_count
- advisor_ignored_best_long_term_count
- target_cargo_unavailable_but_high_wait_cost_count

禁止：
- 不让 OpportunityTool 直接 return final action
- 不删除候选
- 不强制选择 long_term_score 最高的 candidate
- 不写 D009 / D010 / cargo_id 特判
- 不新增复杂 CargoWatchAgent / MarketAgent / MultiAgent debate
- 不进入 beam search

验收：
- compileall 通过
- opportunity tool smoke 通过
- wait candidate 能看到 wait_opportunity_cost
- take_order candidate 能看到 destination_opportunity_score
- Advisor reason 能解释 opportunity trade-off
- SafetyGate 没有被绕过
- high_cost_wait 可被 validation 统计
```

---

## 13. 最终总结

Phase 3.4 是当前最应该推进的阶段。

原因：

```text
项目已经完成基础 Agentic 框架；
Goal Layer 和 Reflection 已经让系统从灾难性错误中恢复；
但距离高分榜仍有巨大差距；
继续补 Memory/Reflection 无法解决核心收益差距；
真正缺的是 future value 和 opportunity cost。
```

Phase 3.4 要坚持：

```text
少加 Agent；
多加 evidence；
不写硬规则；
不抢决策权；
不破坏 SafetyGate；
不再围绕单个司机补丁；
让候选具备长期收益信息。
```

最终目标：

```text
让 Advisor 从“当前收益 + 当前偏好”决策，
升级为“当前收益 + 未来机会 + 机会成本 + 约束风险 + 历史经验”决策。
```
