"""NPC 关系图的单元测试（纯标准库，不需要 Neo4j、不需要模型）。

运行：
    python tests/test_relations.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from relations import (  # noqa: E402
    EVENT_RULES,
    TYPE_CONFLICT,
    TYPE_COOP,
    TYPE_FRIEND,
    TYPE_NEUTRAL,
    TYPE_RIVAL,
    RelationGraph,
    type_of,
)

NPCS = ["张三", "李四", "王五"]


class Base(unittest.TestCase):
    def setUp(self):
        self.g = RelationGraph(NPCS)


class TestStructure(Base):
    def test_edge_count(self):
        # 3 个 NPC 的无向完全图 = 3 条边
        self.assertEqual(len(self.g.all()), 3)

    def test_edge_symmetric_lookup(self):
        r1 = self.g.get("张三", "李四")
        r2 = self.g.get("李四", "张三")
        self.assertIs(r1, r2)

    def test_same_npc_rejected(self):
        with self.assertRaises(ValueError):
            self.g.get("张三", "张三")

    def test_unknown_pair(self):
        with self.assertRaises(KeyError):
            self.g.get("张三", "赵六")

    def test_initial_all_neutral(self):
        for edge in self.g.all():
            self.assertEqual(edge["type"], TYPE_NEUTRAL)
            self.assertAlmostEqual(edge["strength"], 0.0)


class TestEventDriven(Base):
    def test_help_increases_strength(self):
        changed = self.g.apply_event("help", ["张三", "李四"], note="帮王五交了报告")
        self.assertEqual(len(changed), 1)
        self.assertAlmostEqual(self.g.get("张三", "李四").strength, EVENT_RULES["help"])

    def test_three_actors_touch_three_edges(self):
        changed = self.g.apply_event("compete", ["张三", "李四", "王五"])
        self.assertEqual(len(changed), 3)   # C(3,2)

    def test_type_moves_with_strength(self):
        self.g.apply_event("help", ["张三", "李四"])
        rel = self.g.get("张三", "李四")
        self.assertEqual(rel.type, TYPE_COOP)          # 0.30 → coop
        self.g.apply_event("help", ["张三", "李四"])
        self.assertEqual(rel.type, TYPE_FRIEND)        # 0.60 → friend

    def test_negative_side(self):
        self.g.apply_event("conflict", ["李四", "王五"])
        self.assertEqual(self.g.get("李四", "王五").type, TYPE_RIVAL)   # -0.40
        self.g.apply_event("conflict", ["李四", "王五"])
        self.assertEqual(self.g.get("李四", "王五").type, TYPE_CONFLICT)  # -0.80

    def test_float_accumulation_keeps_boundary(self):
        """-0.2 必须判成 rival，不能因为浮点误差退回 neutral。"""
        self.g.apply_event("compete", ["张三", "王五"])    # -0.3
        self.g.apply_event("conflict", ["张三", "王五"])   # -0.7
        self.g.apply_event("help", ["张三", "王五"])       # -0.4
        self.g.apply_event("cooperate", ["张三", "王五"])  # -0.2
        rel = self.g.get("张三", "王五")
        self.assertAlmostEqual(rel.strength, -0.2, places=3)
        self.assertEqual(rel.type, TYPE_RIVAL)

    def test_strength_clamped(self):
        for _ in range(10):
            self.g.apply_event("help", ["张三", "李四"])
        self.assertAlmostEqual(self.g.get("张三", "李四").strength, 1.0)
        for _ in range(20):
            self.g.apply_event("betray", ["张三", "李四"])
        self.assertAlmostEqual(self.g.get("张三", "李四").strength, -1.0)

    def test_unknown_event_raises(self):
        with self.assertRaises(KeyError):
            self.g.apply_event("telepathy", ["张三", "李四"])

    def test_custom_weight_allows_unknown_kind(self):
        self.g.apply_event("telepathy", ["张三", "李四"], weight=0.25)
        self.assertAlmostEqual(self.g.get("张三", "李四").strength, 0.25)

    def test_need_two_known_npcs(self):
        with self.assertRaises(ValueError):
            self.g.apply_event("help", ["张三"])
        with self.assertRaises(ValueError):
            self.g.apply_event("help", ["张三", "赵六"])

    def test_unknown_actor_filtered_out(self):
        # 赵六不在图里，只剩一个已知 NPC → 应报错而不是静默成功
        with self.assertRaises(ValueError):
            self.g.apply_event("help", ["张三", "赵六"])


class TestEvidence(Base):
    def test_evidence_appended(self):
        self.g.apply_event("cooperate", ["张三", "王五"], note="一起做完任务")
        rel = self.g.get("张三", "王五")
        self.assertEqual(len(rel.evidence), 1)
        self.assertEqual(rel.evidence[0]["kind"], "cooperate")
        self.assertAlmostEqual(rel.evidence[0]["delta"], 0.2)
        self.assertEqual(rel.evidence[0]["note"], "一起做完任务")

    def test_evidence_capped(self):
        from relations import EVIDENCE_LIMIT

        for i in range(EVIDENCE_LIMIT + 5):
            self.g.apply_event("praise", ["张三", "李四"], note=f"第{i}次")
        self.assertLessEqual(len(self.g.get("张三", "李四").evidence), EVIDENCE_LIMIT)

    def test_evidence_hidden_when_not_requested(self):
        self.g.apply_event("praise", ["张三", "李四"])
        edges = self.g.all(include_evidence=False)
        self.assertNotIn("evidence", edges[0])
        self.assertIn("evidence_count", edges[0])


class TestPayloadAndStats(Base):
    def test_graph_payload_shape(self):
        self.g.apply_event("help", ["张三", "李四"])
        payload = self.g.to_graph_payload()
        self.assertEqual(len(payload["nodes"]), 3)
        self.assertEqual(len(payload["edges"]), 3)
        self.assertEqual(payload["nodes"][0]["label"], "张三")

    def test_stats(self):
        self.g.apply_event("conflict", ["李四", "王五"])
        stats = self.g.stats()
        self.assertEqual(stats["npcs"], 3)
        self.assertEqual(stats["edges"], 3)
        self.assertEqual(stats["events"], 1)
        self.assertEqual(stats["strongest"]["pair"], ["李四", "王五"])


class TestTypeThresholds(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(type_of(1.0), TYPE_FRIEND)
        self.assertEqual(type_of(0.5), TYPE_FRIEND)
        self.assertEqual(type_of(0.499), TYPE_COOP)
        self.assertEqual(type_of(0.2), TYPE_COOP)
        self.assertEqual(type_of(0.199), TYPE_NEUTRAL)
        self.assertEqual(type_of(-0.199), TYPE_NEUTRAL)
        self.assertEqual(type_of(-0.2), TYPE_RIVAL)
        self.assertEqual(type_of(-0.499), TYPE_RIVAL)
        self.assertEqual(type_of(-0.5), TYPE_CONFLICT)


class TestNeo4jStoreGraceful(unittest.TestCase):
    """没配凭据时，镜像层必须安静地报告未启用，而不是抛异常。"""

    def test_not_configured(self):
        import os
        saved = os.environ.pop("NEO4J_PASSWORD", None)
        try:
            from graph_store import Neo4jGraphStore

            store = Neo4jGraphStore()
            self.assertFalse(store.configured)
            self.assertFalse(store.connect())
            result = store.sync({"nodes": [], "edges": []})
            self.assertFalse(result["synced"])
            self.assertIn("NEO4J_PASSWORD", result["reason"])
        finally:
            if saved is not None:
                os.environ["NEO4J_PASSWORD"] = saved


if __name__ == "__main__":
    unittest.main(verbosity=2)
