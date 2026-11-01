"""权威世界状态与动作白名单的单元测试（纯标准库，不需要模型/网络/GPU）。

运行：
    python tests/test_world_state.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from actions import (  # noqa: E402
    CODE_FORBIDDEN,
    CODE_INVALID,
    CODE_OK,
    CODE_PRECONDITION,
    CODE_UNKNOWN,
    MAX_ITEM_TRANSFER,
    apply_action,
)
from world_state import (  # noqa: E402
    QUEST_ACTIVE,
    QUEST_COMPLETED,
    build_demo_state,
)


class Base(unittest.TestCase):
    def setUp(self):
        self.state = build_demo_state()
        self.state.ensure_player("alice")   # 基线 100 金币，便于断言增量

    def act(self, action, **args):
        return apply_action(self.state, action, args, actor="alice")


class TestPlayerInit(Base):
    def test_new_player_gets_start_gold(self):
        self.state.ensure_player("alice")
        self.assertEqual(self.state.gold_of("alice"), 100.0)

    def test_snapshot_is_a_copy(self):
        snap = self.state.snapshot("alice")
        snap["gold"] = 999999
        snap["items"]["x"] = 1
        self.assertEqual(self.state.gold_of("alice"), 100.0)
        self.assertEqual(self.state.items_of("alice"), {})


class TestQuestFlow(Base):
    def test_accept_quest(self):
        v = self.act("accept_quest", quest_id="q_review")
        self.assertTrue(v.accepted, v.message)
        self.assertEqual(v.code, CODE_OK)
        self.assertEqual(self.state.quest("q_review").status, QUEST_ACTIVE)

    def test_accept_twice_rejected(self):
        self.act("accept_quest", quest_id="q_review")
        v = self.act("accept_quest", quest_id="q_review")
        self.assertFalse(v.accepted)
        self.assertEqual(v.code, CODE_PRECONDITION)

    def test_complete_without_accepting_rejected(self):
        v = self.act("complete_quest", quest_id="q_review")
        self.assertFalse(v.accepted)
        self.assertEqual(v.code, CODE_PRECONDITION)

    def test_complete_without_items_rejected(self):
        self.act("accept_quest", quest_id="q_review")
        v = self.act("complete_quest", quest_id="q_review")
        self.assertFalse(v.accepted)
        self.assertEqual(v.code, CODE_PRECONDITION)
        self.assertIn("代码评审报告", v.message)

    def test_full_flow_grants_reward(self):
        # 1) 从张三处拿到所需物品
        v1 = self.act("transfer_item", from_npc="张三", item="代码评审报告", qty=1)
        self.assertTrue(v1.accepted, v1.message)
        # 2) 接任务
        self.assertTrue(self.act("accept_quest", quest_id="q_review").accepted)
        # 3) 交付
        v3 = self.act("complete_quest", quest_id="q_review")
        self.assertTrue(v3.accepted, v3.message)

        self.assertEqual(self.state.quest("q_review").status, QUEST_COMPLETED)
        self.assertEqual(self.state.gold_of("alice"), 130.0)          # 100 + 30
        self.assertEqual(self.state.items_of("alice"), {})            # 物品被消耗
        self.assertTrue(any("gold:+30" in e for e in v3.effects))


class TestForbidden(Base):
    def test_grant_gold_is_forbidden(self):
        """最典型的越权：直接要钱。必须返回 forbidden 而不是静默忽略。"""
        v = self.act("grant_gold", amount=1000)
        self.assertFalse(v.accepted)
        self.assertEqual(v.code, CODE_FORBIDDEN)
        self.assertEqual(self.state.gold_of("alice"), 100.0)

    def test_set_affinity_is_forbidden(self):
        v = self.act("set_affinity", npc="李四", value=100)
        self.assertFalse(v.accepted)
        self.assertEqual(v.code, CODE_FORBIDDEN)

    def test_unknown_action(self):
        v = self.act("teleport_to_boss")
        self.assertFalse(v.accepted)
        self.assertEqual(v.code, CODE_UNKNOWN)


class TestItemValidation(Base):
    def test_zero_and_negative_qty(self):
        for qty in (0, -3):
            v = self.act("transfer_item", from_npc="张三", item="代码评审报告", qty=qty)
            self.assertFalse(v.accepted, f"qty={qty} 应被拒绝")
            self.assertEqual(v.code, CODE_INVALID)

    def test_over_cap(self):
        v = self.act("transfer_item", from_npc="张三", item="代码评审报告", qty=MAX_ITEM_TRANSFER + 1)
        self.assertFalse(v.accepted)
        self.assertEqual(v.code, CODE_FORBIDDEN)

    def test_beyond_holdings(self):
        v = self.act("transfer_item", from_npc="张三", item="设计稿", qty=1)
        self.assertFalse(v.accepted)
        self.assertEqual(v.code, CODE_PRECONDITION)

    def test_non_integer_qty(self):
        v = self.act("transfer_item", from_npc="张三", item="代码评审报告", qty="两个")
        self.assertFalse(v.accepted)
        self.assertEqual(v.code, CODE_INVALID)


class TestAuditTrail(Base):
    def test_every_attempt_is_recorded(self):
        self.act("grant_gold", amount=1000)                       # 拒绝
        self.act("accept_quest", quest_id="q_review")             # 受理
        events = self.state.recent_events(10)
        self.assertEqual(len(events), 2)
        self.assertFalse(events[0]["detail"]["accepted"])
        self.assertTrue(events[1]["detail"]["accepted"])
        self.assertEqual(events[0]["actor"], "alice")

    def test_version_increments(self):
        v0 = self.state.version
        self.act("grant_gold", amount=1)
        self.act("grant_gold", amount=1)
        self.assertEqual(self.state.version, v0 + 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
