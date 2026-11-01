"""加固项的单元测试：关系持久化恢复、位置校验（R3/R4）、对话关系提议。

运行：
    python tests/test_hardening.py
"""

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from relations import (  # noqa: E402
    TYPE_CONFLICT,
    TYPE_NEUTRAL,
    TYPE_RIVAL,
    RelationGraph,
    extract_relation_proposal,
)
from world_state import WorldState, build_demo_state  # noqa: E402

NPCS = ["张三", "李四", "王五"]


# ---------------------------------------------------------------- 关系恢复
class TestRelationRestore(unittest.TestCase):
    def setUp(self):
        self.g = RelationGraph(NPCS)

    def test_restore_sets_strength_and_type(self):
        n = self.g.restore([{"a": "张三", "b": "王五", "strength": -0.8, "type": "conflict"}])
        self.assertEqual(n, 1)
        rel = self.g.get("张三", "王五")
        self.assertAlmostEqual(rel.strength, -0.8)
        self.assertEqual(rel.type, TYPE_CONFLICT)       # 类型从强度重算，不信库里的字段
        self.assertEqual(rel.evidence[-1]["kind"], "restore")

    def test_restore_clamps(self):
        self.g.restore([{"a": "张三", "b": "李四", "strength": -9}])
        self.assertAlmostEqual(self.g.get("张三", "李四").strength, -1.0)

    def test_restore_skips_unknown_pair(self):
        n = self.g.restore([{"a": "张三", "b": "赵六", "strength": 0.5}])
        self.assertEqual(n, 0)

    def test_restore_skips_same_entity(self):
        self.assertEqual(self.g.restore([{"a": "张三", "b": "张三", "strength": 0.5}]), 0)

    def test_restore_ignores_bad_strength(self):
        self.assertEqual(self.g.restore([{"a": "张三", "b": "李四", "strength": "abc"}]), 0)

    def test_restore_accepts_from_to_keys(self):
        # Neo4j 读回用的字段名是 a/b；也兼容 from/to
        self.assertEqual(self.g.restore([{"from": "李四", "to": "王五", "strength": 0.4}]), 1)

    def test_restore_then_event_continues(self):
        self.g.restore([{"a": "张三", "b": "王五", "strength": -0.4}])
        self.g.apply_event("help", ["张三", "王五"])
        self.assertAlmostEqual(self.g.get("张三", "王五").strength, -0.1)
        self.assertEqual(self.g.get("张三", "王五").type, TYPE_NEUTRAL)


# ---------------------------------------------------------------- 关系提议
class TestRelationProposal(unittest.TestCase):
    def test_extracts_and_strips(self):
        text = '我帮他一把。<<RELATION {"kind": "help", "with": "王五"}>>'
        clean, payload = extract_relation_proposal(text)
        self.assertNotIn("RELATION", clean)
        self.assertEqual(clean, "我帮他一把。")
        self.assertEqual(payload, {"kind": "help", "with": "王五"})

    def test_no_marker(self):
        clean, payload = extract_relation_proposal("今天天气不错")
        self.assertIsNone(payload)
        self.assertEqual(clean, "今天天气不错")

    def test_unknown_kind_rejected_but_marker_stripped(self):
        clean, payload = extract_relation_proposal('<<RELATION {"kind": "mind_control", "with": "王五"}>>')
        self.assertIsNone(payload)
        self.assertNotIn("RELATION", clean)

    def test_missing_with_rejected(self):
        _, payload = extract_relation_proposal('<<RELATION {"kind": "help"}>>')
        self.assertIsNone(payload)

    def test_bad_json_does_not_leak_marker(self):
        clean, payload = extract_relation_proposal('好的 <<RELATION {"kind": help')
        self.assertIsNone(payload)
        self.assertNotIn("RELATION", clean)

    def test_all_whitelisted_kinds_accepted(self):
        for kind in ("help", "cooperate", "praise", "compete", "conflict", "betray"):
            _, payload = extract_relation_proposal(
                '<<RELATION {"kind": "%s", "with": "李四"}>>' % kind)
            self.assertIsNotNone(payload, kind)


# ---------------------------------------------------------------- 位置加固
def make_state(**kwargs):
    defaults = dict(
        positions={},
        map_size=(15, 10),
        max_step=5.0,
        spawns={"player": [1, 8]},
        spawn_radius=3.0,
        min_report_interval=0.0,
    )
    defaults.update(kwargs)
    return WorldState(**defaults)


class TestFirstReport(unittest.TestCase):
    def test_far_first_report_rejected(self):
        s = make_state()
        verdict = s.report_position("player", 12, 2)
        self.assertFalse(verdict["accepted"])
        self.assertIn("R4", verdict["message"])
        self.assertIsNone(s.position_of("player"))

    def test_near_spawn_accepted(self):
        s = make_state()
        self.assertTrue(s.report_position("player", 2, 8)["accepted"])

    def test_no_spawn_configured_means_no_r4(self):
        s = make_state(spawns={})
        self.assertTrue(s.report_position("player", 12, 2)["accepted"])


class TestRateLimit(unittest.TestCase):
    def test_two_immediate_reports_second_rejected(self):
        s = make_state(min_report_interval=0.2)
        self.assertTrue(s.report_position("player", 2, 8)["accepted"])
        second = s.report_position("player", 2.5, 8)
        self.assertFalse(second["accepted"])
        self.assertIn("R3", second["message"])

    def test_after_interval_accepted(self):
        s = make_state(min_report_interval=0.02)
        s.report_position("player", 2, 8)
        time.sleep(0.05)
        self.assertTrue(s.report_position("player", 2.5, 8)["accepted"])

    def test_rejection_is_audited(self):
        s = make_state(min_report_interval=5.0)
        s.report_position("player", 2, 8)
        s.report_position("player", 3, 8)
        moves = [e for e in s.events() if e["action"] == "move"]
        self.assertEqual(len(moves), 2)
        self.assertTrue(moves[-1]["detail"]["accepted"] is False)


class TestDemoWorldSpawn(unittest.TestCase):
    def test_player_first_report_uses_config_spawn(self):
        s = build_demo_state()
        self.assertFalse(s.report_position("player", 12, 2)["accepted"])
        self.assertTrue(s.report_position("player", 2, 8)["accepted"])

    def test_npc_spawn_is_its_position(self):
        s = build_demo_state()
        # 张三初始在 (3,4)，出生点也就是它；跳到远处应被 R4 拦
        self.assertFalse(s.report_position("张三", 12, 2)["accepted"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
