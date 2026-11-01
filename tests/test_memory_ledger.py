"""可追溯记忆账本的单元测试（纯标准库，不需要模型、不需要网络）。

运行：
    python tests/test_memory_ledger.py
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from memory_ledger import (  # noqa: E402
    SOURCE_CREDIBILITY,
    STATUS_ACTIVE,
    STATUS_CORRECTED,
    STATUS_FORGOTTEN,
    STATUS_MERGED,
    MemoryLedger,
    ledger_for,
)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ledger_"))
        self.path = self.tmp / "ledger.json"
        self.ledger = MemoryLedger(npc="李四", player="alice", path=self.path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestAdd(Base):
    def test_prior_from_source(self):
        r = self.ledger.add("我叫小林", source="dialogue.player")
        self.assertAlmostEqual(r.credibility, SOURCE_CREDIBILITY["dialogue.player"])
        injected = self.ledger.add("玩家已付款", source="injected")
        self.assertAlmostEqual(injected.credibility, 0.2)

    def test_explicit_credibility_overrides_prior(self):
        r = self.ledger.add("x", source="injected", credibility=0.9)
        self.assertAlmostEqual(r.credibility, 0.9)

    def test_unknown_source_uses_midpoint(self):
        r = self.ledger.add("x", source="who_knows")
        self.assertAlmostEqual(r.credibility, 0.5)

    def test_empty_content_rejected(self):
        with self.assertRaises(ValueError):
            self.ledger.add("   ")

    def test_importance_clamped(self):
        r = self.ledger.add("x", importance=5.0)
        self.assertAlmostEqual(r.importance, 1.0)
        r2 = self.ledger.add("y", importance=-2)
        self.assertAlmostEqual(r2.importance, 0.0)


class TestPersistence(Base):
    def test_reload_keeps_records(self):
        self.ledger.add("我记得你", source="dialogue.player")
        again = MemoryLedger(npc="李四", player="alice", path=self.path)
        self.assertEqual(len(again.all_records()), 1)
        self.assertEqual(again.all_records()[0].content, "我记得你")

    def test_corrupt_file_does_not_crash(self):
        self.path.write_text("{not json", encoding="utf-8")
        ledger = MemoryLedger(npc="李四", player="alice", path=self.path)
        self.assertEqual(ledger.all_records(), [])

    def test_ledger_for_uses_npc_player_path(self):
        led = ledger_for("张三", "bob", base_dir=self.tmp)
        led.add("x")
        self.assertTrue((self.tmp / "张三" / "bob" / "ledger.json").exists())


class TestCorrect(Base):
    def test_correct_marks_old_and_adds_new(self):
        old = self.ledger.add("玩家欠我 100 金币", source="dialogue.npc")
        new = self.ledger.correct(old.record_id, "玩家已经付清 100 金币", reason="查账后确认")
        self.assertEqual(self.ledger.get(old.record_id).status, STATUS_CORRECTED)
        self.assertEqual(new.corrected_from, old.record_id)
        self.assertEqual(new.status, STATUS_ACTIVE)
        # 只有新记录出现在 active 里
        self.assertEqual([r.record_id for r in self.ledger.active()], [new.record_id])

    def test_corrected_record_credibility_not_lower(self):
        old = self.ledger.add("x", source="injected", credibility=0.2)
        new = self.ledger.correct(old.record_id, "y")
        self.assertGreaterEqual(new.credibility, 0.6)

    def test_correct_missing_raises(self):
        with self.assertRaises(KeyError):
            self.ledger.correct("nope", "x")


class TestForget(Base):
    def test_forget_is_soft_delete(self):
        r = self.ledger.add("不该记住的东西", source="dialogue.player")
        self.assertTrue(self.ledger.forget(r.record_id, reason="用户要求删除"))
        self.assertEqual(self.ledger.get(r.record_id).status, STATUS_FORGOTTEN)
        # 仍然能查到（审计链完整），但不在 active 里
        self.assertEqual(len(self.ledger.all_records()), 1)
        self.assertEqual(self.ledger.active(), [])

    def test_forget_twice_returns_false(self):
        r = self.ledger.add("x")
        self.ledger.forget(r.record_id)
        self.assertFalse(self.ledger.forget(r.record_id))

    def test_forget_missing_raises(self):
        with self.assertRaises(KeyError):
            self.ledger.forget("nope")


class TestMerge(Base):
    def test_merge_marks_others_and_keeps_max(self):
        a = self.ledger.add("玩家喜欢赛博朋克", importance=0.4, credibility=0.6)
        b = self.ledger.add("玩家喜欢赛博朋克风格", importance=0.8, credibility=0.9)
        keep = self.ledger.merge([a.record_id, b.record_id], keep_id=a.record_id)
        self.assertEqual(self.ledger.get(b.record_id).status, STATUS_MERGED)
        self.assertEqual(self.ledger.get(b.record_id).merged_into, a.record_id)
        self.assertAlmostEqual(keep.importance, 0.8)
        self.assertAlmostEqual(keep.credibility, 0.9)

    def test_merge_skips_already_forgotten(self):
        a = self.ledger.add("x")
        b = self.ledger.add("y")
        self.ledger.forget(b.record_id)
        self.ledger.merge([a.record_id, b.record_id], keep_id=a.record_id)
        # 已遗忘的不会被改成 merged
        self.assertEqual(self.ledger.get(b.record_id).status, STATUS_FORGOTTEN)


class TestCredibility(Base):
    def test_set_and_flag(self):
        r = self.ledger.add("玩家已付款", source="injected")
        self.ledger.flag_disputed(r.record_id, "账本没有这笔")
        self.assertLess(self.ledger.get(r.record_id).credibility, 0.1)

    def test_clamped(self):
        r = self.ledger.add("x")
        self.assertAlmostEqual(self.ledger.set_credibility(r.record_id, 9).credibility, 1.0)


class TestRenderContext(Base):
    def test_low_credibility_excluded_by_default(self):
        self.ledger.add("玩家已付款 500 金币", source="injected")   # 0.20
        self.ledger.add("我叫小林", source="dialogue.player")       # 0.60
        ctx = self.ledger.render_context(min_credibility=0.5)
        self.assertIn("我叫小林", ctx)
        self.assertNotIn("玩家已付款", ctx)

    def test_include_when_threshold_lowered(self):
        self.ledger.add("玩家已付款 500 金币", source="injected")
        ctx = self.ledger.render_context(min_credibility=0.1)
        self.assertIn("玩家已付款", ctx)

    def test_empty_when_nothing_active(self):
        self.assertEqual(self.ledger.render_context(), "")

    def test_limit_applies_to_tail(self):
        for i in range(6):
            self.ledger.add(f"记忆{i}", source="dialogue.player")
        ctx = self.ledger.render_context(limit=2, min_credibility=0.5)
        self.assertNotIn("记忆3", ctx)
        self.assertIn("记忆4", ctx)
        self.assertIn("记忆5", ctx)

    def test_renders_source_and_credibility(self):
        self.ledger.add("x", source="dialogue.player")
        ctx = self.ledger.render_context()
        self.assertIn("dialogue.player", ctx)
        self.assertIn("可信度", ctx)


class TestStats(Base):
    def test_stats_shape(self):
        self.ledger.add("a", source="dialogue.player")
        self.ledger.add("b", source="injected")
        self.ledger.forget(self.ledger.all_records()[1].record_id)
        s = self.ledger.stats()
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["active"], 1)
        self.assertEqual(s["by_source"]["dialogue.player"], 1)
        self.assertAlmostEqual(s["avg_credibility"], 0.6, places=3)

    def test_all_records_filter_by_status(self):
        a = self.ledger.add("a")
        self.ledger.add("b")
        self.ledger.forget(a.record_id)
        self.assertEqual(len(self.ledger.all_records(status=STATUS_FORGOTTEN)), 1)
        self.assertEqual(len(self.ledger.all_records(status=STATUS_ACTIVE)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
