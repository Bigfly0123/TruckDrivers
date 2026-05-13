# TruckDrivers Agentic Architecture 总规划文件

> 版本：Phase 3.0 总体重构规划  
> 目标：从“LLM 辅助的贪婪调度器”升级为“面向 31 天货运决策的 Agentic Planning System”  
> 适用范围：`demo/agent`、`demo/server`、`demo/simkit`、`demo/results` 以及后续所有 Agent 架构相关文档

---

## 0. 核心结论

当前项目的大方向需要升级。

当前系统已经不只是 bug 层面的问题，而是宏观架构还没有真正进入主流 Agentic AI 的范式。现在的系统更接近：

```text
规则 / 启发式候选生成
+ 约束过滤
+ 当前 step 收益估计
+ LLM Advisor 从候选里选择一个动作
+ SafetyGate 做硬校验
```

这套架构可以作为 Phase 2 的 baseline，但它还不是一个真正高级的 Agent 系统。

更准确地说，当前系统是：

```text
LLM-assisted constrained greedy optimizer
```

也就是：

```text
带 LLM 的约束贪婪优化器
```

它的优点是稳定、容易调试、可控；但缺点也明显：

- LLM 只在流程末尾做候选选择；
- 缺少长期规划；
- 缺少日级 / 月级策略；
- 缺少记忆；
- 缺少反思；
- 缺少多 Agent 分工；
- 缺少状态图式 orchestration；
- 缺少可观测的 Agent trace；
- 缺少类似现代 Agent 框架中的 handoff、guardrails、memory、state、workflow 等能力。

因此，后续项目不应继续只围绕单点 bug 反复修补，而应该把主线切换为：

```text
Phase 3.0：Agentic Architecture Refactor
```

目标是把 TruckDrivers 从一个“每一步贪婪选动作”的调度器，升级为一个：

```text
面向长周期货运任务的状态化、多角色、多工具、可反思的 Agentic Planning System
```

---

## 1. 新项目定位

### 1.1 旧定位

旧定位可以概括为：

```text
在司机偏好约束下，使用启发式 / 贪婪算法选择当前最优订单。
```

这个定位的问题是：

1. 太像传统优化脚本；
2. LLM 只是一个候选选择器；
3. 缺少 Agentic AI 的高级感；
4. 31 天长周期收益无法只靠单步贪婪保证；
5. 很难体现当前主流 Agent 框架的设计思想。

---

### 1.2 新定位

新定位建议改为：

```text
TruckDrivers 是一个面向 31 天货运调度任务的 Agentic Planning System。

系统通过状态图编排、多角色 Agent 分工、工具化事实计算、长期记忆、滚动规划、约束 guardrails 和反思复盘，在保证硬约束合法的前提下提升司机长期累计收益。
```

更短的项目定位可以写成：

```text
Agentic Truck Driver Decision System
```

或者：

```text
A stateful multi-agent planning system for long-horizon truck dispatch decisions.
```

---

## 2. 为什么当前架构大方向不够

### 2.1 当前系统是 reactive，而不是 planning

当前流程大致是：

```text
当前状态
-> 当前货源
-> 当前候选
-> 当前约束风险
-> 当前收益
-> 选一个动作
```

这是一种 reactive decision loop。

也就是说，它主要回答：

```text
现在这一步做什么？
```

但 31 天货运任务真正需要回答的是：

```text
今天应该采用什么策略？
未来几天应该如何安排位置、休息、订单类型和月度目标？
当前动作会怎样影响后续机会？
什么时候应该赚钱，什么时候应该休息，什么时候应该为未来高价值区域移动？
```

当前系统缺少这些问题的显式建模。

---

### 2.2 当前 LLM 角色太靠后

当前 LLM 大致处在流程末尾：

```text
Python 已经生成候选、过滤候选、计算分数
-> LLM Advisor 选一个 candidate_id
```

这导致 LLM 的作用偏窄。

它现在更像：

```text
候选选择器
```

而不是：

```text
战略规划者 + 约束解释者 + 机会分析者 + 调度决策者 + 复盘反思者
```

真正的 Agentic 系统不应该只让 LLM “点菜”，而应该让 LLM 参与：

- 诊断当前局面；
- 制定今天策略；
- 解释约束优先级；
- 判断长期机会；
- 复盘昨天错误；
- 调整未来策略；
- 在多个专业 Agent 之间 handoff。

---

### 2.3 当前算法偏单步贪婪

当前候选评分主要关注：

```text
当前订单收入
当前空驶成本
当前 penalty exposure
当前约束满足情况
```

但没有系统建模：

```text
订单终点的未来货源价值
当前位置的长期机会密度
当前动作是否会错过未来高价值时间窗
休息安排是否挤压黄金接单时间
月度目标是否需要提前推进
当前动作对未来 6/12/24 小时的影响
```

这会导致局部看似合理，但 31 天总收益不高。

---

### 2.4 当前缺少 memory 和 reflection

一个高级 Agent 系统应该能回答：

```text
昨天为什么收入低？
今天是否重复了昨天的错误？
哪个约束最影响收益？
某个司机是否经常过早休息？
某类订单是否长期导致低收益？
哪些策略应该被记住并在后续使用？
```

当前系统更多是 step-level logging，没有形成真正的记忆和反思闭环。

---

### 2.5 当前缺少状态图 orchestration

现在系统基本是线性流程：

```text
observe -> generate candidates -> evaluate -> advise -> safety gate -> action
```

更高级的 Agent 系统应该是状态图：

```text
observe
-> diagnose
-> strategic_plan
-> generate_candidates
-> constraint_analysis
-> opportunity_analysis
-> lookahead
-> decision_synthesis
-> safety_gate
-> repair_if_failed
-> execute
-> reflect_if_needed
-> memory_update
```

状态图带来的好处是：

- 每个节点职责清晰；
- 可以插入反思、修复、回退；
- 可以对关键决策做多 Agent 审核；
- 可以追踪每个节点的输入输出；
- 更接近主流 Agent workflow 框架。

---

## 3. 对标主流 Agent 框架的能力

当前主流 Agent 框架强调的不是“一个 LLM 每步选择一个动作”，而是更完整的 Agent 应用架构。

### 3.1 LangGraph 风格能力

LangGraph 强调：

- graph-based workflow；
- durable execution；
- state persistence；
- human-in-the-loop；
- short-term / long-term memory；
- 可恢复、可中断、可观察的 Agent 执行流。

对 TruckDrivers 的启发：

```text
我们应该把 agent 决策流程从线性函数升级为状态图。
```

对应能力：

```text
AgentState
GraphNode
Checkpoint
MemoryStore
ReflectionNode
RepairNode
TraceLogger
```

---

### 3.2 OpenAI Agents SDK 风格能力

OpenAI Agents SDK 强调：

- agent definitions；
- tools；
- orchestration；
- handoffs；
- guardrails；
- human review；
- results/state；
- tracing / observability。

对 TruckDrivers 的启发：

```text
我们不应该只有一个 Advisor，而应该有多个专业 Agent，通过 handoff 或 orchestration 协作。
```

对应能力：

```text
StrategicPlannerAgent
ConstraintAnalystAgent
OpportunityAnalystAgent
TacticalDispatcherAgent
DecisionSynthesizerAgent
ReflectionAgent
SafetyGuardrail
```

---

### 3.3 Microsoft AutoGen / Agent Framework 风格能力

Microsoft Agent Framework / AutoGen 系列强调：

- single-agent 与 multi-agent patterns；
- session-based state management；
- filters；
- telemetry；
- 多 Agent orchestration；
- 面向生产的 Agent workflow。

对 TruckDrivers 的启发：

```text
我们应该让不同 Agent 专注不同任务，并保留可追踪的 session state 和 telemetry。
```

对应能力：

```text
Multi-agent coordination
Agent session state
Telemetry logs
Typed inputs / outputs
Decision trace
```

---

### 3.4 CrewAI 风格能力

CrewAI 强调：

- roles；
- tasks；
- tools；
- memory；
- knowledge；
- structured outputs；
- agents / crews / flows。

对 TruckDrivers 的启发：

```text
我们可以把司机调度问题拆成多个角色任务，让 Agent 团队协作完成决策。
```

对应能力：

```text
角色分工
任务链
工具调用
结构化输出
共享记忆
领域知识库
```

---

## 4. 新总体架构

### 4.1 总体流程

新的 Agentic 架构建议为：

```text
Simulation API
    |
    v
Observation Layer
    |
    v
Agent State Builder
    |
    v
Memory Retrieval
    |
    v
Strategic Planner Agent
    |
    v
Candidate Generator / Tool Layer
    |
    v
Constraint Analyst Agent
    |
    v
Opportunity Analyst Agent
    |
    v
Lookahead Evaluator
    |
    v
Decision Synthesizer Agent
    |
    v
Safety Gate / Guardrails
    |
    +---- failed ----> Repair Agent
    |
    v
Action Output
    |
    v
Trace Logger
    |
    v
Reflection / Memory Update
```

---

### 4.2 状态图版本

可以按如下状态图理解：

```text
START
  |
  v
observe_state
  |
  v
build_agent_state
  |
  v
retrieve_memory
  |
  v
strategic_planning
  |
  v
generate_candidates
  |
  v
constraint_analysis
  |
  v
opportunity_analysis
  |
  v
lookahead_evaluation
  |
  v
decision_synthesis
  |
  v
safety_guardrail
  |\
  | \__ failed -> repair_decision -> safety_guardrail
  |
  v
emit_action
  |
  v
log_trace
  |
  v
reflect_if_needed
  |
  v
update_memory
  |
  v
END
```

---

## 5. 核心设计原则

### 5.1 Python 做确定性工具，LLM 做高层 Agent 推理

不能让 LLM 自由决定所有事情，因为货运仿真有强数值、强约束和强合法性要求。

正确边界应该是：

```text
Python：事实计算、收益估计、距离时间、约束校验、状态更新、安全门
LLM Agent：战略规划、偏好解释、机会权衡、长期规划、反思复盘、决策综合
```

也就是说：

```text
规则不是主控，而是工具；
约束不是策略，而是 guardrails；
收益计算不是最终决策，而是 evidence；
LLM 不是装饰，而是 orchestration / reasoning / synthesis 的核心。
```

---

### 5.2 不再以单步贪婪作为最高目标

当前候选的 immediate score 仍然有用，但不能再作为唯一决策依据。

新目标应该是：

```text
long_term_score = immediate_value
                + future_opportunity_value
                + strategic_alignment_value
                + monthly_goal_progress_value
                + rest_schedule_value
                - penalty_exposure
                - opportunity_cost
                - future_constraint_risk
```

Advisor / DecisionSynthesizer 应该根据 long-term expected outcome 做决策。

---

### 5.3 多 Agent 分工，但最终动作唯一

多个 Agent 可以分析，但最终只输出一个 action。

建议结构：

```text
StrategicPlannerAgent：定战略
ConstraintAnalystAgent：看约束
OpportunityAnalystAgent：看机会
TacticalDispatcherAgent：整理候选
DecisionSynthesizerAgent：综合决策
ReflectionAgent：复盘记忆
SafetyGate：硬校验
```

多个 Agent 不能互相抢控制权。

最终控制流必须是：

```text
多 Agent 分析 -> DecisionSynthesizer 选 candidate -> SafetyGate 校验 -> action
```

---

### 5.4 Guardrails 必须保留

Agentic 不等于放飞 LLM。

必须保留硬安全边界：

- 不能违反仿真环境动作格式；
- 不能违反 hard preference；
- 不能接已经过期或不可达订单；
- 不能输出不存在的 cargo_id；
- 不能输出非法 reposition；
- 不能绕过 SimulationApiPort。

因此：

```text
SafetyGate / Guardrails 是最后一道硬门。
```

---

### 5.5 所有 Agent 输出必须结构化

不要让 Agent 返回自由文本再靠字符串解析。

所有 Agent 输出都应该是 typed schema，例如：

```json
{
  "strategy": "...",
  "risk_focus": ["daily_rest", "stay_in_area"],
  "recommended_behavior": "...",
  "confidence": 0.82,
  "reasons": ["...", "..."]
}
```

结构化输出带来：

- 可调试；
- 可记录；
- 可评估；
- 可复盘；
- 可用于后续节点。

---

## 6. Agent 角色设计

## 6.1 StrategicPlannerAgent

### 职责

负责长期和日级策略，不直接选择具体订单。

它回答：

```text
今天的核心策略是什么？
当前司机最重要的约束是什么？
当前是否应该赚钱、休息、靠近某区域、完成某类目标？
休息应该前置还是后置？
是否存在月底风险、deadline 风险、月度目标落后风险？
```

### 输入

```text
AgentState
Driver profile
Preference summary
Current day / minute
Remaining days
Decision history summary
Memory retrieval result
Monthly progress
Recent failures / reflections
```

### 输出 schema

```json
{
  "day_strategy": "优先区域内短单，晚上完成连续休息",
  "primary_objectives": ["maximize_income", "stay_in_area", "complete_daily_rest"],
  "risk_focus": ["operate_within_area", "continuous_rest"],
  "target_regions": ["Shenzhen"],
  "avoid_patterns": ["long_idle_morning", "late_rest_failure"],
  "rest_strategy": "delay_rest_until_low_opportunity_period_if_feasible",
  "order_strategy": "prefer_profitable_in_area_short_orders",
  "confidence": 0.8
}
```

---

## 6.2 ConstraintAnalystAgent

### 职责

负责解释和评估约束，不直接选动作。

它回答：

```text
哪些是 hard constraint？
哪些是 soft preference？
当前满足了吗？
哪些候选违反 hard？
哪些候选只是 soft risk？
某个 rest candidate 是 complete 还是 partial progress？
某个订单是否真的会导致未来约束失败？
```

### 输入

```text
ConstraintSpec list
ConstraintRuntimeState
Candidate list
Current state
History
```

### 输出 schema

```json
{
  "hard_constraints": ["operate_within_area"],
  "soft_constraints": ["daily_rest_preference"],
  "candidate_constraint_summary": [
    {
      "candidate_id": "take_order_123",
      "status": "valid",
      "hard_violations": [],
      "soft_risks": [],
      "future_constraint_risk": 0,
      "explanation": "订单在区域内，接单后仍有足够时间完成剩余休息"
    }
  ],
  "global_risk_summary": "主要风险是当天连续休息尚未完成，但仍可后置完成"
}
```

---

## 6.3 OpportunityAnalystAgent

### 职责

负责判断收益机会和未来位置价值。

它回答：

```text
当前订单是否只是短期赚钱？
订单终点是否有未来货源？
当前位置未来几个小时机会如何？
接这个单会不会错过更好机会？
当前 wait 的机会成本是多少？
```

### 输入

```text
Current location
Candidate list
Visible cargo
Future cargo approximation
Historical cargo density
Time of day
Driver constraints
```

### 输出 schema

```json
{
  "market_summary": "当前位置附近合法货源较少，但南山区未来机会较高",
  "candidate_opportunity_summary": [
    {
      "candidate_id": "take_order_123",
      "immediate_net": 350,
      "future_position_quality": "good",
      "future_value_estimate": 420,
      "opportunity_cost": 80,
      "reason": "终点附近未来可接订单密度较高"
    }
  ]
}
```

---

## 6.4 TacticalDispatcherAgent

### 职责

负责当前 step 的候选整理、去噪、摘要。

它不做最终决策，而是把候选整理成适合 DecisionSynthesizer 阅读的结构。

### 输入

```text
Raw candidates
Constraint analysis
Opportunity analysis
Strategic plan
```

### 输出 schema

```json
{
  "shortlist": [
    {
      "candidate_id": "take_order_123",
      "action": "take_order",
      "why_relevant": "符合今日策略，收益为正，终点机会好",
      "main_tradeoff": "占用 90 分钟，但不影响晚间休息"
    }
  ],
  "discarded_summary": {
    "hard_invalid_count": 45,
    "low_value_count": 8,
    "dominated_count": 12
  }
}
```

---

## 6.5 DecisionSynthesizerAgent

### 职责

最终综合所有分析，选择一个 candidate。

它是唯一策略决策者。

### 输入

```text
AgentState
Strategic plan
Constraint analysis
Opportunity analysis
Candidate shortlist
Memory hints
```

### 输出 schema

```json
{
  "selected_candidate_id": "take_order_123",
  "decision_type": "take_order",
  "expected_immediate_value": 350,
  "expected_future_value": 420,
  "long_term_score": 690,
  "main_tradeoff": "profit_vs_rest_schedule",
  "reason": "该订单在硬约束内，收益为正，终点机会好，且仍可完成晚间休息",
  "confidence": 0.83
}
```

---

## 6.6 RepairAgent

### 职责

当 SafetyGate 拒绝 DecisionSynthesizer 的动作时，RepairAgent 负责修复。

它不能自由发挥，只能在已存在的候选中选择替代方案。

### 触发条件

```text
SafetyGate failed
selected_candidate_id 不存在
候选动作格式非法
hard constraint violation
环境可能拒绝
```

### 输出 schema

```json
{
  "repaired_candidate_id": "wait_60",
  "repair_reason": "原候选违反 hard constraint，选择安全等待作为替代",
  "confidence": 0.7
}
```

---

## 6.7 ReflectionAgent

### 职责

复盘历史表现，生成可复用经验。

它可以在以下时间运行：

```text
每天结束
每 N 步
收入异常低时
连续 wait 过多时
hard invalid 异常高时
偏好风险异常高时
```

### 输入

```text
Daily trace
Income summary
Decision history
Constraint violation summary
Wait/rest/take_order distribution
Missed opportunity summary
```

### 输出 schema

```json
{
  "reflection_type": "daily_review",
  "main_issue": "上午连续 partial rest 导致错过合法短单",
  "lesson": "当有合法盈利订单且后续仍可完成休息时，不应过早进入长休息块",
  "strategy_adjustment": "明天优先接上午区域内短单，将连续休息安排到低机会成本时段",
  "memory_importance": 0.85
}
```

---

## 7. AgentState 设计

新架构必须有统一的 AgentState。

建议文件：

```text
demo/agent/agent_state.py
```

### 7.1 AgentState 字段

```python
@dataclass
class AgentState:
    driver_id: str
    current_day: int
    current_minute: int
    remaining_days: int

    location: Location
    driver_status: dict
    visible_cargo: list[dict]
    recent_history: list[dict]

    preferences: list[PreferenceRule]
    constraints: list[ConstraintSpec]
    runtime_constraints: ConstraintRuntimeState

    monthly_progress: dict
    daily_progress: dict
    rest_state: dict
    area_state: dict

    strategic_memory: list[dict]
    current_day_plan: dict | None
    recent_reflections: list[dict]

    trace_id: str
```

---

### 7.2 为什么需要 AgentState

AgentState 是整个 Agent 系统的核心。

它解决的问题是：

- 所有节点共享同一份状态；
- 每个 Agent 输入输出可以追踪；
- 可以 checkpoint；
- 可以复盘；
- 可以把 state 传给 graph node；
- 可以在 SafetyGate 失败后 repair；
- 可以把反思写回 memory。

---

## 8. Memory 设计

### 8.1 Memory 类型

建议分成四类：

```text
Short-term working memory：当前 day / 当前 episode 内的工作记忆
Long-term driver memory：某个司机长期表现和策略经验
Constraint memory：某类约束过去如何影响收益
Market memory：区域、时间、货源机会统计
```

---

### 8.2 MemoryStore

建议文件：

```text
demo/agent/memory_store.py
```

支持接口：

```python
class MemoryStore:
    def retrieve(self, driver_id: str, query: str, k: int = 5) -> list[dict]:
        ...

    def save_reflection(self, driver_id: str, reflection: dict) -> None:
        ...

    def save_strategy_result(self, driver_id: str, day: int, result: dict) -> None:
        ...
```

---

### 8.3 Memory 内容示例

```json
{
  "driver_id": "D001",
  "memory_type": "strategy_lesson",
  "content": "当上午存在区域内盈利短单时，过早进入连续休息会降低日收益。",
  "applies_to": ["continuous_rest", "operate_within_area"],
  "importance": 0.86,
  "created_day": 3
}
```

注意：这不是 D001 特判。Memory 是按司机历史表现动态形成的经验，不是写死规则。

---

## 9. Planning 设计

## 9.1 Day-level Planning

每天开始时生成一个 day plan。

### 输入

```text
当前司机状态
剩余天数
昨日 reflection
月度目标进度
约束状态
市场机会摘要
```

### 输出

```json
{
  "day": 5,
  "income_target": 1800,
  "primary_strategy": "优先接区域内短单，避免上午长时间空等",
  "rest_plan": {
    "preferred_window": "night",
    "latest_start_minute": 960,
    "avoid_rest_before": 600
  },
  "target_regions": ["Shenzhen core"],
  "risk_controls": ["do_not_leave_area", "complete_daily_rest"],
  "fallback_policy": "如果连续 3 小时无合法盈利订单，则选择低机会成本休息"
}
```

---

## 9.2 Rolling step planning

每一步仍然只执行一个 action，但决策时要参考 day plan 和 future value。

```text
当前 step 决策 = day plan + 当前候选 + 未来机会估计 + 约束状态 + memory
```

---

## 9.3 Lookahead

建议先做轻量 lookahead，不要一上来做复杂全局最优。

第一版：

```text
对每个候选估算执行后 6~12 小时的机会价值
```

第二版：

```text
对 top K 候选展开 2 步 beam search
```

第三版：

```text
日级策略 + step-level rolling planning 联合优化
```

---

## 10. Tools 设计

在主流 Agent 框架里，Agent 不应该直接读写所有内容，而是通过工具拿事实。

建议把当前 Python 模块包装成 tools。

### 10.1 必备工具

```text
get_driver_status_tool
query_cargo_tool
query_decision_history_tool
compile_preferences_tool
build_constraint_state_tool
generate_candidates_tool
evaluate_constraints_tool
estimate_profit_tool
estimate_future_value_tool
safety_validate_tool
write_trace_tool
save_memory_tool
```

---

### 10.2 工具边界

工具只返回事实和评估，不直接做最终策略决策。

例如：

```text
evaluate_constraints_tool 可以说 candidate 是否 hard invalid；
estimate_future_value_tool 可以给 long_term_score；
但它们不能直接 return final action。
```

最终动作仍由 DecisionSynthesizerAgent 选择，再由 SafetyGate 校验。

---

## 11. Trace / Observability 设计

高级 Agent 系统必须可观测。

建议新增：

```text
demo/results/traces/agent_trace.jsonl
```

每一步记录：

```json
{
  "trace_id": "D001_day3_step42",
  "driver_id": "D001",
  "day": 3,
  "minute": 580,
  "node_outputs": {
    "strategic_planner": {...},
    "constraint_analyst": {...},
    "opportunity_analyst": {...},
    "decision_synthesizer": {...},
    "safety_gate": {...}
  },
  "selected_action": {...},
  "final_status": "accepted"
}
```

---

## 12. 新目录结构建议

建议 Phase 3.0 后目录演进为：

```text
demo/agent/
  agent_state.py
  graph_runner.py
  memory_store.py
  trace_logger.py

  agents/
    strategic_planner.py
    constraint_analyst.py
    opportunity_analyst.py
    tactical_dispatcher.py
    decision_synthesizer.py
    reflection_agent.py
    repair_agent.py

  tools/
    observation_tools.py
    candidate_tools.py
    constraint_tools.py
    profit_tools.py
    lookahead_tools.py
    safety_tools.py
    memory_tools.py

  planning/
    day_plan.py
    lookahead_simulator.py
    future_value_estimator.py
    beam_search.py

  schemas/
    agent_outputs.py
    candidate_summary.py
    trace_schema.py

  legacy/
    old_advisor.py
    old_planner.py
```

初期不一定真的移动所有文件，但应该逐步朝这个结构靠。

---

## 13. 与当前代码的迁移关系

### 13.1 保留内容

当前以下模块仍有价值：

```text
PreferenceCompiler
ConstraintSpec
ConstraintRuntimeState
CandidateFactBuilder
ConstraintEvaluator
SafetyGate
SimulationApiPort
calc_monthly_income
```

这些不应该废弃，而是升级为 Agent tools / guardrails。

---

### 13.2 降级内容

当前 `LlmDecisionAdvisor` 应从“唯一 Advisor”升级为更大系统里的：

```text
DecisionSynthesizerAgent
```

并且它的输入不再只是 candidates，而是：

```text
strategic_plan
constraint_analysis
opportunity_analysis
lookahead_summary
memory_hints
candidate_shortlist
```

---

### 13.3 新增内容

必须新增：

```text
AgentState
GraphRunner
MemoryStore
StrategicPlannerAgent
OpportunityAnalystAgent
ReflectionAgent
TraceLogger
FutureValueEstimator
```

---

## 14. 阶段路线图

## Phase 3.0：Agentic 架构地基

目标：把线性流程改造成状态图式流程。

任务：

1. 新增 `AgentState`；
2. 新增 `TraceLogger`；
3. 新增 `GraphRunner`；
4. 把现有 observe / candidate / evaluate / advisor / safety 包装成 graph nodes；
5. 保持行为基本不变，但 trace 更完整。

验收：

```text
原有主流程仍能跑通；
每一步有 graph trace；
每个节点输入输出可记录；
SafetyGate 仍然最后执行；
不增加 validation error。
```

---

## Phase 3.1：Day-level Strategic Planner

目标：让系统每天先有策略，而不是每一步临时反应。

任务：

1. 新增 `StrategicPlannerAgent`；
2. 每天开始生成 `day_plan`；
3. 每一步决策输入 day_plan；
4. Advisor prompt 引用 day_plan；
5. 日志记录 day_plan 是否被遵守。

验收：

```text
每天有明确 day_strategy；
休息安排不再完全被当前 step 触发；
订单选择能解释为符合 / 不符合 day_plan；
总收益不低于 Phase 2 baseline。
```

---

## Phase 3.2：Memory + Reflection

目标：让系统能复盘、记忆和调整。

任务：

1. 新增 `MemoryStore`；
2. 新增 `ReflectionAgent`；
3. 每天结束生成 daily reflection；
4. 下一天 StrategicPlanner 读取 memory；
5. 记录策略调整。

验收：

```text
系统能指出昨天收入低的原因；
同类错误在后续天数减少；
memory 中存在可解释 strategy lessons；
Agent 决策理由能引用历史经验。
```

---

## Phase 3.3：Opportunity Analyst + Future Value

目标：解决单步贪婪导致的长期收益问题。

任务：

1. 新增 `OpportunityAnalystAgent`；
2. 新增 `FutureValueEstimator`；
3. 对候选增加：
   - future_value_estimate；
   - opportunity_cost；
   - future_position_quality；
   - long_term_score；
4. DecisionSynthesizer 优先根据 long_term_score 决策。

验收：

```text
系统不再只选 immediate_net 最高的订单；
能解释为什么选择当前利润略低但终点更好的订单；
31 天累计收益相比贪婪 baseline 提升；
hard violation 不增加。
```

---

## Phase 3.4：Multi-Agent Decision Synthesis

目标：真正形成多 Agent 分析 + 综合决策。

任务：

1. 新增 `ConstraintAnalystAgent`；
2. 新增 `TacticalDispatcherAgent`；
3. 新增 `DecisionSynthesizerAgent`；
4. 各 Agent 输出结构化 JSON；
5. DecisionSynthesizer 综合所有分析。

验收：

```text
每个关键决策能看到：
- 战略观点；
- 约束观点；
- 机会观点；
- 最终综合理由；
- SafetyGate 结果。
```

---

## Phase 3.5：Repair / Guardrail Loop

目标：SafetyGate 失败时自动修复，而不是简单 wait。

任务：

1. 新增 `RepairAgent`；
2. SafetyGate failed 后进入 repair node；
3. RepairAgent 从剩余合法候选中选替代；
4. 最多 repair 1~2 次，避免循环。

验收：

```text
非法动作不会直接导致低质量 wait；
修复动作仍来自候选池；
repair trace 清晰；
validation error 不增加。
```

---

## Phase 3.6：Beam Search / Receding Horizon

目标：进一步提升长期收益。

任务：

1. 对 top K 候选做 2~3 步轻量展开；
2. 计算 path_score；
3. 只执行最佳 path 的第一步；
4. 下一步重新规划。

验收：

```text
相较单步 long_term_score，收益进一步提升；
运行时间可控；
决策 trace 可解释；
不破坏 hard constraints。
```

---

## 15. 算法层升级方向

### 15.1 从 immediate score 到 long-term score

当前：

```text
score = estimated_net_after_penalty
```

升级为：

```text
long_term_score = immediate_net
                - penalty_exposure
                + future_value_estimate
                + strategic_alignment
                + rest_schedule_value
                + monthly_goal_progress_value
                - opportunity_cost
                - future_constraint_risk
```

---

### 15.2 从单步候选到路径候选

当前：

```text
candidate = one action
```

未来：

```text
path = action_1 -> estimated_action_2 -> estimated_action_3
```

最终仍只执行 action_1。

这就是 receding horizon。

---

### 15.3 从静态约束到动态约束规划

当前：

```text
当前是否违反约束？
```

未来：

```text
当前动作会不会导致未来约束更难满足？
当前动作是否有助于后续满足月度 / 日级目标？
```

---

## 16. 新 Prompt 总方向

### 16.1 StrategicPlanner prompt 方向

```text
You are the strategic planner for a long-horizon truck dispatch agent.
Your job is not to select a concrete cargo order.
Your job is to produce a day-level strategy that balances income, hard constraints, soft preferences, rest planning, location opportunity, and monthly progress.
```

---

### 16.2 ConstraintAnalyst prompt 方向

```text
You are the constraint analyst.
Classify each constraint as hard or soft based on ConstraintSpec, not driver_id.
Explain whether each candidate violates hard constraints, creates soft risk, or remains feasible.
Do not select the final action.
```

---

### 16.3 OpportunityAnalyst prompt 方向

```text
You are the opportunity analyst.
Evaluate immediate income, destination value, future cargo opportunity, opportunity cost, and whether waiting/resting wastes high-value time.
Do not select the final action.
```

---

### 16.4 DecisionSynthesizer prompt 方向

```text
You are the final decision synthesizer.
Use the strategic plan, constraint analysis, opportunity analysis, lookahead summary, and memory hints to choose exactly one candidate.
Prefer the highest long-term expected outcome, not merely the highest immediate profit.
Never choose a candidate that violates hard constraints.
Return structured JSON only.
```

---

## 17. 评价指标升级

不能只看 monthly_income。

需要新增 Agentic 指标。

### 17.1 收益指标

```text
total_gross_income
total_net_income
income_per_day
income_per_active_hour
empty_mile_cost
```

---

### 17.2 合法性指标

```text
validation_error_count
hard_constraint_violation_count
soft_preference_penalty
```

---

### 17.3 Agent 行为指标

```text
wait_ratio
rest_ratio
take_order_ratio
reposition_ratio
long_idle_blocks
partial_rest_before_profitable_order_count
missed_profitable_order_count
```

---

### 17.4 长期规划指标

```text
day_plan_adherence
memory_usage_count
reflection_count
strategy_adjustment_count
future_value_used_count
long_term_score_vs_immediate_score_disagreement_count
```

---

### 17.5 可解释性指标

```text
trace_completeness
structured_output_success_rate
safety_repair_count
reason_length_valid_rate
json_parse_success_rate
```

---

## 18. 风险与边界

### 18.1 不要一次性推翻所有代码

当前 Phase 2 模块仍是地基。

不要直接重写全部，而是：

```text
先包装成 graph node
再逐步替换 Advisor
再增加 memory / planning / reflection
```

---

### 18.2 不要让多 Agent 变成噪声

多 Agent 不是越多越好。

初期建议最多：

```text
StrategicPlanner
ConstraintAnalyst
OpportunityAnalyst
DecisionSynthesizer
ReflectionAgent
```

不要一开始就搞十几个 Agent。

---

### 18.3 不要让 LLM 绕过硬计算

所有数值相关内容必须由 Python 工具提供，包括：

- 距离；
- 时间；
- 收益；
- penalty；
- deadline；
- hard constraint；
- cargo availability。

LLM 可以解释和权衡，但不能凭空计算事实。

---

### 18.4 不要牺牲合法性换收益

Agentic 架构的目标不是让模型冒险乱接单。

底线仍然是：

```text
hard constraints must never be violated
SafetyGate remains mandatory
```

---

## 19. 建议新增总文档

建议在仓库中新增：

```text
demo/docs/agentic_architecture_master_plan.md
```

同时把旧文档定位调整：

```text
agent_refactor_history_and_current_direction.md
```

变成 Phase 1 / Phase 2 历史文档。

新文档 `agentic_architecture_master_plan.md` 作为 Phase 3 之后的总方向。

---

## 20. 给代码模型的总提示词

```text
我们现在不再继续围绕 TruckDrivers 当前 Phase 2 的小 bug 做零散修补，而是要把项目升级为一个更接近主流大 Agent 框架的 Agentic Planning System。

当前系统本质上还是 LLM-assisted constrained greedy optimizer：Python 生成候选和约束评估，LLM Advisor 只在最后从当前候选里选一个动作。这不够 agentic，也难以解决 31 天长期收益规划问题。

请基于现有代码设计 Phase 3.0 Agentic Architecture Refactor。核心要求：

1. 新定位：
   将项目从“单步贪婪调度器”升级为“面向 31 天货运任务的状态化、多角色、多工具、可反思的 Agentic Planning System”。

2. 新架构：
   使用状态图式流程：
   observe_state
   -> build_agent_state
   -> retrieve_memory
   -> strategic_planning
   -> generate_candidates
   -> constraint_analysis
   -> opportunity_analysis
   -> lookahead_evaluation
   -> decision_synthesis
   -> safety_guardrail
   -> repair_if_failed
   -> emit_action
   -> log_trace
   -> reflect_if_needed
   -> update_memory

3. 新增核心模块：
   - AgentState
   - GraphRunner
   - MemoryStore
   - TraceLogger
   - StrategicPlannerAgent
   - ConstraintAnalystAgent
   - OpportunityAnalystAgent
   - TacticalDispatcherAgent
   - DecisionSynthesizerAgent
   - ReflectionAgent
   - RepairAgent
   - FutureValueEstimator
   - LookaheadSimulator

4. 保留并工具化当前模块：
   PreferenceCompiler、ConstraintSpec、ConstraintRuntimeState、CandidateFactBuilder、ConstraintEvaluator、SafetyGate 不要废弃，而是作为 tools / guardrails 接入新 Agent workflow。

5. LLM 与 Python 分工：
   Python 负责确定性事实计算、收益估计、距离时间、硬约束校验、安全门。
   LLM Agent 负责战略规划、偏好解释、机会权衡、长期规划、决策综合、反思复盘。

6. 多 Agent 分工：
   StrategicPlannerAgent 负责日级 / 长期策略。
   ConstraintAnalystAgent 负责约束解释和候选约束风险。
   OpportunityAnalystAgent 负责未来机会、位置价值、机会成本。
   DecisionSynthesizerAgent 负责最终选择一个 candidate。
   ReflectionAgent 负责每天或异常时复盘并写入 memory。
   SafetyGate 仍然做最终硬校验。

7. 长期优化：
   不再只根据 estimated_net_after_penalty 选择。
   增加 long_term_score：
   long_term_score = immediate_net
                   - penalty_exposure
                   + future_value_estimate
                   + strategic_alignment
                   + rest_schedule_value
                   + monthly_goal_progress_value
                   - opportunity_cost
                   - future_constraint_risk

8. 记忆与反思：
   增加 daily reflection、strategy lesson、driver memory、market memory。
   下一天 planning 必须读取历史 memory。

9. 可观测性：
   每一步记录完整 trace，包括各 Agent 输出、候选摘要、最终决策、SafetyGate 结果、repair 结果、reflection。

10. 阶段实施：
   Phase 3.0：AgentState + GraphRunner + TraceLogger，把现有流程包装成图。
   Phase 3.1：StrategicPlannerAgent + day_plan。
   Phase 3.2：ReflectionAgent + MemoryStore。
   Phase 3.3：OpportunityAnalyst + FutureValueEstimator。
   Phase 3.4：Multi-Agent DecisionSynthesizer。
   Phase 3.5：Repair / Guardrail loop。
   Phase 3.6：Beam Search / Receding Horizon。

重要边界：
不要写 driver_id 特判；不要让 LLM 绕过硬计算；不要恢复旧的 MissionExecutor / CandidateSafetyFilter 主控逻辑；不要让 fallback 负责赚钱；SafetyGate 必须保留；最终动作必须来自合法 candidate。
```

---

## 21. 最终总结

当前项目不是没有价值，而是需要升级定位。

Phase 2 的工作解决的是：

```text
如何从规则系统转向 LLM-assisted constrained decision system
```

Phase 3 要解决的是：

```text
如何从 LLM-assisted greedy optimizer 转向真正的 Agentic Planning System
```

新的总方向应该是：

```text
状态图编排
+ 多 Agent 分工
+ 工具化事实计算
+ 长期记忆
+ 日级战略规划
+ 未来机会评估
+ 决策综合
+ Safety guardrails
+ 复盘反思
```

这才更接近当前主流大 Agent 框架，也更能体现项目的高级感和研究价值。
