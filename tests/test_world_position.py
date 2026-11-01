"""位置与关卡配置的单元测试（纯标准库，不需要模型、不需要网络）。

运行：
    python tests/test_world_position.py
"""

import json
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from world_state import (  # noqa: E402
    DEFAULT_MAX_STEP,
    FALLBACK_WORLD,
    WorldState,
    build_demo_state,
    load_world_config,
)


class TestConfig(unittest.TestCase):
    def test_loads_repo_config(self):
        cfg = load_world_config()
        self.assertEqual(cfg["town"], "晨雾镇")
        self.assertIn("q_review", cfg["quests"])
        self.assertEqual(cfg["map_size"], [15, 10])

    def test_missing_file_falls_back(self):
        cfg = load_world_config(Path("definitely_not_here.json"))
        self.assertEqual(cfg["town"], FALLBACK_WORLD["town"])

    def test_bad_json_falls_back(self):
        tmp = Path(tempfile.mkdtemp(prefix="world_"))
        try:
            bad = tmp / "world.json"
            bad.write_text("{not json", encoding="utf-8")
            cfg = load_world_config(bad)
            self.assertEqual(cfg["town"], FALLBACK_WORLD["town"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_config_without_quests_falls_back(self):
        tmp = Path(tempfile.mkdtemp(prefix="world_"))
        try:
            p = tmp / "world.json"
            p.write_text(json.dumps({"town": "空镇"}), encoding="utf-8")
            cfg = load_world_config(p)
            self.assertEqual(cfg["town"], FALLBACK_WORLD["town"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.state = build_demo_state()

    def move(self, entity, x, y):
        return self.state.report_position(entity, x, y)


class TestQuestData(Base):
    def test_quests_come_from_config(self):
        quests = {q["quest_id"]: q for q in self.state.list_quests()}
        self.assertEqual(quests["q_review"]["reward_gold"], 30.0)
        self.assertEqual(quests["q_design"]["required_items"], {"设计稿": 1})

    def test_items_come_from_config(self):
        self.assertEqual(self.state.item_count("张三", "代码评审报告"), 2)
        self.assertEqual(self.state.item_count("王五", "设计稿"), 2)


class TestPositions(Base):
    def test_initial_positions(self):
        self.assertEqual(self.state.position_of("张三"), [3.0, 4.0])
        self.assertEqual(len(self.state.positions()), 3)

    def test_unknown_entity(self):
        self.assertIsNone(self.state.position_of("赵六"))

    def test_small_move_accepted(self):
        verdict = self.move("张三", 4, 4)
        self.assertTrue(verdict["accepted"])
        self.assertEqual(self.state.position_of("张三"), [4.0, 4.0])

    def test_teleport_rejected(self):
        verdict = self.move("张三", 14, 9)          # 距离 ~11.2 > max_step
        self.assertFalse(verdict["accepted"])
        self.assertIn("R2", verdict["message"])
        self.assertEqual(self.state.position_of("张三"), [3.0, 4.0])   # 位置未变

    def test_out_of_bounds_rejected(self):
        verdict = self.move("张三", 99, 99)
        self.assertFalse(verdict["accepted"])
        self.assertIn("R1", verdict["message"])

    def test_nan_rejected(self):
        verdict = self.move("张三", float("nan"), 4)
        self.assertFalse(verdict["accepted"])
        self.assertIn("R0", verdict["message"])

    def test_non_numeric_rejected(self):
        verdict = self.move("张三", "一二", 4)
        self.assertFalse(verdict["accepted"])
        self.assertIn("R0", verdict["message"])

    def test_first_report_of_new_entity(self):
        verdict = self.move("赵六", 5, 5)           # 没有历史位置，只校验边界
        self.assertTrue(verdict["accepted"])
        self.assertEqual(self.state.position_of("赵六"), [5.0, 5.0])

    def test_rejections_are_audited(self):
        self.move("张三", 99, 99)
        self.move("张三", 14, 9)
        moves = [e for e in self.state.events() if e["action"] == "move"]
        self.assertEqual(len(moves), 2)
        self.assertTrue(all(e["detail"]["accepted"] is False for e in moves))

    def test_accepted_move_is_audited(self):
        self.move("张三", 4, 4)
        moves = [e for e in self.state.events() if e["action"] == "move"]
        self.assertEqual(len(moves), 1)
        self.assertTrue(moves[0]["detail"]["accepted"])

    def test_set_position_bypasses_validation(self):
        # 世界初始化 / 场景事件 / 测试需要直接设定
        self.state.set_position("张三", 12, 8)
        self.assertEqual(self.state.position_of("张三"), [12.0, 8.0])

    def test_snapshot_includes_positions_and_map(self):
        snap = self.state.snapshot()
        self.assertIn("positions", snap)
        self.assertEqual(snap["map_size"], [15.0, 10.0])
        self.assertEqual(snap["positions"]["李四"], [7.0, 4.0])

    def test_custom_max_step(self):
        state = WorldState(positions={"A": [0, 0]}, map_size=(10, 10), max_step=1.0)
        self.assertFalse(state.report_position("A", 3, 0)["accepted"])
        self.assertTrue(state.report_position("A", 0.5, 0)["accepted"])

    def test_default_max_step_exposed(self):
        self.assertGreater(DEFAULT_MAX_STEP, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
