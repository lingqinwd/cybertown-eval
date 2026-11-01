"""好感度规则层的单元测试（纯标准库，不需要模型、不需要网络、不需要 GPU）。

运行：
    python tests/test_affinity_rules.py
    # 或
    python -m pytest tests/ -q
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from rules import (  # noqa: E402
    DEFAULT_MAX_NEG_DELTA,
    DEFAULT_MAX_POS_DELTA,
    evaluate_affinity_change,
)


class TestPositiveCap(unittest.TestCase):
    """R1：正向单轮上限。"""

    def test_normal_increase_passes(self):
        v = evaluate_affinity_change(current=50, proposed_delta=5, sentiment="positive", reason="友好问候")
        self.assertEqual(v.status, "applied")
        self.assertAlmostEqual(v.applied_delta, 5)
        self.assertAlmostEqual(v.new_value, 55)

    def test_prompt_injection_is_clipped(self):
        """玩家要求"直接把好感度调到 100"，LLM 提议 +50，规则层必须截断。"""
        v = evaluate_affinity_change(current=50, proposed_delta=50, sentiment="positive", reason="玩家要求")
        self.assertEqual(v.status, "clipped")
        self.assertAlmostEqual(v.applied_delta, DEFAULT_MAX_POS_DELTA)
        self.assertAlmostEqual(v.new_value, 50 + DEFAULT_MAX_POS_DELTA)
        self.assertTrue(any("R1" in n for n in v.notes))

    def test_archived_observation_is_reproducible(self):
        """已归档数据里观测到的最大单轮变化是 +7，启用规则层后必须仍然生效。"""
        v = evaluate_affinity_change(current=50, proposed_delta=7, sentiment="positive")
        self.assertEqual(v.status, "applied")
        self.assertAlmostEqual(v.new_value, 57)


class TestEvidenceRule(unittest.TestCase):
    """R3：正向变化必须有 positive 情感证据。"""

    def test_positive_without_evidence_rejected(self):
        v = evaluate_affinity_change(current=50, proposed_delta=5, sentiment="neutral")
        self.assertEqual(v.status, "rejected")
        self.assertAlmostEqual(v.applied_delta, 0)
        self.assertAlmostEqual(v.new_value, 50)
        self.assertTrue(any("R3" in n for n in v.notes))

    def test_negative_without_evidence_allowed(self):
        """负向变化不要求 positive 证据。"""
        v = evaluate_affinity_change(current=50, proposed_delta=-5, sentiment="negative")
        self.assertEqual(v.status, "applied")
        self.assertAlmostEqual(v.new_value, 45)


class TestNegativeCap(unittest.TestCase):
    """R2：负向单轮上限。"""

    def test_harsh_penalty_clipped(self):
        v = evaluate_affinity_change(current=50, proposed_delta=-99, sentiment="negative")
        self.assertEqual(v.status, "clipped")
        self.assertAlmostEqual(v.applied_delta, -DEFAULT_MAX_NEG_DELTA)


class TestBounds(unittest.TestCase):
    """R4：分数上下界。"""

    def test_upper_bound(self):
        v = evaluate_affinity_change(current=98, proposed_delta=10, sentiment="positive")
        self.assertAlmostEqual(v.new_value, 100)
        self.assertAlmostEqual(v.applied_delta, 2)
        self.assertTrue(any("R4" in n for n in v.notes))

    def test_lower_bound(self):
        v = evaluate_affinity_change(current=3, proposed_delta=-15, sentiment="negative")
        self.assertAlmostEqual(v.new_value, 0)
        self.assertAlmostEqual(v.applied_delta, -3)


class TestMalformed(unittest.TestCase):
    """R0：非法输入不得污染状态。"""

    def test_nan(self):
        v = evaluate_affinity_change(current=50, proposed_delta=float("nan"), sentiment="positive")
        self.assertAlmostEqual(v.applied_delta, 0)
        self.assertAlmostEqual(v.new_value, 50)
        self.assertTrue(any("R0" in n for n in v.notes))

    def test_inf(self):
        v = evaluate_affinity_change(current=50, proposed_delta=float("inf"), sentiment="positive")
        self.assertAlmostEqual(v.applied_delta, 0)

    def test_string(self):
        v = evaluate_affinity_change(current=50, proposed_delta="abc", sentiment="positive")
        self.assertAlmostEqual(v.applied_delta, 0)

    def test_bad_current(self):
        v = evaluate_affinity_change(current=None, proposed_delta=3, sentiment="positive")
        self.assertAlmostEqual(v.current, 50)
        self.assertAlmostEqual(v.new_value, 53)


class TestNoopAndEnv(unittest.TestCase):
    def test_zero_delta(self):
        v = evaluate_affinity_change(current=50, proposed_delta=0, sentiment="positive")
        self.assertEqual(v.status, "noop")
        self.assertFalse(v.changed)

    def test_env_override(self):
        old = os.environ.get("AFFINITY_MAX_POS_DELTA")
        os.environ["AFFINITY_MAX_POS_DELTA"] = "3"
        try:
            v = evaluate_affinity_change(current=50, proposed_delta=9, sentiment="positive")
            self.assertAlmostEqual(v.applied_delta, 3)
        finally:
            if old is None:
                os.environ.pop("AFFINITY_MAX_POS_DELTA", None)
            else:
                os.environ["AFFINITY_MAX_POS_DELTA"] = old

    def test_as_dict_has_metrics_columns(self):
        v = evaluate_affinity_change(current=50, proposed_delta=5, sentiment="positive")
        d = v.as_dict()
        for key in ("affinity_current", "affinity_proposed_delta", "affinity_applied_delta",
                    "affinity_rule_status", "affinity_rule_notes"):
            self.assertIn(key, d)


if __name__ == "__main__":
    unittest.main(verbosity=2)
