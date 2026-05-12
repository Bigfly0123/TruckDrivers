# 司机找货 Agentic AI 架构规划

## 1. 最终目标

我们要做的不是一个“把公开数据规则写全”的规则系统，而是一个能面对未知司机偏好、未知货源分布、隐藏规则变化仍然能自我判断的驾驶调度 Agent。

目标架构是：

```text
Observe -> Understand -> Build Facts -> Deliberate -> Act -> Verify -> Learn
```

核心原则：

- **LLM 负责理解与权衡**：理解偏好文本、识别任务结构、判断当前局面、在候选动作之间做 trade-off。
- **程序负责事实与安全**：接口取数、距离/时间/收益计算、动作格式校验、不可违反的硬安全底线。
- **不要为每种偏好写一个 if-else 执行器**：新偏好不能靠新增 `if rule.kind == ...` 才能工作。
- **不要按公开数据补洞**：不写司机 ID、货号、公开坐标、公开时间窗口的特殊处理。
- **减少非必要规则编码**：只保留通用物理约束和接口约束，策略判断逐步交给 Agent。
- **目标效果**：隐藏数据也能稳定跑完，偏好罚分低，收入稳定向 20w+ 靠近。

## 2. 当前架构的真实状态

当前代码已经有一些 Agentic 组件，但核心还没有完全转向 Agentic。

当前链路大致是：

```text
get_driver_status / query_cargo / query_decision_history
  -> PreferenceCompiler / LlmPreferenceAgent
  -> LlmMissionPlanner + task_graph_builder
  -> MissionExecutor
  -> PlannerScorer
  -> CandidateSafetyFilter / SafetyGate
  -> LlmDecisionAdvisor
  -> ActionContract
```

问题在于：LLM 不是没有用，而是它的权限不够清晰。很多关键策略仍然藏在 Python 分支里。

现在更像：

```text
LLM 做偏好解析和部分仲裁
Python 按 rule.kind / mission_id / action_type 写大量策略
SafetyGate 再按任务类型拦截
Advisor 只能在程序给出的有限候选里选择
```

这导致几个后果：

- 代码越来越长，模块越来越多，但谁真的有用不清楚。
- 新偏好出现时，如果没有对应 `rule.kind` 分支，就无法执行。
- Planner 经常把候选全部过滤掉，LLM 没有真实决策空间。
- SafetyGate 经常把 Advisor 的动作打回 wait，形成死循环。
- 每次大改容易性能倒退，因为新规则和旧规则互相约束。
- 这不是稳定的 Agentic AI，而是“LLM 外壳 + 规则内核”。

## 3. 模块级问题诊断

### 3.1 PreferenceCompiler / LlmPreferenceAgent

已有价值：

- LLM 解析中文偏好是正确方向。
- 解析结果缓存也是正确方向。
- 保留结构化字段是必要的，因为程序需要知道地点、时间、罚金、距离限制等事实。

当前问题：

- `LlmPreferenceAgent` 的 schema 仍然强依赖枚举类型，比如 `home_nightly`、`special_cargo`、`multi_step_task`、`visit_point`。
- 这些枚举本身不一定错，但如果后续执行层也按这些枚举写死逻辑，就会变成规则编码。
- 旧版 `PreferenceCompiler` 曾经有大量正则 fallback，这类数据格式补洞必须避免。

优化方向：

- 保留 LLM-first。
- `kind` 只作为“语义标签”，不能作为执行策略分支的唯一依据。
- 让 LLM 输出更通用的任务原语，而不是只输出固定 rule kind。
- 推荐目标 schema：

```json
{
  "intent": "avoid|require|prefer|complete_task|budget_limit|rest|time_lock",
  "priority": "hard|soft",
  "penalty_amount": 0,
  "constraints": [
    {
      "type": "time_window|deadline|location|stay_duration|cargo_identity|distance_budget|cargo_category|area",
      "fields": {}
    }
  ],
  "task_steps": [
    {
      "action": "go_to_point|wait_until|stay_within_radius|take_specific_cargo|avoid_action",
      "point": null,
      "deadline": null,
      "duration_minutes": null,
      "cargo_id": null
    }
  ],
  "reasoning_notes": "LLM explains how this preference affects decisions"
}
```

注意点：

- 不要再补“某种中文格式”的正则。
- 可以保留通用数字、时间、坐标解析，但只能作为 LLM 失败时的事实提取，不得生成特化策略。

### 3.2 task\_graph\_builder

已有价值：

- 把复杂偏好变成步骤图是正确方向。
- Agent 需要任务计划，而不是只看单步收益。

当前问题：

- 历史上按 `_RULE_BUILDERS` 映射不同 `rule.kind`，这是典型枚举执行器。
- 如果新增一种偏好，必须新增 builder 才能执行。
- 这会把 Agentic 能力锁死在已知任务类型里。

优化方向：

- 任务构建必须字段驱动，而不是类型驱动。
- 只认通用任务原语：

```text
go_to_point
wait_until
wait_duration
stay_within_radius
take_specific_cargo
avoid_action
```

- LLM 负责把偏好翻译成这些任务原语。
- Python 只负责把原语转换成可执行 MissionPlan。

禁止方向：

```python
if rule.kind == "home_nightly": ...
if rule.kind == "family_task": ...
if rule.kind == "special_cargo": ...
```

推荐方向：

```python
if rule.task_steps:
    build_steps(rule.task_steps)
elif has_location_and_deadline(rule):
    build_deadline_point_task(rule)
elif has_cargo_identity(rule):
    build_specific_cargo_task(rule)
```

这不是按偏好名字分支，而是按通用字段能力分支。

### 3.3 MissionExecutor

已有价值：

- 通用动作原语执行器是必要的。
- 它负责把 `go_to_point`、`wait_until`、`take_specific_cargo` 等任务原语转成动作。

当前问题：

- 仍有一些按 mission id 或特殊 lock 语义写死的逻辑。
- 对任务卡住后的处理偏保守，容易标记 expired 或反复 wait。
- 执行器有时承担了“策略判断”，而不只是“执行当前任务步骤”。

优化方向：

- MissionExecutor 只执行步骤，不判断商业策略。
- 如果任务卡住，不在 executor 内部靠 if-else 猜解决办法，而是生成 `MissionBlockedReport` 交给 LLM Replanner。
- Replanner 输出新的通用步骤。

推荐接口：

```text
execute_step(step, state, visible_cargo) -> action | blocked_report
```

blocked\_report 示例：

```json
{
  "blocked_step": "take_specific_cargo",
  "reason": "target cargo not visible",
  "elapsed_wait_minutes": 360,
  "visible_nearby_cargo_count": 42,
  "deadline_minutes_left": 180,
  "suggested_questions_for_llm": [
    "continue waiting?",
    "move closer?",
    "abandon mission?",
    "take alternative profit?"
  ]
}
```

### 3.4 PlannerScorer

这是当前最大问题之一。

已有价值：

- 计算候选货物的距离、时间、收益、装货窗口、完单时间，这些是必要事实。
- 给 LLM 提供候选表是必要的。

当前问题：

- `PlannerScorer` 不只是事实计算器，它仍然是半个策略引擎。
- 内部大量 `rule.kind` 分支会决定风险、过滤、reposition、机会价值。
- 它会把候选全过滤掉，让 LLM 只能在 wait 里打转。
- 评分公式固定，无法适配隐藏偏好和新场景。
- 它把“是否值得冒险”提前替 LLM 决定了。

典型问题模式：

```python
if rule.kind == "home_nightly": ...
if rule.kind == "first_order_deadline": ...
if rule.kind == "max_daily_orders": ...
if rule.kind == "max_monthly_deadhead": ...
```

其中一部分属于必要事实计算，一部分属于策略判断。需要拆开。

应该保留的事实计算：

- 到装货点距离
- 到装货点时间
- 是否赶得上装货窗口
- 是否超过 remove\_time
- 预计完单时间
- 预计毛收入
- 预计空驶成本
- 预计干线距离
- 候选动作对累计预算的边际消耗
- 候选动作可能影响哪些偏好

应该交给 LLM 的策略判断：

- 是否为了高收益接受 soft penalty
- 月度预算快耗尽时是继续保护偏好还是接受罚分赚钱
- 当前是等待新货、接最小风险货，还是执行任务移动
- 某个 deadline 还有多久时应放弃普通收益
- 多个偏好冲突时优先哪个

目标改造：

```text
PlannerScorer -> CandidateFactBuilder
```

输出不应该是“可执行/不可执行”的强判断，而应该是事实表：

```json
{
  "action": "take_order",
  "cargo_id": "xxx",
  "estimated_profit": 1200,
  "pickup_deadhead_km": 8.4,
  "haul_distance_km": 56.0,
  "finish_minute": 12345,
  "violations": [
    {
      "constraint_id": "monthly_deadhead",
      "severity": "soft",
      "estimated_penalty": 300,
      "marginal_overage": 1.5,
      "explanation": "would exceed cumulative budget by 1.5km"
    }
  ],
  "hard_invalid_reasons": []
}
```

只有这类情况可以程序硬过滤：

- 货源不存在或不可见。
- 装货窗口已经不可能赶上。
- remove\_time 已过或到达前会下架。
- 完单超过仿真结束。
- 动作格式不合法。

其他“偏好风险”原则上不要过滤，只给 LLM 决策。

### 3.5 CandidateSafetyFilter

已有价值：

- 可以在最终执行前过滤明显非法动作。

当前问题：

- 它现在可能把 Advisor 应该看到的候选提前拿掉。
- 如果所有货都带 soft risk，它会让系统进入全 wait。

优化方向：

- CandidateSafetyFilter 只过滤 hard invalid。
- Soft risk 候选必须保留给 Advisor。
- 输出候选池分层：

```text
valid_candidates
soft_risk_candidates
hard_invalid_candidates
```

LLM 至少要能看到：

- 最好的安全货
- 最好的软风险货
- 被硬过滤的代表样本和原因

### 3.6 SafetyGate

已有价值：

- Agentic AI 也需要 SafetyGate。
- LLM 不能直接批准非法动作。
- SafetyGate 是最后一道动作合法性校验。

当前问题：

- 历史上 SafetyGate 混入了任务特化和业务白名单。
- 如果 SafetyGate 按 `home_nightly/family_task/special_cargo` 放行或拒绝，就变成策略器。
- Advisor 选出的动作经常被它改成 wait，造成 LLM 和执行不一致。

SafetyGate 应该只做：

- action schema 是否合法。
- cargo\_id 是否在当前可见候选里。
- reposition 坐标是否合法。
- wait 时长是否合法。
- 当前是否处于明确 hard lock，动作是否会打破 hard lock。
- 是否违反不可执行的物理/接口约束。

SafetyGate 不应该做：

- 选择哪个偏好优先。
- 判断 soft penalty 是否值得。
- 按任务类型白名单放行。
- 根据公开数据经验决定等待多久。
- 把所有不确定动作都改成 wait。

原则：

```text
SafetyGate can veto illegal actions.
SafetyGate should not choose strategy.
```

如果 SafetyGate 拒绝动作，必须返回结构化拒绝原因给 Advisor，下次让 Advisor 重新决策，而不是静默改成 wait。

### 3.7 LlmDecisionAdvisor

这是未来 Agentic 能力的核心。

已有价值：

- 已经能在关键场景调用 LLM。
- 已经不是 token=0 的纯规则系统。

当前问题：

- Advisor 的候选空间经常被 Planner/SafetyGate 限死。
- prompt 仍然偏保守，有时一直选择 wait。
- 对累计预算、等待机会成本、长期收益规划理解不足。
- LLM 输出的理由没有被系统稳定用于下一步改进。

优化方向：

Advisor 必须成为“关键决策脑”，输入包括：

- 原始偏好文本
- 结构化约束
- 当前状态
- 历史摘要
- 候选动作事实表
- soft risk 候选
- hard invalid 代表样本
- 任务进度
- wait streak / deadlock 诊断
- 已发生的 SafetyGate 拒绝原因

Advisor 输出不仅是动作，还应包含：

```json
{
  "decision": "choose_candidate|override_wait|request_replan",
  "selected_candidate_id": 3,
  "policy_mode": "profit|protect_preference|mission|recovery|rest|budget_tradeoff",
  "accepted_risks": [],
  "rejected_alternatives": [],
  "next_check_condition": "new cargo appears or 180 minutes passed",
  "reason": "..."
}
```

关键提示词原则：

- 不要默认保护所有 soft preference；要比较收益和罚分。
- 累计预算不会日内恢复，不能等待“预算重置”。
- 长时间等待本身是机会成本。
- 如果候选都有 soft risk，应该选择最小净损失或最高净收益，而不是一直 wait。
- 如果 SafetyGate 拒绝过某类动作，下一次必须解释如何避免同一拒绝。

### 3.8 LlmMissionPlanner / MissionReplanner

已有价值：

- 复杂任务必须由 LLM 规划，这是正确方向。

当前问题：

- LLM 计划如果漏掉任务，Python fallback 又会按规则补任务，容易回到枚举系统。
- Replanner 触发条件仍然偏程序化，且没有充分利用失败上下文。

优化方向：

- MissionPlanner 直接输出通用步骤图。
- Replanner 输入必须包含失败原因，而不是只说“卡住了”。
- 如果 LLM 没规划出复杂任务，应该二次追问 LLM，而不是马上用 Python 枚举 fallback。

推荐流程：

```text
LLM mission plan
  -> validate generic steps
  -> if missing obvious high-penalty raw preference:
       ask LLM repair plan with explicit missing preference
  -> only if LLM unavailable:
       conservative generic fallback
```

### 3.9 FactCollector / SituationAnalyzer

已有价值：

- Agent 需要局面摘要。

当前问题：

- 当前 FactCollector 仍有 `home_pressure/rest_pressure/budget_pressure` 这类程序判断。
- 这些可以作为事实摘要，但不能直接决定动作。

优化方向：

- SituationAnalyzer 不应输出策略结论，只输出事实和异常信号。
- 例如：

```json
{
  "wait_streak": 12,
  "visible_cargo_count": 100,
  "safe_candidate_count": 0,
  "soft_risk_candidate_count": 26,
  "dominant_soft_risk": "monthly_deadhead_budget",
  "budget_status": {
    "used": 99.7,
    "limit": 100,
    "remaining": 0.3,
    "reset": "end_of_month"
  },
  "diagnosis_candidates": [
    "over_conservative_filtering",
    "budget_exhausted",
    "waiting_will_not_repair_budget"
  ]
}
```

注意：诊断可以提示，但最后选择交给 Advisor。

### 3.10 ActionContract

已有价值：

- 保证最终 action 格式正确。
- 防止重复原地 reposition、非法 cargo\_id、超长 wait。

当前问题：

- 如果它擅自夹断 Advisor 的等待时间，会造成“LLM 计划”和“实际执行”不一致。
- 它不应该做策略，只应该做协议约束。

优化方向：

- ActionContract 只做动作协议和边界限制。
- 如果需要修改动作，必须记录 `contract_rewrite_reason`。
- 这个原因要反馈给下一轮 Advisor。

## 4. 新目标架构

推荐目标架构如下：

```text
ModelDecisionService.decide(driver_id)
  |
  |-- Observe
  |     get_driver_status
  |     query_cargo
  |     query_decision_history
  |
  |-- Understand
  |     LlmPreferenceAgent
  |     LlmMissionPlanner
  |     StateTracker
  |
  |-- Build Facts
  |     CandidateFactBuilder
  |     ConstraintFactBuilder
  |     SituationAnalyzer
  |
  |-- Deliberate
  |     LlmDecisionAdvisor
  |     LlmMissionReplanner when task is blocked
  |
  |-- Act
  |     MissionExecutor for selected mission step
  |     SafetyGate for hard legality
  |     ActionContract for API schema
  |
  |-- Learn
        Runtime memory for generic lessons, not public data memorization
```

关键变化：

```text
从：rule.kind -> Python if-else -> action
到：raw preference + structured facts -> LLM deliberation -> checked action
```

## 5. 什么是允许的规则，什么是不允许的规则

### 允许保留的程序规则

这些是物理事实、接口事实、法律边界，不属于“策略硬编码”：

- 距离计算。
- 时间窗可达性计算。
- remove\_time 是否过期。
- 货源是否当前可见。
- action schema 是否合法。
- 仿真结束前是否能完成。
- 当前 hard lock 是否禁止离开。
- 坐标是否合法。
- 预算边际消耗计算。
- 收益成本计算。

### 需要逐步删除或收权的规则

这些是策略，不应该由 Python 固定写死：

- `if rule.kind == "home_nightly"` 就强制某种动作。
- `if rule.kind == "special_cargo"` 就走专门流程。
- `if wait_streak > N` 就无条件接风险货。
- `if budget_pressure == urgent` 就永远 wait。
- `if daily_rest_missing` 就固定等多久。
- 为某类偏好写特定 reposition 目标。
- 按 mission\_id 名字判断任务优先级。
- 按 cargo\_id/driver\_id/公开坐标写任何分支。

判断标准：

```text
如果这段代码回答的是“事实是什么”，可以保留。
如果这段代码回答的是“现在应该怎么取舍”，优先交给 LLM。
```

## 6. 通用 Agentic 决策流程

每一步决策应该形成一个结构化问题：

```json
{
  "state": {},
  "preferences": [],
  "mission_progress": [],
  "candidate_actions": [],
  "hard_invalid_actions": [],
  "soft_risks": [],
  "recent_failures": [],
  "question": "What is the best next action and why?"
}
```

LLM 要回答：

- 当前主要矛盾是什么？
- 哪些偏好是 hard，哪些是 soft？
- 哪些风险可以接受？
- 等待是否真的会改善局面？
- 接单是否会导致更大罚分？
- 当前动作对整月目标有什么影响？
- 为什么不是其他候选？

这才是“真正思考”。

## 7. 收入目标和策略目标

我们最终不是只追求低罚分，也不是只追求高毛收入，而是：

```text
校验通过
  > 不陷入等待死循环
  > 大额罚分可控
  > 稳定收入 20w+
  > 隐藏偏好可泛化
  > token 使用合理
```

当前需要特别修复的收益问题：

- 过度保守导致大量 wait。
- 累计预算接近耗尽后不会做收益/罚分 trade-off。
- Planner 过滤太强，导致 Advisor 没有选择空间。
- SafetyGate 拒绝后没有把拒绝原因反馈成下一轮反思。
- 早期接单没有前瞻，可能一两单消耗整月预算。
- 长任务和普通收益之间缺少 LLM 级别的全局判断。

Agentic 收益策略应该是：

- 低风险时，积极赚钱。
- 出现 soft risk 时，计算风险与收益，让 LLM 权衡。
- 出现 hard mission 时，优先保证任务。
- 出现 wait deadlock 时，强制进入反思，而不是继续规则 wait。
- 出现预算耗尽时，承认现实，选择最优剩余策略，而不是等待不存在的恢复。

## 8. 后续重构路线

### Phase 1：止血与收权

目标：不再让程序无脑过滤和无脑 wait。

任务：

- Planner 改名或拆分为 `CandidateFactBuilder`。
- 只 hard filter 物理不可执行货源。
- soft risk 候选必须保留给 Advisor。
- SafetyGate 拒绝动作后，返回结构化 rejection 给下一轮 Advisor。
- Advisor prompt 强化累计预算、等待机会成本、soft risk trade-off。
- 删除任务类型白名单和 mission\_id 策略判断。

验收：

- D003 类预算耗尽场景不再连续 wait 10+ 次。
- 日志里能看到 Advisor 比较 `net_after_known_risk`。
- `rg "home_nightly_mission|family_task|special_cargo_|visit_point_mission|multi_step_task_ordered"` 无命中。

### Phase 2：通用任务图

目标：复杂任务由 LLM 输出步骤图，不由 Python 枚举 builder。

任务：

- Preference schema 从 `kind` 中心改成 `constraints + task_steps` 中心。
- MissionPlanner 输出通用 action primitives。
- task\_graph\_builder 只按字段构建，不按偏好类型构建。
- MissionExecutor 只执行原语，任务卡住就交给 Replanner。

验收：

- 新增一种地点+时间+停留组合偏好，不需要新增 Python 分支。
- LLM mission plan 缺步骤时，会二次修复，而不是 Python 偷偷补特化任务。

### Phase 3：LLM 决策主脑

目标：关键取舍真正由 LLM 做。

任务：

- Advisor 输入完整候选事实和风险事实。
- Advisor 输出 policy\_mode、accepted\_risks、rejected\_alternatives。
- 每日开始、任务卡住、候选全风险、连续等待、预算异常时必须调用 Advisor。
- 普通低风险高收益场景可走快速程序路径，减少 token。

验收：

- token 不为 0，但不会每步无脑调用。
- 日志能解释为什么接、为什么等、为什么接受罚分。
- 结果不靠公开数据特化也能稳定跑完。

### Phase 4：Memory 与自我改进

目标：利用 memory 学习通用经验，而不是记测试数据。

允许记录：

- 某类偏好导致的通用失败模式。
- 某类局面下等待是否有效。
- 某类风险的收益/罚分 trade-off 经验。
- SafetyGate 拒绝原因统计。
- Advisor 选择后的结果反馈。

禁止记录：

- driver\_id 专属策略。
- cargo\_id。
- 公开数据坐标路线。
- 公开数据时间表。
- 固定司机偏好原文到策略映射。

Memory 示例：

```json
{
  "lesson_type": "cumulative_budget",
  "condition": "monthly budget exhausted and wait_streak high",
  "lesson": "waiting does not restore cumulative budget; compare marginal penalty with profit",
  "confidence": 0.8
}
```

### Phase 5：稳定冲 20w+

目标：在架构干净后做收益提升，最终结果一定保证20w+，罚分很低，没有达成目标时将直接分析问题，继续改进，但一定不能违反改正原则，我们要一个真正的agentic AI。

任务：

- 收益/风险事实更准确。
- LLM 决策样本回放分析。
- 用公开数据做 A/B，但只调通用策略，不写数据特化。
- 建立回归集：D003 类预算、D009 类长期任务、D010 类多阶段任务、无货等待、月末长单。

验收：

- 结果回到并超过历史 19w 基准。
- 偏好罚分不失控。
- wait 死循环显著减少。
- 代码规模不再持续膨胀。

## 9. 防反向优化清单

每次改代码前检查：

- 这是不是在为某个司机写策略？
- 这是不是在为某个公开货号/坐标/时间写策略？
- 这是不是新增了一个 `if rule.kind == 新类型` 的执行器？
- 这是不是把 soft risk 提前过滤，导致 LLM 看不到候选？
- 这是不是让 SafetyGate 参与策略选择？
- 这是不是会增加 wait 死循环？
- 这是不是让代码更长但 Agent 权限更小？

每次改代码后检查：

```powershell
rg "cargo_dataset|drivers\.json|server/data|D00[0-9]|240646|driver_id\s*==" demo/agent
rg "home_nightly_mission|family_task|special_cargo_|visit_point_mission|multi_step_task_ordered" demo/agent
python -m compileall demo/agent
```

还要看日志：

- Advisor 是否真的被调用。
- Advisor 是否看到 soft risk 候选。
- SafetyGate 是否频繁拒绝同类动作。
- 是否出现 10 次以上连续 wait。
- 是否出现候选全被 planner filter。
- 是否出现 token 大量消耗但动作不变。

## 10. 一句话总结

我们要把系统从：

```text
LLM 解析偏好，Python 枚举策略
```

改成：

```text
Python 提供事实和安全边界，LLM 理解偏好并做关键取舍
```

真正的 Agentic AI 不是没有程序规则，而是程序规则只描述世界，不替 Agent 做策略。后续所有优化都应该围绕“减少非必要规则编码、扩大 LLM 的有效决策空间、保留硬安全底线、提升稳定收益”展开。
