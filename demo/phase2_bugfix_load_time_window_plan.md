# Phase 2 Bugfix：修复 load_time_window_expired 硬校验问题

## 0. 当前状态判断

Phase 2.0 的中度精简主流程已经基本完成。

当前 `ModelDecisionService` 主流程已经明显变短，核心链路基本变成：

```text
Observe
-> PreferenceCompiler
-> CandidateFactBuilder
-> 简单分组 valid / soft_risk / hard_invalid
-> LlmDecisionAdvisor 选择 candidate_id
-> SafetyGate 硬校验
-> 返回动作
```
目前不需要继续大改主流程。

当前优先问题不是“架构臃肿”，而是一个明确的 hard validation bug：

Advisor 选择了 take_order
SafetyGate 通过
但是仿真环境拒绝，原因是 load_time_window_expired

这说明：

CandidateFactBuilder 没有正确把过期/赶不上装货时间窗的订单标成 hard_invalid
SafetyGate 也没有在提交前重复校验装货时间窗

这个问题必须先修。否则后续优化 Advisor、换模型、调 prompt 都没有意义。

1. 本次修复目标

本次只修一个核心问题：

阻止所有必然会触发 load_time_window_expired 的订单进入最终执行。

具体目标：

1. CandidateFactBuilder 中提前标记过期或赶不上装货时间窗的订单为 hard_invalid
2. SafetyGate 中再次复核 take_order 的装货时间窗
3. hard_invalid candidates 不进入 Advisor
4. Advisor 不再选择已经过期或赶不上装货时间窗的订单
5. D001 前 50 步中环境拒绝 load_time_window_expired 次数降为 0

本次不要做：

1. 不要重构主流程
2. 不要恢复复杂 MissionExecutor
3. 不要修改 Advisor 策略
4. 不要新增复杂候选结构
5. 不要让 fallback 接管赚钱
6. 不要顺手做 D009/D010 mission 优化
2. 当前 bug 表现

最新实验中，D001 已经开始接单，这是好现象。

但是有多次 take_order 被仿真环境拒绝，原因是：

load_time_window_expired

这说明这些订单在提交给仿真器之前就应该被标记为：

hard_invalid

而不是进入 Advisor 候选池。

典型错误链路：

CandidateFactBuilder 生成候选
-> 候选没有 hard_invalid_reasons
-> Advisor 选择该候选
-> SafetyGate validate 通过
-> 仿真环境执行失败：load_time_window_expired

正确链路应该是：

CandidateFactBuilder 生成候选
-> 计算到达装货点时间
-> 判断已经超过装货时间窗
-> hard_invalid_reasons 添加 load_time_window_expired / load_time_window_unreachable
-> 不进入 Advisor

SafetyGate 也要做最后兜底：

即使 CandidateFactBuilder 判断遗漏，SafetyGate 也必须拦住。
3. 需要修改的文件

优先修改：

demo/agent/planner.py
demo/agent/safety_gate.py

可能需要新增或调整：

demo/agent/time_window_utils.py

如果已有时间解析工具，也可以复用已有工具，不强制新增文件。

不要修改：

ModelDecisionService 主流程
MissionExecutor
MissionReplanner
LlmMissionPlanner
TaskGraphBuilder
复杂 fallback
4. 核心概念说明
4.1 remove_time 与 load_time_window_end 的区别

当前代码很可能只判断了：

remove_time

但环境拒绝原因是：

load_time_window_expired

这可能表示数据中存在更具体的装货时间窗字段，例如：

load_time_window_end
load_end_time
loading_end_time
load_deadline
pickup_deadline
latest_load_time

如果这些字段存在，应该优先使用这些字段。

如果没有这些字段，再 fallback 到：

remove_time
4.2 当前时间与到达时间

不能只判断：

当前时间 < deadline

还必须判断：

到达装货点时间 <= deadline

因为司机可能现在没过期，但开到装货点时已经过期。

应该计算：

arrival_minute = state.current_minute + pickup_minutes

如果：

arrival_minute > deadline_minute

则候选不可执行。

建议加安全 buffer：

LOAD_WINDOW_BUFFER_MINUTES = 5

即：

arrival_minute + 5 > deadline_minute

就标记为不可执行。

这样可以避免边界误差导致环境拒绝。

5. CandidateFactBuilder 修改要求
5.1 新增统一 deadline 解析

在 planner.py 中新增或复用函数：

def _parse_cargo_deadline_minute(self, cargo: dict) -> int | None:
    ...

优先读取以下字段：

deadline_keys = [
    "load_time_window_end",
    "load_end_time",
    "loading_end_time",
    "load_deadline",
    "pickup_deadline",
    "latest_load_time",
    "remove_time",
]

伪代码：

def _parse_cargo_deadline_minute(self, cargo: dict) -> int | None:
    for key in (
        "load_time_window_end",
        "load_end_time",
        "loading_end_time",
        "load_deadline",
        "pickup_deadline",
        "latest_load_time",
        "remove_time",
    ):
        value = cargo.get(key)
        if value is None or value == "":
            continue
        parsed = self._parse_time_to_minute(value)
        if parsed is not None:
            return parsed
    return None

注意：

不要因为某个字段解析失败就直接报错。
继续尝试下一个字段。
5.2 时间解析必须兼容当前数据格式

时间字段可能是：

2026-03-01 08:00:00
2026-03-01 08:00
03-01 08:00
08:00
整数分钟

如果已有 _parse_remove_time()，可以复用或扩展它。

要求：

1. 返回值必须是全月绝对分钟
2. 与 state.current_minute 使用同一时间基准
3. 解析失败返回 None，不要抛异常

如果当前项目已经有类似函数：

_parse_remove_time
_parse_time_to_minute

可以直接扩展，不要重复写太多。

5.3 Candidate facts 必须记录时间窗信息

每个 take_order candidate 的 facts 中必须增加：

{
  "pickup_minutes": 38,
  "pickup_arrival_minute": 12383,
  "cargo_deadline_minute": 12370,
  "load_window_buffer_minutes": 5
}

如果解析不到 deadline：

{
  "cargo_deadline_minute": null
}

同时可以记录：

{
  "deadline_source": "load_time_window_end"
}

方便调试。

5.4 hard_invalid 规则

新增规则：

LOAD_WINDOW_BUFFER_MINUTES = 5

deadline_minute = self._parse_cargo_deadline_minute(cargo)
arrival_minute = state.current_minute + pickup_minutes

facts["pickup_minutes"] = pickup_minutes
facts["pickup_arrival_minute"] = arrival_minute
facts["cargo_deadline_minute"] = deadline_minute
facts["load_window_buffer_minutes"] = LOAD_WINDOW_BUFFER_MINUTES

if deadline_minute is not None:
    if state.current_minute >= deadline_minute:
        hard_invalid.append("load_time_window_expired")
    elif arrival_minute + LOAD_WINDOW_BUFFER_MINUTES > deadline_minute:
        hard_invalid.append("load_time_window_unreachable")

含义：

load_time_window_expired:
  当前时间已经过了装货截止时间

load_time_window_unreachable:
  当前还没过期，但司机到达时已经赶不上
5.5 保留旧字段，但统一语义

如果代码里已经有：

remove_time_expired
pickup_unreachable

可以保留，但建议同时加更明确的新 reason：

load_time_window_expired
load_time_window_unreachable

例如：

if state.current_minute >= deadline_minute:
    hard_invalid.append("load_time_window_expired")
    hard_invalid.append("remove_time_expired")

但不建议重复太多，最好统一成环境能对应的 reason。

5.6 hard_invalid 不进入 Advisor

确认 ModelDecisionService 中分组逻辑满足：

executable_candidates = valid_candidates + soft_risk_candidates

而不是：

all_candidates

也就是说：

hard_invalid_candidates 只能用于日志
不能传给 Advisor
6. SafetyGate 修改要求
6.1 当前问题

当前 SafetyGate._validate_take_order() 只检查：

cargo_id 是否存在于当前 visible cargo

但没有复核：

当前时间是否已经过装货截止
到达装货点时是否已经过装货截止

这导致 Advisor 选出的过期单通过 SafetyGate。

6.2 SafetyGate 必须重复校验时间窗

在 safety_gate.py 的 take_order 校验中新增：

1. 找到 matched cargo
2. 解析 cargo deadline
3. 计算当前司机到达装货点时间
4. 如果过期或赶不上，拒绝

伪代码：

LOAD_WINDOW_BUFFER_MINUTES = 5

def _validate_take_order(self, action: dict, state, visible_items: list[dict]) -> tuple[bool, str]:
    cargo_id = str(action.get("params", {}).get("cargo_id", ""))

    item = self._find_visible_item(cargo_id, visible_items)
    if item is None:
        return False, "cargo_not_visible"

    cargo = item.get("cargo") if isinstance(item.get("cargo"), dict) else item

    pickup_minutes = self._estimate_pickup_minutes(state, item, cargo)
    arrival_minute = state.current_minute + pickup_minutes

    deadline_minute = self._parse_cargo_deadline_minute(cargo)

    if deadline_minute is not None:
        if state.current_minute >= deadline_minute:
            return False, "load_time_window_expired"
        if arrival_minute + LOAD_WINDOW_BUFFER_MINUTES > deadline_minute:
            return False, "load_time_window_unreachable"

    return True, ""
6.3 pickup_minutes 计算方式

优先使用 item 中已有字段：

pickup_minutes
estimated_pickup_minutes
time_to_pickup_minutes

如果没有，则根据距离估计：

distance_km / speed_km_per_minute

可以使用当前项目已有速度常量。

简单保守估计：

speed_km_per_hour = 60.0
pickup_minutes = math.ceil(distance_km / speed_km_per_hour * 60)

如果 item 中已经有 distance_km：

pickup_minutes = math.ceil(float(distance_km))

因为 60km/h 下 1km≈1min。

如果无法估计 pickup_minutes：

不要直接通过。
可以保守返回 False, "pickup_time_unknown"

但这可能过于保守。建议先：

无法估计时记录 warning，但不拒绝

除非当前仍大量出现过期单。

6.4 SafetyGate 不要做策略判断

本次只增加 hard validation。

SafetyGate 仍然不能拒绝：

soft risk
preference penalty
budget risk
daily rest soft risk
mission soft risk
收益不高

只拒绝必然会导致环境拒绝的动作。

7. 日志要求

为了确认修复是否有效，需要在 candidate facts 或 debug 日志中输出时间窗信息。

建议在 agent_decisions.jsonl 中对被选中的 candidate 增加：

{
  "selected_candidate_id": "take_order_790",
  "selected_candidate_facts": {
    "pickup_minutes": 38,
    "pickup_arrival_minute": 12383,
    "cargo_deadline_minute": 12370,
    "hard_invalid_reasons": []
  }
}

如果日志不想太长，可以至少在 server log 中对 SafetyGate 拒绝输出：

SafetyGate reject take_order cargo_id=790 reason=load_time_window_unreachable current=12345 arrival=12383 deadline=12370
8. 测试方法
8.1 先跑 D001 前 50 步

不要直接跑完整 10 个司机。

先跑 D001 前 50 步，观察：

1. 是否还出现 load_time_window_expired 环境拒绝
2. SafetyGate 是否提前拒绝了类似订单
3. hard_invalid_count 是否上升
4. take_order 成功率是否提升
5. gross_income 是否继续增长
8.2 检查日志

搜索：

rg "load_time_window_expired|load_time_window_unreachable" demo/results/logs demo/results

期望结果：

1. 不应再在 simulation_orchestrator.log 里出现大量 accepted=false detail=load_time_window_expired
2. 可以在 agent_decisions/server_runtime 里看到候选被 hard_invalid 或 SafetyGate 拒绝
8.3 检查 actions

确认 action 文件中：

take_order 的 accepted=false 明显减少
9. 验收标准
9.1 必须满足
1. D001 前 50 步中，环境返回 load_time_window_expired 次数为 0 或显著下降
2. SafetyGate 能拒绝过期/赶不上装货时间窗的订单
3. hard_invalid_candidates 中出现 load_time_window_expired / load_time_window_unreachable
4. Advisor 不再选择这些 hard_invalid candidates
5. validation_error = 0
6. gross_income > 0
9.2 行为预期

修复后可能出现：

hard_invalid_count 上升
valid_count 下降

这是正常的，因为以前错误进入 Advisor 的订单现在被正确过滤了。

不要因为 valid_count 变少就回滚。

10. 本次不要做的事情

不要做：

1. 不要重构 ModelDecisionService
2. 不要恢复 CandidateGrouper
3. 不要恢复 MissionExecutor
4. 不要改 Advisor prompt
5. 不要做 D009/D010 mission
6. 不要让 fallback 接单
7. 不要让 Python 根据 score 直接接单

当前任务就是修：

load_time_window_expired hard validation
11. 修完后请输出总结

请输出：

1. 修改了哪些文件
2. 新增了哪些 deadline 字段解析
3. CandidateFactBuilder 如何判断 load_time_window_expired
4. SafetyGate 如何复核 take_order 时间窗
5. candidate facts 新增了哪些调试字段
6. D001 前 50 步测试结果
7. load_time_window_expired 是否消失
8. take_order 成功率是否提升
9. 是否有新的异常