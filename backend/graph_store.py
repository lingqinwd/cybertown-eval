"""把 NPC 关系图镜像到 Neo4j（可选）。

为什么是"可选镜像"
------------------
3 个 NPC 只有 3 条边，用图数据库存是杀鸡用牛刀 —— **内存图才是权威**。
但镜像到 Neo4j 有两个真实好处：

1. 用 Cypher 做多跳查询（"谁和谁是一条线上的"），内存版没实现；
2. 答辩演示时可以直接开 Neo4j Browser 看关系网络，比看 JSON 直观。

因此：没配 `NEO4J_PASSWORD` 就完全不启用，**不影响任何其它功能**；配了才同步。
这样关系图谱不依赖数据库可用性，也不会因为数据库挂了而拖垮对话。
"""

from __future__ import annotations

import os
import threading
from typing import Dict, Optional

DEFAULT_URI = "bolt://127.0.0.1:7687"
DEFAULT_USER = "neo4j"
DEFAULT_DATABASE = "neo4j"

_SYNC_CYPHER = """
UNWIND $nodes AS n
MERGE (x:NPC {id: n.id})
SET x.label = n.label
"""

_SYNC_EDGES_CYPHER = """
UNWIND $edges AS e
MATCH (a:NPC {id: e.a})
MATCH (b:NPC {id: e.b})
MERGE (a)-[r:RELATES]->(b)
SET r.strength = e.strength, r.type = e.type, r.updated_at = e.updated_at
"""


class Neo4jGraphStore:
    """惰性连接的 Neo4j 客户端。任何异常都只影响同步，不影响主流程。"""

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
    ):
        self.uri = uri or os.getenv("NEO4J_URI") or DEFAULT_URI
        self.user = user or os.getenv("NEO4J_USER") or DEFAULT_USER
        self.password = password if password is not None else os.getenv("NEO4J_PASSWORD", "")
        # 关闭认证时（conf 里 auth_enabled=false）用 auth=None 连接
        self.no_auth = os.getenv("NEO4J_AUTH", "").strip().lower() in ("none", "disabled", "false")
        self.database = database or os.getenv("NEO4J_DATABASE") or DEFAULT_DATABASE
        self._driver = None
        self._lock = threading.Lock()
        self.last_error: str = ""

    # -------------------------------------------------- 状态
    @property
    def configured(self) -> bool:
        return self.no_auth or bool(self.password)

    @property
    def available(self) -> bool:
        return self._driver is not None

    def describe(self) -> Dict[str, object]:
        return {
            "configured": self.configured,
            "no_auth": self.no_auth,
            "connected": self.available,
            "uri": self.uri,
            "database": self.database,
            "last_error": self.last_error,
        }

    # -------------------------------------------------- 连接
    def connect(self) -> bool:
        if not self.configured:
            self.last_error = ("未配置 NEO4J_PASSWORD（或 NEO4J_AUTH=none），镜像未启用")
            return False
        if self._driver is not None:
            return True
        try:
            from neo4j import GraphDatabase
        except ImportError:
            self.last_error = "未安装 neo4j 驱动（pip install neo4j）"
            return False
        try:
            auth = None if self.no_auth else (self.user, self.password)
            driver = GraphDatabase.driver(self.uri, auth=auth)
            driver.verify_connectivity()
        except Exception as exc:  # 连接失败不该抛到调用方
            self.last_error = f"连接失败: {type(exc).__name__}: {exc}"
            return False
        with self._lock:
            self._driver = driver
        return True

    def close(self) -> None:
        with self._lock:
            if self._driver is not None:
                try:
                    self._driver.close()
                except Exception:  # noqa: BLE001
                    pass
                self._driver = None

    # -------------------------------------------------- 同步
    def sync(self, payload: Dict[str, object]) -> Dict[str, object]:
        """把 nodes / edges 写进 Neo4j。返回同步结果，失败不抛异常。"""
        if not self.connect():
            return {"synced": False, "reason": self.last_error}

        nodes = payload.get("nodes") or []
        edges = payload.get("edges") or []
        try:
            with self._driver.session(database=self.database) as session:
                session.run(_SYNC_CYPHER, nodes=nodes)
                session.run(_SYNC_EDGES_CYPHER, edges=edges)
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"写入失败: {type(exc).__name__}: {exc}"
            return {"synced": False, "reason": self.last_error}

        self.last_error = ""
        return {"synced": True, "nodes": len(nodes), "edges": len(edges),
                "database": self.database}

    def read_back(self, limit: int = 50) -> Dict[str, object]:
        """读回图，用于验证镜像确实写进去了。"""
        if not self.connect():
            return {"ok": False, "reason": self.last_error}
        try:
            with self._driver.session(database=self.database) as session:
                rows = session.run(
                    "MATCH (a:NPC)-[r:RELATES]->(b:NPC) "
                    "RETURN a.id AS a, b.id AS b, r.strength AS strength, r.type AS type "
                    "LIMIT $limit",
                    limit=limit,
                )
                edges = [dict(record) for record in rows]
                node_rows = session.run("MATCH (n:NPC) RETURN n.id AS id LIMIT $limit",
                                        limit=limit)
                nodes = [dict(record)["id"] for record in node_rows]
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"读取失败: {type(exc).__name__}: {exc}"
            return {"ok": False, "reason": self.last_error}
        return {"ok": True, "nodes": nodes, "edges": edges}


_STORE: Optional[Neo4jGraphStore] = None
_LOCK = threading.Lock()


def get_graph_store() -> Neo4jGraphStore:
    """进程级单例，读环境变量。"""
    global _STORE
    if _STORE is None:
        with _LOCK:
            if _STORE is None:
                _STORE = Neo4jGraphStore()
    return _STORE
