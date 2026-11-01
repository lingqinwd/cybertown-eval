"""NPC ↔ NPC 社会关系图。

为什么是"图"，不是再加一个好感度
--------------------------------
`relationship_manager` 里只有 **NPC ↔ 玩家** 的一维好感度。要观察"两个 NPC 之间是朋友
还是对手、这个关系怎么随事件演化"，需要的是**边**：每对 NPC 一条，由事件驱动，带证据链。

设计取舍
--------
1. **内存为主，Neo4j 为可选镜像。** 3 个 NPC 只有 3 条无向边，用图数据库存是本末倒置；
   但把图同步到 Neo4j 有价值 —— 可以用 Cypher 查询、用 Neo4j Browser 直接演示关系网络。
   因此默认走内存，配了 `NEO4J_PASSWORD` 才镜像。
2. **强度是唯一的连续量，类型是从强度派生出来的。** 这样事件只需要加减一个数，
   不会出现"类型和强度互相矛盾"的状态。
3. **每次变动都留证据。** 学不到"为什么变成对手"，关系图就只是装饰。

已知边界
--------
* 关系只由显式事件驱动（`apply_event`），不会自己从对话里推断。
  自动推断需要 LLM 判定"这句话算不算帮忙"，属于未验证的设计，没做。
* 强度是启发式的（事件 → 固定增量），不是从数据里拟合出来的。
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# 事件 → 强度增量（作用于事件涉及的所有 NPC 对）
EVENT_RULES: Dict[str, float] = {
    "help": 0.30,        # 帮对方完成任务
    "cooperate": 0.20,   # 协作
    "praise": 0.10,      # 公开称赞
    "ignore": 0.0,       # 无互动
    "compete": -0.30,    # 争夺同一任务
    "conflict": -0.40,   # 正面冲突
    "betray": -0.60,     # 背约
}

TYPE_NEUTRAL = "neutral"
TYPE_COOP = "coop"
TYPE_FRIEND = "friend"
TYPE_RIVAL = "rival"
TYPE_CONFLICT = "conflict"

EVIDENCE_LIMIT = 20


def type_of(strength: float) -> str:
    """强度 → 关系类型。阈值是启发式的，改这里就能改口径。

    先四舍五入到 3 位：事件加减会产生 -0.19999999999999998 这类值，
    直接比阈值会把"恰好 -0.2"判成中立。
    """
    strength = round(strength, 3)
    if strength >= 0.5:
        return TYPE_FRIEND
    if strength >= 0.2:
        return TYPE_COOP
    if strength <= -0.5:
        return TYPE_CONFLICT
    if strength <= -0.2:
        return TYPE_RIVAL
    return TYPE_NEUTRAL


@dataclass
class Relation:
    a: str
    b: str
    strength: float = 0.0
    type: str = TYPE_NEUTRAL
    evidence: List[Dict[str, object]] = field(default_factory=list)
    updated_at: str = ""

    @property
    def key(self) -> Tuple[str, str]:
        return (a, b)

    def to_dict(self, include_evidence: bool = True) -> Dict[str, object]:
        data = {
            "a": self.a,
            "b": self.b,
            "pair": [self.a, self.b],
            "strength": round(self.strength, 3),
            "type": self.type,
            "updated_at": self.updated_at,
            "evidence_count": len(self.evidence),
        }
        if include_evidence:
            data["evidence"] = [dict(e) for e in self.evidence]
        return data


class RelationGraph:
    """无向图：每对 NPC 一条边。方向只在"谁对谁"的语义上，强度是共享的。"""

    def __init__(self, npcs: List[str]):
        self._lock = threading.RLock()
        self._npcs = list(dict.fromkeys(npcs))          # 去重保序
        self._edges: Dict[Tuple[str, str], Relation] = {}
        for i, a in enumerate(self._npcs):
            for b in self._npcs[i + 1:]:
                self._edges[(a, b)] = Relation(a=a, b=b)

    # -------------------------------------------------- 查询
    @property
    def npcs(self) -> List[str]:
        return list(self._npcs)

    def get(self, a: str, b: str) -> Relation:
        if a == b:
            raise ValueError("关系需要两个不同的 NPC")
        key = (a, b) if (a, b) in self._edges else (b, a)
        if key not in self._edges:
            raise KeyError(f"未知 NPC 对: {a} / {b}")
        return self._edges[key]

    def all(self, include_evidence: bool = True) -> List[Dict[str, object]]:
        with self._lock:
            edges = list(self._edges.values())
        return [r.to_dict(include_evidence) for r in edges]

    # -------------------------------------------------- 事件驱动
    def apply_event(self, kind: str, actors: List[str], weight: Optional[float] = None,
                    note: str = "") -> List[Dict[str, object]]:
        """把一次涉及多个 NPC 的事件作用到它们所有的边。

        例如 `actors=["张三","王五"]` 只影响一条边；三个 NPC 同时参与则影响三条边
        —— 这对应"三个人一起抢东西"这类情形。
        """
        if kind not in EVENT_RULES and weight is None:
            raise KeyError(f"未知事件类型: {kind}（可用: {', '.join(EVENT_RULES)}）")
        names = [n for n in dict.fromkeys(actors or []) if n in self._npcs]
        if len(names) < 2:
            raise ValueError("关系事件至少需要 2 个已知 NPC")

        base = EVENT_RULES.get(kind, 0.0) if weight is None else float(weight)
        now = datetime.now().isoformat(timespec="seconds")
        changed: List[Dict[str, object]] = []

        with self._lock:
            for i, a in enumerate(names):
                for b in names[i + 1:]:
                    rel = self.get(a, b)
                    before = rel.strength
                    rel.strength = round(max(-1.0, min(1.0, rel.strength + base)), 3)
                    rel.type = type_of(rel.strength)
                    rel.updated_at = now
                    rel.evidence.append({
                        "at": now,
                        "kind": kind,
                        "delta": round(rel.strength - before, 3),
                        "strength_after": round(rel.strength, 3),
                        "note": note,
                    })
                    rel.evidence = rel.evidence[-EVIDENCE_LIMIT:]
                    changed.append({
                        "pair": [a, b],
                        "type": rel.type,
                        "strength": round(rel.strength, 3),
                        "delta": round(rel.strength - before, 3),
                    })
        return changed

    # -------------------------------------------------- 给 UI / Neo4j 用
    def to_graph_payload(self) -> Dict[str, object]:
        """节点 + 边，Godot 面板与 Neo4j 镜像都用这个结构。"""
        with self._lock:
            edges = [r.to_dict(include_evidence=False) for r in self._edges.values()]
        return {
            "nodes": [{"id": n, "label": n} for n in self._npcs],
            "edges": edges,
        }

    def stats(self) -> Dict[str, object]:
        with self._lock:
            edges = list(self._edges.values())
        by_type: Dict[str, int] = {}
        for r in edges:
            by_type[r.type] = by_type.get(r.type, 0) + 1
        return {
            "npcs": len(self._npcs),
            "edges": len(edges),
            "by_type": by_type,
            "events": sum(len(r.evidence) for r in edges),
            "strongest": max(edges, key=lambda r: abs(r.strength)).to_dict(False)
            if edges else None,
        }


# ---------------------------------------------------------------- 单例

_LOCK = threading.Lock()
_GRAPH: Optional[RelationGraph] = None


def get_relation_graph(npcs: Optional[List[str]] = None) -> RelationGraph:
    """进程级单例。首次调用必须给出 NPC 列表（来自 NPC_ROLES）。"""
    global _GRAPH
    if _GRAPH is None:
        with _LOCK:
            if _GRAPH is None:
                if not npcs:
                    raise RuntimeError("首次创建关系图需要提供 NPC 列表")
                _GRAPH = RelationGraph(npcs)
    return _GRAPH


def reset_relation_graph(npcs: Optional[List[str]] = None) -> RelationGraph:
    global _GRAPH
    with _LOCK:
        _GRAPH = RelationGraph(npcs or (_GRAPH.npcs if _GRAPH else []))
    return _GRAPH
