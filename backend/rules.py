"""权威状态规则层（authoritative state rules）。

设计原则
--------
语言模型只负责**提议**状态变更，是否生效由本层的确定性规则裁决。

当前覆盖好感度（affinity）—— 在加规则层之前，它是整个系统里唯一由 LLM 直接决定的
可变状态：

    # 旧实现（backend/relationship_manager.py）
    new_affinity = current_affinity + analysis["change_amount"]   # 完全由 LLM 给出
    new_affinity = max(0.0, min(100.0, new_affinity))             # 只做区间钳制

也就是说，玩家只要能在对话里说服 LLM，就能一次性把好感度推满。现在改为：

    verdict = evaluate_affinity_change(current, proposed_delta, sentiment, reason)
    new_affinity = verdict.new_value

每条规则都有编号，触发时写进日志和 ``metrics_*.csv``（``affinity_rule_status`` /
``affinity_rule_notes`` 两列），因此"LLM 提议了多少、规则实际放行多少"是可统计的。

规则清单
--------
R0 有限性        提议值必须是有限数，NaN / inf / 非数值一律按 0 处理
R1 正向单轮上限  正变化不超过 AFFINITY_MAX_POS_DELTA（默认 10）
R2 负向单轮上限  负变化不超过 AFFINITY_MAX_NEG_DELTA（默认 15）
R3 正向需情感证据 sentiment 不是 positive 时，正向变化直接拒绝
R4 分数上下界    结果限制在 [0, 100]，越界部分被截断并记录

为什么默认正向上限是 10 而不是更小
----------------------------------
已归档的四组实验（`experiments/`）采集于"无规则层"的旧版本，观测到的单轮变化最大为
**+7**。把默认上限设为 10 有两个好处：

1. 那些数据在启用规则层之后仍然可复现（不会被新规则改写出不同的好感度轨迹）；
2. 仍足以拦住"给加 50 好感度""把好感度调到 100"这类提示词越权。

需要更严格时用环境变量覆盖，例如 ``AFFINITY_MAX_POS_DELTA=5``。

注意：本模块是**纯函数**，不依赖任何第三方库，也不依赖 LLM，可以直接单元测试。
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Dict, List

AFFINITY_MIN = 0.0
AFFINITY_MAX = 100.0

DEFAULT_MAX_POS_DELTA = 10.0
DEFAULT_MAX_NEG_DELTA = 15.0


def _env_float(name: str, default: float) -> float:
    """读取浮点环境变量；缺失或非法时回退默认值。"""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def max_positive_delta() -> float:
    return abs(_env_float("AFFINITY_MAX_POS_DELTA", DEFAULT_MAX_POS_DELTA))


def max_negative_delta() -> float:
    return abs(_env_float("AFFINITY_MAX_NEG_DELTA", DEFAULT_MAX_NEG_DELTA))


@dataclass
class AffinityVerdict:
    """一条好感度变更的裁决结果。"""

    current: float
    proposed_delta: float
    applied_delta: float
    new_value: float
    status: str                       # applied / clipped / rejected / noop
    notes: List[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return abs(self.applied_delta) > 1e-9

    def as_dict(self) -> Dict[str, object]:
        """展开成可以直接写进 metrics CSV 的字段。"""
        return {
            "affinity_current": round(self.current, 2),
            "affinity_proposed_delta": round(self.proposed_delta, 2),
            "affinity_applied_delta": round(self.applied_delta, 2),
            "affinity_rule_status": self.status,
            "affinity_rule_notes": "|".join(self.notes),
        }


def evaluate_affinity_change(
    current: float,
    proposed_delta: float,
    sentiment: str = "neutral",
    reason: str = "",
    min_value: float = AFFINITY_MIN,
    max_value: float = AFFINITY_MAX,
) -> AffinityVerdict:
    """对 LLM 提议的好感度变化做裁决。

    Args:
        current: 当前好感度。
        proposed_delta: LLM 建议的变化量（可为负）。
        sentiment: LLM 给出的情感标签（positive / neutral / negative）。
        reason: LLM 给出的原因，仅用于日志。
        min_value: 分数下界。
        max_value: 分数上界。

    Returns:
        AffinityVerdict，其中 ``applied_delta`` 才是允许写入状态的值。
    """
    notes: List[str] = []

    # --- R0 有限性 ---
    try:
        cur = float(current)
    except (TypeError, ValueError):
        cur = 50.0
        notes.append("R0 当前值非数值，回退到 50")
    if not math.isfinite(cur):
        cur = 50.0
        notes.append("R0 当前值非有限，回退到 50")

    try:
        raw_delta = float(proposed_delta)
    except (TypeError, ValueError):
        raw_delta = 0.0
        notes.append("R0 提议值非数值，按 0 处理")
    if not math.isfinite(raw_delta):
        raw_delta = 0.0
        notes.append("R0 提议值非有限，按 0 处理")

    raw_delta = round(raw_delta, 2)
    delta = raw_delta

    # --- R3 正向需情感证据 ---
    senti = (sentiment or "").strip().lower()
    if delta > 0 and senti != "positive":
        notes.append(
            "R3 正向变化缺少 positive 情感证据(sentiment=%s)，已拒绝"
            % (senti or "empty")
        )
        return AffinityVerdict(cur, raw_delta, 0.0, cur, "rejected", notes)

    # --- R1 / R2 单轮上下限 ---
    if delta > 0:
        cap = max_positive_delta()
        if delta > cap:
            notes.append("R1 正向 %.2f 超过单轮上限 %.2f，已截断" % (delta, cap))
            delta = cap
    elif delta < 0:
        cap = max_negative_delta()
        if abs(delta) > cap:
            notes.append("R2 负向 %.2f 超过单轮上限 -%.2f，已截断" % (delta, cap))
            delta = -cap

    if abs(delta) < 1e-9:
        notes.append("变化量为 0，状态不变")
        return AffinityVerdict(cur, raw_delta, 0.0, cur, "noop", notes)

    # --- R4 分数上下界 ---
    applied = delta
    target = cur + delta
    if target < min_value:
        applied = min_value - cur
        notes.append("R4 触及下界 %.0f，delta 由 %.2f 调整为 %.2f" % (min_value, delta, applied))
    elif target > max_value:
        applied = max_value - cur
        notes.append("R4 触及上界 %.0f，delta 由 %.2f 调整为 %.2f" % (max_value, delta, applied))

    applied = round(applied, 2)
    status = "clipped" if abs(applied - raw_delta) > 1e-9 else "applied"
    if not notes and reason:
        notes.append("通过全部规则（%s）" % reason.strip()[:20])

    return AffinityVerdict(
        current=cur,
        proposed_delta=raw_delta,
        applied_delta=applied,
        new_value=round(cur + applied, 2),
        status=status,
        notes=notes,
    )
