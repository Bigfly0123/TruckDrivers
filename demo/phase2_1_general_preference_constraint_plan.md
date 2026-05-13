# Phase 2.1：通用偏好约束层规划

## 0. 当前背景

当前 Phase 2.0 已经完成了主流程中度精简。

目前主流程基本是：

```text
Observe
-> PreferenceCompiler
-> CandidateFactBuilder
-> valid / soft_risk / hard_invalid 分组
-> LlmDecisionAdvisor 选择 candidate_id
-> SafetyGate 硬校验
-> 返回动作
```
这个方向是对的。

但是最新实验暴露出一个新问题：

系统已经不再全 wait，也有了较高 gross income；
但是偏好罚分非常高，说明系统几乎只在追求接单收益，没有真正理解和处理司机偏好。

当前问题不是要回退到旧的复杂 MissionExecutor / MissionReplanner，也不是继续写大量：

if rule.kind == "daily_rest":
    ...
elif rule.kind == "quiet_hours":
    ...
elif rule.kind == "home_nightly":
    ...

这种代码。

这样虽然可能在开放数据上短期提分，但复赛如果出现新的复杂偏好，系统会崩。

本阶段目标是：

在保持当前精简主流程的基础上，增加一层“通用偏好约束层”。

也就是：

原始偏好文本
-> LLM / PreferenceCompiler 编译成通用 ConstraintSpec
-> CandidateFactBuilder 生成候选
-> ConstraintEvaluator 标注每个候选的风险与满足情况
-> Advisor 根据收益、风险、罚分、任务收益做取舍

核心原则：

Python 不直接替司机决策；
Python 只评估候选动作对通用约束的影响；
Advisor 负责最终 trade-off。
1. 本阶段总目标

Phase 2.1 的目标不是恢复旧框架，而是补齐当前精简主流程缺失的“偏好理解与风险标注能力”。

目标链路：

PreferenceCompiler
  -> General ConstraintSpec

CandidateFactBuilder
  -> Candidate

ConstraintEvaluator
  -> Candidate risk / satisfy facts

LlmDecisionAdvisor
  -> choose candidate_id

本阶段成功后，系统应做到：

1. 不再把所有赚钱订单都误判为 valid
2. 能把每日休息、禁行时段、区域、回家、任务、指定货物等偏好转成通用约束
3. 能为候选动作标注 soft_risk / hard_invalid
4. 能生成满足偏好的 wait / reposition / task candidates
5. Advisor 能看到“接单收益”和“偏好罚分风险”的对比
6. 不恢复旧的 Python 决策系统
2. 当前不要做的事情

本阶段不要做：

1. 不要恢复 MissionExecutor
2. 不要恢复 MissionReplanner
3. 不要恢复 LlmMissionPlanner 作为主流程模块
4. 不要恢复 TaskGraphBuilder 复杂执行图
5. 不要让 SafetyGate 处理 soft preference
6. 不要让 Python 根据 rule.kind 直接返回动作
7. 不要为开放数据中的每个司机写特化策略
8. 不要写 driver_id / cargo_id 特化逻辑
9. 不要让 fallback 接管赚钱

允许复用旧模块中的工具函数，但不能恢复旧模块的主流程决策权。

3. 核心设计：从 rule.kind 转向 ConstraintSpec
3.1 为什么不能继续依赖 rule.kind

当前 rule.kind 可以作为偏好解析结果的标签，但不能作为决策核心。

不推荐：

if rule.kind == "daily_rest":
    return wait()

if rule.kind == "home_nightly":
    return reposition_home()

if rule.kind == "special_cargo":
    return take_specific_cargo()

这种写法会导致：

1. Python 重新成为策略主脑
2. 新偏好需要新分支
3. 代码越来越大
4. 复赛泛化能力差
3.2 rule.kind 可以怎么用

可以把 rule.kind 用于“编译”：

if rule.kind == "quiet_hours":
    constraint_type = "forbid_action_in_time_window"

但不能用于“决策”：

if rule.kind == "quiet_hours":
    force_wait()

一句话：

kind 可以辅助编译；
不能直接驱动动作。
4. 新增通用数据结构 ConstraintSpec

建议新增文件：

demo/agent/preference_constraints.py

定义通用约束结构：

from dataclasses import dataclass, field
from typing import Any

@dataclass
class TimeWindowSpec:
    start_minute_of_day: int | None = None
    end_minute_of_day: int | None = None
    start_minute_abs: int | None = None
    end_minute_abs: int | None = None
    repeat: str | None = None  # daily / monthly / once / none

@dataclass
class LocationSpec:
    latitude: float | None = None
    longitude: float | None = None
    radius_km: float | None = None
    name: str | None = None

@dataclass
class AreaBoundsSpec:
    min_lat: float
    max_lat: float
    min_lng: float
    max_lng: float
    name: str | None = None

@dataclass
class TaskStepSpec:
    step_id: str
    step_type: str
    location: LocationSpec | None = None
    time_window: TimeWindowSpec | None = None
    required_minutes: int | None = None
    cargo_id: str | None = None
    cargo_names: list[str] = field(default_factory=list)
    deadline_minute: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class ConstraintSpec:
    constraint_id: str
    constraint_type: str
    priority: str  # hard / soft
    scope: str  # action / daily / monthly / task
    penalty_amount: float = 0.0
    penalty_cap: float | None = None

    actions: list[str] = field(default_factory=list)
    cargo_names: list[str] = field(default_factory=list)
    cargo_ids: list[str] = field(default_factory=list)

    time_window: TimeWindowSpec | None = None
    location: LocationSpec | None = None
    area_bounds: AreaBoundsSpec | None = None

    required_minutes: int | None = None
    required_days: int | None = None
    deadline_minute: int | None = None
    steps: list[TaskStepSpec] = field(default_factory=list)

    raw_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
5. 支持的通用 constraint_type

本阶段先支持这些通用类型，不要为每个司机偏好写专门逻辑。

5.1 forbid_cargo_category

用于：

不接煤炭
不拉化工
尽量不接蔬菜
避免快递快运

通用判断：

候选 cargo 的 category / name / tags 是否命中 cargo_names。

如果 priority 是 hard：

hard_invalid_reasons += forbidden_cargo_category

如果 priority 是 soft：

soft_risk_reasons += forbidden_cargo_category_soft_risk
5.2 forbid_action_in_time_window

用于：

夜间不接单
凌晨不空驶
午休不接单
23:00-04:00 不接单不空驶

通用判断：

候选动作执行时间区间是否与 forbidden time window overlap。

这里不关心它叫 quiet_hours、lunch_break 还是 night_rest。

只关心：

action interval 与 time_window 是否重叠。
5.3 continuous_rest

用于：

每天连续休息不少于 8 小时
每天停车休息至少 4 小时
每日连续熄火休息 3 小时

通用判断：

今天已经有多少连续 wait/rest？
当前候选会不会破坏完成 rest 的机会？
wait candidate 能不能增加连续 rest？

不要直接 Python 强制 wait。

应该：

1. 对接单候选标注 daily_rest_risk
2. 对 wait 候选标注 satisfies_continuous_rest
3. 让 Advisor 选择
5.4 operate_within_area

用于：

只在深圳内跑
不出某市
在某区域内停车/行驶

通用判断：

pickup / destination / reposition target 是否在 area_bounds 内。

如果 hard：

hard_invalid

如果 soft：

soft_risk
5.5 avoid_zone

用于：

不去某个区域
避开某城市
不进入某片区

通用判断：

pickup / destination / reposition target 是否落入禁止区域。
5.6 max_distance

用于：

单笔装卸距离不超过 X km
空驶不超过 X km
单程距离不超过 X km

通用判断：

pickup_deadhead_km / haul_distance_km / total_distance_km 是否超过 limit。
5.7 be_at_location_by_deadline