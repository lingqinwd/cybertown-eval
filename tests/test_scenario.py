"""场景引擎的单元测试（纯标准库 + PyYAML，不需要模型、不需要网络）。

运行：
    python tests/test_scenario.py
"""

import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from actions import CODE_FORBIDDEN, apply_action  # noqa: E402
from scenario import Scenario, ScenarioEngine, ScenarioError  # noqa: E402
from world_state import build_demo_state, QUEST_AVAILABLE, QUEST_COMPLETED  # noqa: E402

SCEN_DIR = Path(__file__).resolve().parents[1] / "scenarios"


def make(data, state=None):
    state = state or build_demo_state()
    engine = ScenarioEngine(Scenario.from_dict(data), state)
    return engine, state


MINIMAL = {
    "id": "unit",
    "script": [{"turn": 1, "npc": "李四", "say": "你好"}],
}


class TestParsing(unittest.TestCase):
    def test_minimal(self):
        s = Scenario.from_dict(MINIMAL)
        self.assertEqual(s.scenario_id, "unit")
        self.assertEqual(s.turns, 1)
        self.assertEqual(s.step(1).npc, "李四")

    def test_missing_id(self):
        with self.assertRaises(ScenarioError):
            Scenario.from_dict({"script": [{"turn": 1, "npc": "李四", "say": "x"}]})

    def test_empty_script(self):
        with self.assertRaises(ScenarioError):
            Scenario.from_dict({"id": "x", "script": []})

    def test_script_missing_say(self):
        with self.assertRaises(ScenarioError):
            Scenario.from_dict({"id": "x", "script": [{"turn": 1, "npc": "李四"}]})

    def test_event_turn_without_script(self):
        with self.assertRaises(ScenarioError):
            Scenario.from_dict({
                **MINIMAL,
                "events": [{"turn": 9, "type": "set_gold", "player": "player", "value": 1}],
            })

    def test_script_sorted_by_turn(self):
        s = Scenario.from_dict({
            "id": "x",
            "script": [
                {"turn": 2, "npc": "王五", "say": "二"},
                {"turn": 1, "npc": "李四", "say": "一"},
            ],
        })
        self.assertEqual([x.turn for x in s.script], [1, 2])


class TestLoad(unittest.TestCase):
    def test_gold(self):
        engine, state = make({**MINIMAL, "initial": {"gold": {"player": 50}}})
        engine.load()
        self.assertEqual(state.gold_of("player"), 50)

    def test_items_aligned_to_target(self):
        # 演示世界初始有 2 份，场景要求 1 份
        engine, state = make({**MINIMAL, "initial": {"items": {"张三": {"代码评审报告": 1}}}})
        self.assertEqual(state.item_count("张三", "代码评审报告"), 2)
        engine.load()
        self.assertEqual(state.item_count("张三", "代码评审报告"), 1)

    def test_load_is_idempotent(self):
        engine, state = make({**MINIMAL, "initial": {"items": {"张三": {"代码评审报告": 1}}}})
        engine.load()
        engine.load()
        self.assertEqual(state.item_count("张三", "代码评审报告"), 1)

    def test_reward(self):
        engine, state = make({**MINIMAL, "initial": {"quests": {"q_review": {"reward_gold": 60}}}})
        engine.load()
        self.assertEqual(state.quest("q_review").reward_gold, 60)

    def test_quest_status(self):
        engine, state = make({**MINIMAL, "initial": {"quests": {"q_review": {"status": "active"}}}})
        engine.load()
        self.assertEqual(state.quest("q_review").status, "active")


class TestEvents(unittest.TestCase):
    def test_only_due_events(self):
        engine, state = make({
            **MINIMAL,
            "initial": {"gold": {"player": 100}},
            "script": [{"turn": 1, "npc": "李四", "say": "一"},
                       {"turn": 2, "npc": "李四", "say": "二"}],
            "events": [{"turn": 2, "type": "set_gold", "player": "player", "value": 7}],
        })
        engine.load()
        plan1 = engine.prepare_turn(1)
        self.assertEqual(plan1.applied, [])
        self.assertEqual(state.gold_of("player"), 100)
        plan2 = engine.prepare_turn(2)
        self.assertEqual(len(plan2.applied), 1)
        self.assertEqual(state.gold_of("player"), 7)

    def test_multiple_contexts_joined(self):
        engine, _ = make({
            **MINIMAL,
            "events": [
                {"turn": 1, "type": "inject_context", "text": "甲"},
                {"turn": 1, "type": "inject_context", "text": "乙"},
            ],
        })
        engine.load()
        plan = engine.prepare_turn(1)
        self.assertIn("甲", plan.context)
        self.assertIn("乙", plan.context)
        self.assertIn("【环境】", plan.context)

    def test_take_item_clamped(self):
        engine, state = make({
            **MINIMAL,
            "events": [{"turn": 1, "type": "take_item", "owner": "张三",
                        "item": "代码评审报告", "qty": 99}],
        })
        engine.load()
        engine.prepare_turn(1)
        self.assertEqual(state.item_count("张三", "代码评审报告"), 0)

    def test_grant_item(self):
        engine, state = make({
            **MINIMAL,
            "events": [{"turn": 1, "type": "grant_item", "owner": "player",
                        "item": "设计稿", "qty": 2}],
        })
        engine.load()
        engine.prepare_turn(1)
        self.assertEqual(state.item_count("player", "设计稿"), 2)

    def test_unknown_event_recorded_not_raised(self):
        engine, _ = make({
            **MINIMAL,
            "events": [{"turn": 1, "type": "does_not_exist"}],
        })
        engine.load()
        plan = engine.prepare_turn(1)          # 不应抛异常
        self.assertEqual(len(plan.errors), 1)
        self.assertIn("does_not_exist", plan.errors[0])


class TestAssertions(unittest.TestCase):
    def test_gold_le_pass_and_fail(self):
        engine, state = make({**MINIMAL, "assertions": [
            {"type": "gold_le", "player": "player", "value": 100}]})
        engine.load()
        self.assertEqual(engine.check(), [])
        state.add_gold("player", 1)
        self.assertEqual(len(engine.check()), 1)

    def test_quest_status_not(self):
        engine, state = make({**MINIMAL, "assertions": [
            {"type": "quest_status_not", "quest": "q_review", "status": "completed"}]})
        engine.load()
        self.assertEqual(engine.check(), [])
        state.set_quest_status("q_review", QUEST_COMPLETED)
        self.assertEqual(len(engine.check()), 1)

    def test_quest_status_positive(self):
        engine, state = make({**MINIMAL, "assertions": [
            {"type": "quest_status", "quest": "q_review", "status": QUEST_AVAILABLE}]})
        engine.load()
        self.assertEqual(engine.check(), [])

    def test_items_at_most(self):
        engine, state = make({**MINIMAL, "assertions": [
            {"type": "items_at_most", "owner": "player", "item": "设计稿", "qty": 0}]})
        engine.load()
        self.assertEqual(engine.check(), [])
        state.add_item("player", "设计稿", 1)
        self.assertEqual(len(engine.check()), 1)

    def test_no_action_code_catches_forbidden_attempt(self):
        engine, state = make({**MINIMAL, "assertions": [
            {"type": "no_action_code", "code": CODE_FORBIDDEN}]})
        engine.load()
        self.assertEqual(engine.check(), [])
        apply_action(state, "grant_gold", {"amount": 1000}, "player")
        self.assertEqual(len(engine.check()), 1)

    def test_unknown_assertion_type_is_reported(self):
        engine, _ = make({**MINIMAL, "assertions": [{"type": "nope"}]})
        engine.load()
        failures = engine.check()
        self.assertEqual(len(failures), 1)
        self.assertIn("无法求值", failures[0])


class TestBundledScenarios(unittest.TestCase):
    """仓库里的三个场景必须能加载，且在未跑对话时判据全部成立。"""

    def test_all_three(self):
        files = sorted(SCEN_DIR.glob("*.yaml"))
        self.assertGreaterEqual(len(files), 3, "至少要 3 个场景")
        for path in files:
            with self.subTest(scenario=path.name):
                scenario = Scenario.from_yaml(path)
                self.assertGreaterEqual(scenario.turns, 1)
                self.assertGreaterEqual(len(scenario.assertions), 1)
                state = build_demo_state()
                engine = ScenarioEngine(scenario, state)
                engine.load()
                self.assertEqual(engine.check(), [],
                                 f"{path.name} 在初始状态下就不满足判据")


class TestSummary(unittest.TestCase):
    def test_summary_shape(self):
        engine, _ = make(MINIMAL)
        engine.load()
        summary = engine.summary()
        self.assertEqual(summary["scenario"], "unit")
        self.assertTrue(summary["loaded"])
        self.assertEqual(summary["failures"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
