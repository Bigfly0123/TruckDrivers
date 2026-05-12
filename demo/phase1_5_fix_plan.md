# Phase 1.5 Bugfix 与主流程修复说明

## 0. 当前问题背景

Phase 1.5 已经完成了部分框架瘦身：

```text
1. fallback 不再主动 take_order
2. CandidateSafetyFilter 已经开始向 CandidateGrouper 转换
3. agent_decisions.jsonl 已经开始记录结构化日志
4. SafetyGate / Advisor / CandidateGrouper 的职责正在重新拆分
```
但是最新运行 D001 时出现了新的问题：

AttributeError: 'BlockedCandidate' object has no attribute 'hard_invalid_reasons'

同时从当前代码和日志可以看出，还有几个 Phase 1.5 主流程问题需要一起修复：

1. 日志函数因为候选结构不兼容而中断决策
2. Advisor 仍然可能只在 trigger 非空时才调用
3. fallback reason 不够准确
4. CandidateGrouper 输出中仍混有旧结构 BlockedCandidate
5. CandidateSafetyFilter / CandidateGrouper 命名和职责还没有完全理顺
6. _advisor_allowed 可能因为 repeated context 跳过 Advisor，导致 fallback wait
7. 日志构造函数没有做到 fail-safe

本次修复目标：

先修 bug，再修主流程，确保有候选时一定由 Advisor 决策，日志永远不能影响最终 action。
1. 本次必须修复的问题列表
问题 1：BlockedCandidate 与新 Candidate 结构不兼容
报错日志
ERROR [agent.decision_service] decision failed for driver_id=D001: 'BlockedCandidate' object has no attribute 'hard_invalid_reasons'

Traceback:
  File "demo/agent/model_decision_service.py", line 117, in decide
    log_entry = self._init_decision_log_entry(...)
  File "demo/agent/model_decision_service.py", line 409, in _init_decision_log_entry
    for reason in c.hard_invalid_reasons:
AttributeError: 'BlockedCandidate' object has no attribute 'hard_invalid_reasons'
当前状态

当前候选池中至少存在两种对象：

1. 新 Candidate / ActionCandidate
   - 有 hard_invalid_reasons
   - 有 soft_risk_reasons
   - 有 final_action
   - 有 facts

2. 旧 BlockedCandidate
   - 没有 hard_invalid_reasons
   - 可能只有 reason / reasons / block_reason 等旧字段

但是 _init_decision_log_entry() 把所有 hard invalid candidates 都当成新结构访问：

for reason in c.hard_invalid_reasons:
    ...

这会导致日志构造直接崩溃，进而中断整个决策流程。

修复目标
1. 日志函数必须兼容旧 Candidate / BlockedCandidate
2. 日志构造不能因为字段缺失而中断决策
3. CandidateGrouper 最好统一输出结构
2. 修复方案 A：先做兼容 helper，立即止血

请在 demo/agent/model_decision_service.py 中增加候选字段读取 helper。

2.1 新增 hard reason helper
def _candidate_hard_reasons(self, candidate) -> list[str]:
    """Return hard invalid reasons from both new Candidate and legacy BlockedCandidate."""
    reasons = getattr(candidate, "hard_invalid_reasons", None)
    if reasons:
        return [str(r) for r in reasons]

    reason = getattr(candidate, "reason", None)
    if reason:
        return [str(reason)]

    reasons = getattr(candidate, "reasons", None)
    if reasons:
        return [str(r) for r in reasons]

    block_reason = getattr(candidate, "block_reason", None)
    if block_reason:
        return [str(block_reason)]

    rejection_code = getattr(candidate, "rejection_code", None)
    if rejection_code:
        return [str(rejection_code)]

    risk_code = getattr(candidate, "risk_code", None)
    if risk_code:
        return [str(risk_code)]

    return ["unknown_hard_invalid"]
2.2 新增 soft reason helper
def _candidate_soft_reasons(self, candidate) -> list[str]:
    """Return soft risk reasons from both new Candidate and legacy structures."""
    reasons = getattr(candidate, "soft_risk_reasons", None)
    if reasons:
        return [str(r) for r in reasons]

    reasons = getattr(candidate, "risk_reasons", None)
    if reasons:
        return [str(r) for r in reasons]

    risk_code = getattr(candidate, "risk_code", None)
    severity = getattr(candidate, "severity", None)
    if risk_code and severity == "soft":
        return [str(risk_code)]

    return []
2.3 新增 candidate_id helper
def _candidate_id(self, candidate) -> str:
    candidate_id = getattr(candidate, "candidate_id", None)
    if candidate_id:
        return str(candidate_id)

    cargo_id = getattr(candidate, "cargo_id", None)
    if cargo_id:
        return f"take_order_{cargo_id}"

    action = getattr(candidate, "final_action", None)
    if isinstance(action, dict):
        if action.get("cargo_id"):
            return f"take_order_{action.get('cargo_id')}"
        if action.get("type"):
            return f"{action.get('type')}_unknown"

    return "unknown_candidate"
2.4 修改 _init_decision_log_entry()

把所有类似下面的代码：

for reason in c.hard_invalid_reasons:
    ...

改成：

for reason in self._candidate_hard_reasons(c):
    ...

把：

for reason in c.soft_risk_reasons:
    ...

改成：

for reason in self._candidate_soft_reasons(c):
    ...

把直接读取：

c.candidate_id

改成：

self._candidate_id(c)
3. 修复方案 B：长期修复，统一 CandidateGrouper 输出结构

上面的 helper 是止血修复，但长期应该在 CandidateGrouper 层统一候选结构。

请在 demo/agent/candidate_safety_filter.py 或新的 candidate_grouper.py 中定义统一视图。

3.1 推荐 CandidateView
from dataclasses import dataclass, field
from typing import Any

@dataclass
class CandidateView:
    candidate_id: str
    action_type: str
    final_action: dict[str, Any]
    facts: dict[str, Any] = field(default_factory=dict)
    hard_invalid_reasons: list[str] = field(default_factory=list)
    soft_risk_reasons: list[str] = field(default_factory=list)
    preference_impacts: list[Any] = field(default_factory=list)
    source: str = "unknown"
    raw: Any = None
3.2 推荐转换函数
def to_candidate_view(candidate) -> CandidateView:
    candidate_id = getattr(candidate, "candidate_id", None)
    cargo_id = getattr(candidate, "cargo_id", None)

    final_action = getattr(candidate, "final_action", None)
    if final_action is None:
        action = getattr(candidate, "action", None)
        if isinstance(action, dict):
            final_action = action
        elif cargo_id:
            final_action = {"type": "take_order", "cargo_id": cargo_id}
        else:
            final_action = {}

    if not candidate_id:
        if isinstance(final_action, dict) and final_action.get("cargo_id"):
            candidate_id = f"take_order_{final_action.get('cargo_id')}"
        elif cargo_id:
            candidate_id = f"take_order_{cargo_id}"
        elif isinstance(final_action, dict) and final_action.get("type"):
            candidate_id = f"{final_action.get('type')}_unknown"
        else:
            candidate_id = "unknown_candidate"

    hard_reasons = list(getattr(candidate, "hard_invalid_reasons", []) or [])
    if not hard_reasons:
        for attr in ("reason", "reasons", "block_reason", "rejection_code"):
            value = getattr(candidate, attr, None)
            if value:
                if isinstance(value, list):
                    hard_reasons.extend(str(v) for v in value)
                else:
                    hard_reasons.append(str(value))

    soft_reasons = list(getattr(candidate, "soft_risk_reasons", []) or [])
    if not soft_reasons:
        risk_reasons = getattr(candidate, "risk_reasons", None)
        if risk_reasons:
            soft_reasons.extend(str(r) for r in risk_reasons)

    facts = getattr(candidate, "facts", None)
    if facts is None:
        facts = {}

    source = getattr(candidate, "source", None) or candidate.__class__.__name__

    action_type = getattr(candidate, "action_type", None)
    if not action_type:
        if isinstance(final_action, dict):
            action_type = final_action.get("type", "unknown")
        else:
            action_type = "unknown"

    return CandidateView(
        candidate_id=str(candidate_id),
        action_type=str(action_type),
        final_action=final_action if isinstance(final_action, dict) else {},
        facts=facts if isinstance(facts, dict) else {},
        hard_invalid_reasons=[str(r) for r in hard_reasons],
        soft_risk_reasons=[str(r) for r in soft_reasons],
        preference_impacts=list(getattr(candidate, "preference_impacts", []) or []),
        source=str(source),
        raw=candidate,
    )
3.3 CandidateGrouper 输出必须统一

CandidateGrouper 不应该直接把旧 BlockedCandidate 原样传出去。

应该：

views = [to_candidate_view(c) for c in candidates]

valid_candidates = [
    c for c in views
    if not c.hard_invalid_reasons and not c.soft_risk_reasons
]

soft_risk_candidates = [
    c for c in views
    if not c.hard_invalid_reasons and c.soft_risk_reasons
]

hard_invalid_candidates = [
    c for c in views
    if c.hard_invalid_reasons
]

这样后面所有模块都能稳定访问：

candidate.hard_invalid_reasons
candidate.soft_risk_reasons
candidate.candidate_id
candidate.final_action
4. 日志构造必须 fail-safe
4.1 当前问题

_init_decision_log_entry() 当前一旦报错，整个 decide() 会进入 exception fallback。

这是不允许的。

日志系统只能辅助分析，不能影响最终动作。

4.2 必须修改

在 decide() 中调用日志初始化时增加保护：

try:
    log_entry = self._init_decision_log_entry(...)
except Exception as exc:
    logger.exception("failed to build decision log entry for driver_id=%s", driver_id)
    log_entry = {
        "driver_id": driver_id,
        "log_error": str(exc),
        "log_error_type": exc.__class__.__name__,
    }

后续写日志也必须保护：

try:
    self._write_decision_log(log_entry)
except Exception:
    logger.exception("failed to write decision log for driver_id=%s", driver_id)
4.3 验收标准

日志构造失败时，不允许出现：

decision failed for driver_id=...
source=exception

除非真正的决策逻辑失败。

日志失败只能记录：

{
  "log_error": "...",
  "log_error_type": "AttributeError"
}

不能影响最终 action。

5. 修复主流程：有候选必须调用 Advisor
5.1 当前问题

当前 ModelDecisionService.decide() 里 Advisor 可能仍然被 trigger gate 控制：

trigger = self._advisor_trigger(...)

if trigger is not None and self._advisor_allowed(...):
    advisor_result = self._advisor.advise(...)
else:
    fallback wait

这会导致：

有正常候选，但 trigger 为 None
-> Advisor 不调用
-> fallback wait

在 Phase 1.5 中，这是不允许的。

5.2 必须修改

核心规则：

只要 advisor_candidates 非空，就必须调用 Advisor。

推荐改法：

advisor_candidates = self._build_advisor_candidates(...)

has_advisor_candidates = bool(advisor_candidates)

trigger = self._advisor_trigger(...)

if trigger is None and has_advisor_candidates:
    trigger = "normal_candidate_decision"

if not has_advisor_candidates:
    fallback_reason = "no_candidates_available"
    return self._fallback_wait(...)

# 到这里，只要有 candidates，就调用 Advisor
advisor_result = self._advisor.advise(
    ...,
    trigger=trigger,
    candidates=advisor_candidates,
)
5.3 禁止行为

禁止出现：

if trigger is None:
    return fallback_wait()

除非：

advisor_candidates 为空
5.4 验收标准

日志中不允许出现：

{
  "total_candidate_count": 10,
  "advisor_called": false,
  "fallback_used": true
}

除非 fallback_reason 是：

llm_api_failed
llm_json_parse_failed
advisor_invalid_candidate
safety_rejection_retry_failed

正常情况下：

有候选 -> advisor_called = true
6. 暂时禁用 repeated-context Advisor skip
6.1 当前问题

如果 _advisor_allowed() 因为 repeated context 返回 False，那么 Phase 1.5 后会出现：

有候选
-> Advisor 被 skip
-> fallback wait

这会重新造成 Python 决策。

6.2 调试阶段处理

Phase 1.5 调试阶段请先禁用 repeated-context skip。

最简单：

advisor_allowed = True

或者：

if has_advisor_candidates:
    advisor_allowed = True
else:
    advisor_allowed = self._advisor_allowed(...)
6.3 后续优化

等 D001~D003 能完整跑完，再考虑 token 优化。
不要在当前阶段为了省 token 跳过 Advisor。

7. 修复 fallback_reason
7.1 当前问题

新日志里出现：

"fallback_reason": "no_advisor_or_advisor_failed"

这个 reason 太模糊。它可能表示：

1. 没有候选
2. Advisor 没被调用
3. Advisor API 失败
4. Advisor JSON 失败
5. Advisor 输出非法

这不利于调试。

7.2 必须拆分 reason

允许的 fallback reason：

no_candidates_available
llm_api_failed
llm_json_parse_failed
advisor_invalid_candidate
advisor_invalid_action_schema
safety_rejection_retry_failed
no_submitable_action
unexpected_exception
7.3 禁止的 reason

不要再使用：

no_advisor_or_advisor_failed

不要使用：

has_valid_candidate
best_score_candidate
budget_pressure
no_safe_candidate_but_soft_risk_exists
7.4 第 0 步无货源时

如果：

visible_cargo_count = 0
total_candidate_count = 0

合理 fallback 是：

{
  "fallback_used": true,
  "fallback_reason": "no_candidates_available",
  "final_action": {
    "type": "wait",
    "duration_minutes": 60
  }
}
8. CandidateGrouper 命名和职责修复
8.1 当前问题

代码中可能仍然有：

self._candidate_safety_filter = CandidateGrouper()
candidate_pool = self._candidate_safety_filter.apply(...)

这会导致命名混乱，也容易让后续代码继续把它当 filter。

8.2 必须修改

改成：

self._candidate_grouper = CandidateGrouper()
grouped_candidates = self._candidate_grouper.group(raw_candidates)

或者：

candidate_pool = raw_candidate_pool
grouped_candidates = self._candidate_grouper.group(candidate_pool.all_candidates)
8.3 CandidateGrouper 不允许有 apply 过滤语义

避免：

apply()
filter()
block()
move_to_blocked()

推荐：

group()
split()
summarize()
8.4 禁止日志

不应该再出现：

safety filter: candidates moved to blocked

如果确实有 hard invalid 统计，应改成：

candidate grouper: total=15 valid=0 soft_risk=0 hard_invalid=15

并且 reasons 要清楚。

9. 不要让 day 30 / remove_time_expired 误导调试

最新报错时日志是：

day=30
mod=1431
rem_d=0.0
items=15
hard_invalid=15
filters={'remove_time_expired': 15}

这表示：

已经是最后一天最后几分钟
所有货源都过期

这种情况下：

valid=0
soft_risk=0
hard_invalid=15
fallback wait 9 minutes

是合理的。

但是不合理的是：

日志函数因为 hard_invalid candidate 字段不兼容而崩溃

因此这次 bug 不代表候选判断一定错，主要是结构兼容和日志 fail-safe 问题。

10. 需要全局搜索并修复的关键词

请运行：

rg "hard_invalid_reasons|soft_risk_reasons|BlockedCandidate|no_advisor_or_advisor_failed|_advisor_trigger|_advisor_allowed|candidate_safety_filter|CandidateGrouper|moved to blocked|source=exception" demo/agent

逐项处理：

10.1 hard_invalid_reasons

检查是否直接访问旧对象字段。
需要改成 helper 或统一 CandidateView。

10.2 soft_risk_reasons

同上。

10.3 BlockedCandidate

检查是否还被直接传到日志、Advisor、SafetyGate。
尽量在 CandidateGrouper 转成 CandidateView。

10.4 no_advisor_or_advisor_failed

替换为明确 reason。

10.5 _advisor_trigger

确保 trigger 为 None 时，如果有候选，也会变成：

normal_candidate_decision
10.6 _advisor_allowed

Phase 1.5 调试时不要让它跳过 Advisor。

10.7 candidate_safety_filter

改名或至少变量改为：

candidate_grouper
10.8 moved to blocked

删除或改成 hard invalid summary。

10.9 source=exception

如果只是日志错误，不应该进入 source=exception。

11. 修改顺序建议
Step 1：先修日志 AttributeError

目标：

BlockedCandidate 不再导致 hard_invalid_reasons AttributeError

修改：

demo/agent/model_decision_service.py

增加 helper：

_candidate_hard_reasons
_candidate_soft_reasons
_candidate_id

并替换所有直接字段访问。

Step 2：日志构造 fail-safe

目标：

日志错误不影响最终 action

修改：

demo/agent/model_decision_service.py

给：

_init_decision_log_entry
_write_decision_log

加保护。

Step 3：修 Advisor 默认调用逻辑

目标：

有候选必须调用 Advisor

修改：

demo/agent/model_decision_service.py

规则：

trigger None + candidates 非空 -> normal_candidate_decision
candidates 为空 -> no_candidates_available fallback
Step 4：禁用 Advisor skip

目标：

Phase 1.5 调试阶段 Advisor 不因 repeated context 被跳过

修改：

demo/agent/model_decision_service.py

暂时：

advisor_allowed = True

或保证有候选时为 True。

Step 5：修 fallback_reason

目标：

fallback reason 明确可分析

修改：

demo/agent/model_decision_service.py

删除：

no_advisor_or_advisor_failed

改成具体原因。

Step 6：统一 CandidateGrouper 输出

目标：

后续不再混用 BlockedCandidate / Candidate

修改：

demo/agent/candidate_safety_filter.py

或新增：

demo/agent/candidate_grouper.py

加入：

CandidateView
to_candidate_view
group()
12. 验收标准
12.1 bug 验收

重新跑 D001 后，不允许出现：

'BlockedCandidate' object has no attribute 'hard_invalid_reasons'

不允许因为日志错误出现：

source=exception
12.2 Advisor 调用验收

只要有候选，日志必须显示：

{
  "advisor_called": true
}

除非明确：

llm_api_failed
llm_json_parse_failed
advisor_invalid_candidate
safety_rejection_retry_failed

不允许：

{
  "total_candidate_count": 10,
  "advisor_called": false,
  "fallback_used": true,
  "fallback_reason": "no_advisor_or_advisor_failed"
}
12.3 fallback 验收

Fallback 不允许主动 take_order。

允许：

{
  "fallback_used": true,
  "fallback_reason": "no_candidates_available",
  "final_action": {
    "type": "wait",
    "duration_minutes": 60
  }
}

不允许：

{
  "fallback_used": true,
  "final_action": {
    "type": "take_order"
  }
}
12.4 CandidateGrouper 验收

日志应类似：

candidate grouper: total=15 valid=0 soft_risk=0 hard_invalid=15

但不应该报字段错误。

不应该出现：

moved to blocked
12.5 day 30 场景验收

如果处于：

day=30
rem_d=0.0
all candidates remove_time_expired

允许：

valid=0
soft_risk=0
hard_invalid=N
fallback wait remaining minutes

但必须：

不崩溃
日志正常写入
fallback_reason = no_candidates_available 或 no_submitable_action
13. 修完后请输出总结

完成修改后，请输出：

1. 修改了哪些文件
2. 是否新增 CandidateView / helper
3. 是否修复 BlockedCandidate 兼容问题
4. _init_decision_log_entry 是否 fail-safe
5. 有候选时是否一定调用 Advisor
6. _advisor_allowed 是否暂时禁用 repeated-context skip
7. fallback_reason 是否拆分
8. no_advisor_or_advisor_failed 是否删除
9. CandidateGrouper 是否还会 moved to blocked
10. 如何重新运行 D001 测试
14. 最终目标

这次修复完成后，系统应该满足：

1. 日志不会中断决策
2. BlockedCandidate 和 Candidate 不再结构冲突
3. 有候选时 Advisor 必须被调用
4. fallback 只处理真正异常或无候选
5. fallback reason 可追踪
6. CandidateGrouper 只分组，不过滤
7. SafetyGate / Advisor / Fallback 的职责继续保持清晰

一句话：

先让主流程稳定跑通，再继续看收益。