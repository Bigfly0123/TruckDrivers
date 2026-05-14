# TruckDrivers Phase 3.1.5 指导方案：DayPlan 质量增强与 Planner 输出稳定化

## 0. 本阶段定位

Phase 3.1 已经完成第一版：

```text
StrategicPlannerAgent
DayPlan
DayPlanStore
PlanningNode
Advisor 接收 DayPlan context
trace / validation 增加 day_plan 字段
```

从实验日志看，Phase 3.1 的主链路已经跑通：

```text
observe -> preference -> runtime -> candidate -> constraint -> planning -> advisor -> safety -> emit
```

PlanningNode 已经执行，DayPlan 已经创建和复用，Advisor reason 中也已经出现了 “aligns with day plan” 等迹象。这说明 **Phase 3.1 的架构接入是成功的**。

但是第一版 DayPlan 暴露出明显质量问题：

```text
1. advisor_guidance 大部分为空；
2. risk_focus 经常为空；
3. 有些 DayPlan 太泛泛；
4. 有些 DayPlan 会强化旧的 wait/rest 保守倾向；
5. DayPlan 语言和表达不稳定；
6. validation report 对 DayPlan 质量的诊断还不够。
```

所以 Phase 3.1.5 的目标是：

```text
不新增新 Agent；
不进入 Memory / Reflection；
不做 FutureValue / Opportunity；
不修 D001/rest/time window 局部 bug；
只增强 DayPlan 的可用性、稳定性和可诊断性。
```

一句话：

```text
Phase 3.1.5 = DayPlan Quality Hardening
```

它是进入 Phase 3.2 前的必要收口。

---

## 1. 为什么需要 Phase 3.1.5

Phase 3.1 的核心目标不是让收入立刻暴涨，而是让系统具备 day-level planning 能力。

但是如果 DayPlan 输出质量不稳定，后续 Phase 3.2 的 Memory / Reflection 会建立在不稳定的 planning 上，容易出现：

```text
Reflection 复盘了一个质量很差的 DayPlan；
Memory 记住了错误策略；
后续 Planner 越调越偏；
Advisor 被空 guidance 或保守 guidance 干扰。
```

所以在进入 Phase 3.2 之前，必须先保证：

```text
DayPlan 至少稳定、非空、可读、可诊断、不会绕过 candidate_id / SafetyGate。
```

---

## 2. 本阶段核心目标

Phase 3.1.5 只做以下六件事：

```text
1. 强制 DayPlan 的 advisor_guidance 非空；
2. 强制 DayPlan 的 risk_focus 非空；
3. 统一 DayPlan 输出语言为中文；
4. 增强 StrategicPlannerAgent prompt，避免 Planner 强化旧的 wait/rest 保守倾向；
5. 增加 DayPlan 质量诊断字段；
6. 增强 validation report，判断 Phase 3.1 是否可以进入 Phase 3.2。
```

---

## 3. 本阶段绝对不要做什么

为了避免重新陷入 Phase 2 式局部 bug 修补，本阶段禁止以下事项。

### 3.1 不修局部策略 bug

不要修：

```text
D001 continuous_rest 具体计算；
D004 time window / lunch break 具体规则；
load_time_window；
partial rest candidate 生成逻辑；
ConstraintEvaluator 的 hard/soft 判定；
某个司机的某个订单选择；
某个 penalty 数值；
某个 cargo category 匹配。
```

如果日志里仍然看到 D001 wait 多、D004 wait 多，不要在本阶段修它们。

Phase 3.1.5 只修 DayPlan 输出质量。

---

### 3.2 不新增 Phase 3.2 / Phase 3.3 功能

不要新增：

```text
MemoryStore
ReflectionAgent
OpportunityAnalyst
FutureValueEstimator
LookaheadSimulator
Beam Search
Multi-agent debate
```

这些留到后续阶段。

---

### 3.3 不让 DayPlan 变成规则系统

禁止写：

```python
if "休息" in day_plan.rest_strategy:
    return wait
```

禁止写：

```python
if day_plan.primary_goal == "avoid_penalty":
    filter_out_orders()
```

禁止写：

```python
if day_plan.advisor_guidance contains "...":
    selected_candidate_id = ...
```

DayPlan 只能作为 Advisor 的上下文指导，不能直接控制 action。

正确边界仍然是：

```text
StrategicPlannerAgent -> DayPlan guidance
Advisor -> selected_candidate_id
SafetyGate -> final hard validation
```

---

## 4. 语言策略：字段名英文，字段内容中文

本阶段建议统一：

```text
JSON 字段名：英文
字段内容：中文
```

原因：

```text
1. 司机偏好和业务语义本身是中文；
2. 中文 DayPlan 更容易保持偏好语义一致；
3. 人工检查日志更方便；
4. 字段名英文可以保持程序解析稳定；
5. 后续 validation / trace 不受自然语言影响。
```

示例：

```json
{
  "strategy_summary": "今天优先在满足硬约束的前提下接取有利润的合法订单，避免在仍有赚钱机会时过早进行部分休息。",
  "primary_goal": "在满足硬约束的前提下提升当日收益",
  "risk_focus": ["连续休息", "硬约束区域", "时间窗口"],
  "advisor_guidance": [
    "最终动作必须从候选 candidate_id 中选择，不能发明动作。",
    "如果存在有利润的合法订单，且接单后仍可满足关键约束，应优先考虑订单而不是部分休息。",
    "只有当没有有利润的可接受订单，或接单会导致关键约束无法完成时，才优先选择等待或休息。",
    "任何情况下都不能为了收益违反硬约束或绕过 SafetyGate。"
  ]
}
```

注意：不要让字段名变中文，否则代码解析和 validation 会变复杂。

---

## 5. 当前实验暴露的问题

### 5.1 advisor_guidance 大部分为空

实验中 `day_plan_advisor_guidance` 非空率很低。这说明 DayPlan 虽然创建了，但最关键的 Advisor 指导项没有稳定输出。

后果：

```text
Advisor 只能从 strategy_summary / primary_goal / rest_strategy 中猜测策略；
DayPlan 对当前候选选择的影响弱；
不同 LLM 输出波动会更大；
Phase 3.1 的效果不稳定。
```

Phase 3.1.5 必须保证：

```text
advisor_guidance 非空率接近 100%。
```

---

### 5.2 risk_focus 经常为空

`risk_focus` 为空会导致 Advisor 不知道今天的重点风险是什么。

后果：

```text
Planner 生成的 DayPlan 太泛；
Advisor 无法区分今天主要该防连续休息、区域约束、时间窗口还是禁运品类；
validation report 难以判断 Planner 是否理解了约束。
```

Phase 3.1.5 必须保证：

```text
risk_focus 至少包含 1 条，最多 5 条。
```

---

### 5.3 DayPlan 有时强化 wait/rest 保守倾向

部分 DayPlan 会写：

```text
优先完成连续休息
尽早安排 8 小时休息
当前重点是避免罚金
```

这在某些场景下是合理的，但如果系统本来就有“过度休息”倾向，Planner 可能会强化旧问题。

Phase 3.1.5 不是要修 continuous_rest 计算，而是要让 DayPlan 增加一个通用原则：

```text
部分休息只是进度，不等于已经避免罚金。
如果存在有利润的合法订单，且接单后仍能完成关键约束，则不应机械地优先部分休息。
```

这个原则是通用的，不是 D001 特判。

---

### 5.4 DayPlan 诊断不足

当前 validation report 应进一步统计：

```text
day_plan_empty_guidance_count
day_plan_empty_risk_focus_count
advisor_chose_wait_despite_profitable_order count by driver
day_plan_fallback_count
day_plan_language_mismatch_count
```

这些指标用于判断：

```text
Phase 3.1 是否稳定；
是否可以进入 Phase 3.2；
是否 DayPlan 只是形式上存在但质量不够。
```

---

## 6. 具体修改要求

## 6.1 修改 StrategicPlannerAgent Prompt

位置可能是：

```text
demo/agent/phase3/agents/strategic_planner_agent.py
```

需要强化 prompt。

### 6.1.1 输出语言要求

加入：

```text
请使用中文填写所有自然语言字段。
JSON 字段名必须保持英文。
不要输出 Markdown，不要输出解释文字，只输出 JSON。
```

### 6.1.2 advisor_guidance 要求

加入：

```text
advisor_guidance 必须包含 3-5 条具体指导。
每条指导必须能帮助 Advisor 在候选 candidate_id 之间做选择。
指导必须保持通用，不得指定具体 candidate_id、cargo_id 或 action id。
```

### 6.1.3 risk_focus 要求

加入：

```text
risk_focus 必须包含 1-5 个今日主要风险。
风险可以来自硬约束、软偏好、候选诊断、dominant_hard_invalid_reason 或 runtime_state。
```

### 6.1.4 防止 DayPlan 变成最终动作

加入：

```text
你不能输出 candidate_id、cargo_id、order_id 或 final action。
你只能输出 day-level strategy guidance。
最终动作由 Advisor 从候选列表中选择，并由 SafetyGate 校验。
```

### 6.1.5 防止过度 wait/rest

加入：

```text
如果候选诊断显示存在有利润的合法订单，不要建议机械等待或过早部分休息。
部分休息只是进度，不代表已经避免罚金。
如果接单后仍可满足关键约束，应建议 Advisor 优先考虑有利润的合法订单。
```

### 6.1.6 中文 prompt 示例

可以在 planner prompt 中加入：

```text
你是一个货运司机的日级策略规划 Agent。你的任务不是选择具体订单，而是生成今天的策略指导。

请遵守：
1. 只输出 JSON；
2. JSON 字段名使用英文；
3. 字段内容使用中文；
4. 不要输出 candidate_id、cargo_id、order_id 或 final action；
5. 不要绕过候选池、硬约束或 SafetyGate；
6. advisor_guidance 必须有 3-5 条；
7. risk_focus 必须有 1-5 条；
8. 如果存在有利润的合法订单，且接单后仍可满足关键约束，不要建议机械等待或过早部分休息；
9. 部分休息只是进度，不等于已经避免罚金。
```

---

## 6.2 修改 DayPlan parser / normalizer

位置可能是：

```text
demo/agent/phase3/planning/day_plan.py
```

需要增加 normalize 逻辑，确保即使 LLM 输出不完整，DayPlan 也不会空。

建议新增方法：

```python
def normalize(self, context: dict | None = None) -> "DayPlan":
    ...
```

或者在 `from_json()` / `from_dict()` 中自动 normalize。

---

### 6.2.1 advisor_guidance 为空时自动补默认值

如果 LLM 返回：

```python
advisor_guidance = []
```

或字段缺失，则自动补：

```python
DEFAULT_ADVISOR_GUIDANCE_CN = [
    "最终动作必须从候选 candidate_id 中选择，不能发明动作。",
    "如果存在有利润的合法订单，且接单后仍可满足关键约束，应优先考虑订单而不是等待或部分休息。",
    "只有当没有有利润的可接受订单，或接单会导致关键约束无法完成时，才优先选择等待或休息。",
    "任何情况下都不能为了收益违反硬约束或绕过 SafetyGate。"
]
```

注意：这是 DayPlan 质量兜底，不是策略规则。

---

### 6.2.2 risk_focus 为空时自动补默认值

如果 `risk_focus` 为空，优先从上下文补：

```text
constraint_summary.dominant_hard_invalid_reason
runtime_state 中的 active constraints
state.constraints 的 constraint_type
diagnostics 中的 warning
```

如果仍无法推断，则使用：

```python
DEFAULT_RISK_FOCUS_CN = ["硬约束", "候选可行性", "收益与等待权衡"]
```

如果能从 constraint type 映射，则建议中文化：

```python
RISK_LABELS_CN = {
    "continuous_rest": "连续休息",
    "operate_within_area": "硬约束区域",
    "forbid_action_in_time_window": "时间窗口",
    "forbid_cargo_category": "禁运品类",
    "max_distance": "最大距离",
    "load_time_window": "装货时间窗",
}
```

---

### 6.2.3 primary_goal 为空时自动补默认值

如果为空，补：

```text
在满足硬约束的前提下提升当日收益
```

---

### 6.2.4 strategy_summary 为空时自动补默认值

如果为空，补：

```text
今天在严格遵守硬约束和 SafetyGate 的前提下，优先选择有利润的合法候选，并避免不必要的等待。
```

---

### 6.2.5 rest_strategy 的通用兜底

如果 DayPlan 涉及 continuous_rest 或 risk_focus 包含连续休息，应确保 rest_strategy 中包含类似含义：

```text
部分休息只是进度，不等于已经避免罚金；如果存在有利润的合法订单且后续仍可完成必要休息，不应机械优先部分休息。
```

注意：这不是修改 continuous_rest 判定，只是给 Advisor 的计划指导。

---

## 6.3 修改 StrategicPlannerAgent fallback DayPlan

LLM 失败或 JSON 解析失败时 fallback DayPlan 应该是中文，并且必须包含：

```text
strategy_summary
primary_goal
risk_focus
advisor_guidance
fallback_used = true
```

示例：

```python
DayPlan(
    driver_id=state.driver_id,
    day=state.current_day,
    strategy_summary="今天在满足硬约束的前提下，优先选择有利润的合法候选，并避免不必要的等待。",
    primary_goal="在满足硬约束的前提下提升当日收益",
    risk_focus=["硬约束", "候选可行性", "收益与等待权衡"],
    advisor_guidance=[
        "最终动作必须从候选 candidate_id 中选择，不能发明动作。",
        "如果存在有利润的合法订单，且接单后仍可满足关键约束，应优先考虑订单而不是等待或部分休息。",
        "只有当没有有利润的可接受订单，或接单会导致关键约束无法完成时，才优先选择等待或休息。",
        "任何情况下都不能为了收益违反硬约束或绕过 SafetyGate。"
    ],
    fallback_used=True,
    reason="LLM 失败或 JSON 解析失败，使用默认日级策略计划。"
)
```

---

## 6.4 修改 PlanningNode

位置可能是：

```text
demo/agent/phase3/graph_nodes/planning_node.py
```

PlanningNode 需要确保：

```text
1. 每次写入 state.day_plan 的都是 normalized DayPlan；
2. planning_summary 中记录 advisor_guidance_count；
3. planning_summary 中记录 risk_focus_count；
4. planning_summary 中记录 fallback_used；
5. planning_summary 中记录 language = "zh";
6. day_plan_created / reused trace 中包含 guidance_count 和 risk_focus_count。
```

示例 summary：

```python
{
    "day_plan_created": True,
    "day": state.current_day,
    "strategy_summary": plan.strategy_summary,
    "primary_goal": plan.primary_goal,
    "risk_focus": plan.risk_focus,
    "risk_focus_count": len(plan.risk_focus),
    "advisor_guidance_count": len(plan.advisor_guidance),
    "fallback_used": plan.fallback_used,
    "language": "zh"
}
```

---

## 6.5 修改 AdvisorTool / Advisor Context

Advisor 已经接收 DayPlan，但需要确认传入的是 normalized context。

要求：

```text
1. Advisor context 中的 day_plan 使用 plan.to_advisor_context()；
2. 其中必须包含 advisor_guidance；
3. 其中必须包含 risk_focus；
4. 如果 day_plan 缺失，应使用 fallback default context；
5. Advisor prompt 明确 day_plan 是中文策略指导。
```

Advisor prompt 可以保留英文主提示，但 DayPlan section 应允许中文：

```text
DAY PLAN GUIDANCE:
The following day-level guidance is written in Chinese because driver preferences are written in Chinese.
Use it as strategy guidance only.
It does not override hard constraints, candidate list, or SafetyGate.
Final answer must still choose one selected_candidate_id from the provided candidates.

{day_plan}
```

---

## 6.6 修改 Trace / agent_decisions.jsonl

每步 final decision summary 增加或确保存在：

```text
day_plan_summary
day_plan_primary_goal
day_plan_risk_focus
day_plan_rest_strategy
day_plan_advisor_guidance
day_plan_guidance_count
day_plan_risk_focus_count
day_plan_fallback_used
day_plan_language
day_plan_generated_this_step
```

其中：

```text
day_plan_guidance_count 应大多数 > 0
day_plan_risk_focus_count 应大多数 > 0
day_plan_language 应为 zh
```

---

## 6.7 修改 Validation Report

位置可能是：

```text
demo/agent/phase3/validation/validate_phase3_run.py
```

新增统计：

```text
day_plan_empty_guidance_count
day_plan_empty_risk_focus_count
day_plan_guidance_present_rate
day_plan_risk_focus_present_rate
day_plan_fallback_count
day_plan_language_mismatch_count
advisor_chose_wait_despite_profitable_order_by_driver
decisions_with_day_plan_guidance
decisions_missing_day_plan_guidance
```

建议在 report 中新增 section：

```markdown
## DayPlan Quality

| metric | value |
|---|---|
| decisions_with_day_plan | ... |
| day_plan_empty_guidance_count | ... |
| day_plan_guidance_present_rate | ... |
| day_plan_empty_risk_focus_count | ... |
| day_plan_risk_focus_present_rate | ... |
| day_plan_fallback_count | ... |
| language_mismatch_count | ... |
```

新增 acceptance：

```text
day_plan_guidance_present_rate >= 0.95
day_plan_risk_focus_present_rate >= 0.90
node_error_count == 0
final_action_missing == 0
planner_fallback_count not excessive
```

注意：这些阈值可以先只是 report 中提示，不一定直接让程序 fail。

---

## 7. 测试策略

### 7.1 不需要一上来完整跑全量

Phase 3.1.5 是 DayPlan 质量修正，不需要立刻跑完整 31 天全量。

建议：

```text
1. syntax / import 检查；
2. 单司机短测；
3. 四司机短测；
4. validation report；
5. 如果 DayPlan 质量指标达标，再决定是否全量跑。
```

---

### 7.2 推荐先测 D001

D001 最容易暴露：

```text
DayPlan 是否过度鼓励休息；
advisor_guidance 是否包含“有利润合法订单优先”；
Advisor 是否仍然在有 profitable valid order 时大量 wait。
```

但是注意：

```text
不要因为 D001 仍然 wait 多就修 continuous_rest。
只看 DayPlan 质量指标是否改善。
```

---

### 7.3 四司机短测指标

重点看：

```text
day_plan_guidance_present_rate
day_plan_risk_focus_present_rate
advisor_chose_wait_despite_profitable_order
fallback_used
node_error
safety_reject
final_action_missing
```

希望看到：

```text
advisor_guidance 非空率接近 100%
risk_focus 非空率明显提升
node_error = 0
final_action_missing = 0
fallback 不异常
```

如果 `advisor_chose_wait_despite_profitable_order` 略降，是好信号；如果没降，也不必阻塞进入 Phase 3.2，只要 DayPlan 质量达标。

---

## 8. 验收标准

Phase 3.1.5 完成的最低标准：

```text
1. StrategicPlannerAgent prompt 明确中文输出；
2. DayPlan advisor_guidance 必须非空；
3. DayPlan risk_focus 必须非空；
4. fallback DayPlan 是中文且包含 guidance；
5. DayPlan parser / normalizer 能自动补空字段；
6. agent_decisions.jsonl 有 guidance_count / risk_focus_count / language / fallback_used；
7. validation report 能统计 DayPlan quality；
8. 四司机短测 node_error = 0；
9. final_action 仍来自 candidate_id；
10. SafetyGate 仍最终校验；
11. 没有新增 MemoryStore / ReflectionAgent / OpportunityAnalyst / FutureValueEstimator；
12. 没有修 D001/rest/time window 局部策略 bug；
13. DayPlan 没有变成 Python 规则系统。
```

---

## 9. 完成后是否可以进入 Phase 3.2

如果满足以下条件，可以进入 Phase 3.2：

```text
1. DayPlan 能稳定生成或 fallback；
2. advisor_guidance 非空率接近 100%；
3. risk_focus 非空率明显提升；
4. Advisor context 中确实包含 DayPlan；
5. validation report 能自动诊断 DayPlan 质量；
6. 没有框架级错误；
7. DayPlan 没有绕过 candidate_id / SafetyGate；
8. 四司机短测稳定。
```

不要求：

```text
总收入一定提升；
D001 rest 问题完全消失；
D004 wait 问题完全消失；
advisor_chose_wait_despite_profitable_order 必须归零。
```

这些要到 Phase 3.2 / 3.3 继续处理。

---

## 10. 给代码 Agent 的完整执行提示词

可以直接复制以下内容给代码 Agent：

```text
现在进入 TruckDrivers Phase 3.1.5。目标是修正 Phase 3.1 第一版 DayPlan 质量问题，为 Phase 3.2 做准备。

实验显示：
1. PlanningNode 已接入；
2. DayPlan 已创建和复用；
3. Advisor 已受到 DayPlan 影响；
4. 但 advisor_guidance 大部分为空；
5. risk_focus 经常为空；
6. 部分 DayPlan 会强化 wait/rest 保守倾向；
7. DayPlan 语言不够稳定。

本阶段只做 DayPlan Quality Hardening，不要新增 Phase 3.2/3.3 功能，不要修 D001/rest/time window 局部策略 bug。

请修改：

1. StrategicPlannerAgent prompt：
   - 明确要求 JSON 字段名英文，字段内容中文；
   - 只输出 JSON，不输出 markdown；
   - advisor_guidance 必须包含 3-5 条具体指导；
   - risk_focus 必须包含 1-5 条风险；
   - 不允许输出 candidate_id / cargo_id / order_id / final action；
   - 不允许绕过候选池 / SafetyGate；
   - 如果存在有利润的合法订单且接单后仍可满足关键约束，不要建议机械等待或过早部分休息；
   - 部分休息只是进度，不等于已经避免罚金。

2. DayPlan parser / normalizer：
   - 如果 advisor_guidance 为空，自动填充中文默认 guidance；
   - 如果 risk_focus 为空，根据 constraint_summary / dominant_hard_invalid_reason / runtime_state / constraints 自动补充；
   - 如果 primary_goal 为空，补“在满足硬约束的前提下提升当日收益”；
   - 如果 strategy_summary 为空，补默认中文 summary；
   - 如果涉及连续休息，在 rest_strategy 中加入通用原则：部分休息只是进度，如果仍可后续完成休息，不应机械优先部分休息。

3. fallback DayPlan：
   - 使用中文；
   - 必须包含 strategy_summary / primary_goal / risk_focus / advisor_guidance；
   - fallback_used = true。

4. PlanningNode：
   - 写入 normalized DayPlan；
   - planning_summary 增加 advisor_guidance_count、risk_focus_count、fallback_used、language="zh"。

5. AdvisorTool / Advisor context：
   - 确保传入 normalized day_plan.to_advisor_context()；
   - Advisor prompt 说明 DayPlan 是中文策略指导，只能作为 guidance，不能覆盖 hard constraints / candidate list / SafetyGate。

6. Trace / agent_decisions.jsonl：
   增加或确保：
   - day_plan_guidance_count
   - day_plan_risk_focus_count
   - day_plan_fallback_used
   - day_plan_language
   - day_plan_advisor_guidance
   - day_plan_risk_focus

7. validate_phase3_run.py：
   增加：
   - day_plan_empty_guidance_count
   - day_plan_empty_risk_focus_count
   - day_plan_guidance_present_rate
   - day_plan_risk_focus_present_rate
   - day_plan_fallback_count
   - day_plan_language_mismatch_count
   - advisor_chose_wait_despite_profitable_order_by_driver

禁止：
- 不新增 MemoryStore / ReflectionAgent；
- 不新增 OpportunityAnalyst / FutureValueEstimator；
- 不做 lookahead / beam search；
- 不修 continuous_rest / D001 / D004 / time window；
- 不重写 CandidateFactBuilder / ConstraintEvaluator；
- 不让 DayPlan 变成 Python 规则系统；
- 不让 StrategicPlannerAgent 输出 final action；
- 不让 fallback 负责赚钱。

验收：
1. syntax ok；
2. 四司机短测 node_error = 0；
3. final action 仍来自 candidate_id；
4. SafetyGate 仍最终校验；
5. advisor_guidance 非空率接近 100%；
6. risk_focus 非空率明显提升；
7. validation report 能输出 DayPlan Quality section；
8. 没有引入 Phase 3.2+ 功能。
```

---

## 11. 总结

Phase 3.1.5 是一个必要的小阶段。

它不是“又开始修小 bug”，而是让 Phase 3.1 的核心产物 DayPlan 真正可用。

做完以后，项目应该达到：

```text
DayPlan 稳定生成；
DayPlan 内容中文可读；
advisor_guidance 非空；
risk_focus 非空；
Planner 不输出 action；
Advisor 仍选 candidate_id；
SafetyGate 仍最终校验；
validation report 能判断 DayPlan 质量。
```

达到这些条件后，就有很大概率可以进入 Phase 3.2：

```text
MemoryStore + ReflectionAgent
```
