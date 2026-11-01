"""检查本机 Neo4j 是否可用（独立于后端，重启服务后跑一次最方便）。

三步：
    1. HTTP 探活：不带凭据访问 7474，判断认证是否已关闭
    2. 驱动连接：用 NEO4J_PASSWORD 或 NEO4J_AUTH=none 连 bolt
    3. 写读回环：MERGE 一个测试节点与关系，读回来，再删掉

用法：
    python tools/check_neo4j.py
    $env:NEO4J_AUTH='none'; python tools/check_neo4j.py     # 已关闭认证时
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request

HTTP = "http://127.0.0.1:7474"
BOLT = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
USER = os.getenv("NEO4J_USER", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD", "")
DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
NO_AUTH = os.getenv("NEO4J_AUTH", "").strip().lower() in ("none", "disabled", "false")


def check_http() -> int:
    """不带凭据 POST 一个空事务：200=认证已关闭，401=仍需要密码。"""
    body = b'{"statements":[]}'
    req = urllib.request.Request(HTTP + "/db/neo4j/tx/commit", data=body,
                                 method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            print(f"[1/3] HTTP 无凭据访问: {resp.status} → 认证已关闭 ✅")
            return 0
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            print("[1/3] HTTP 无凭据访问: 401 → 认证仍然开启 "
                  "（需要改 conf 后以管理员重启服务）")
        elif exc.code == 429:
            print("[1/3] HTTP 无凭据访问: 429 → 失败次数过多被临时锁定，等约 5 分钟")
        else:
            print(f"[1/3] HTTP 无凭据访问: {exc.code}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[1/3] 连不上 {HTTP}: {exc}")
        return 1


def check_driver() -> int:
    try:
        from neo4j import GraphDatabase
    except ImportError:
        print("[2/3] 未安装 neo4j 驱动：pip install neo4j")
        return 1

    auth = None if NO_AUTH else (USER, PASSWORD)
    label = "auth=None（无认证）" if NO_AUTH else f"user={USER}, password={'已配置' if PASSWORD else '空'}"
    try:
        driver = GraphDatabase.driver(BOLT, auth=auth)
        driver.verify_connectivity()
    except Exception as exc:  # noqa: BLE001
        print(f"[2/3] 连接失败（{label}）: {type(exc).__name__}: {exc}")
        return 1

    try:
        with driver.session(database=DATABASE) as session:
            version = session.run(
                "CALL dbms.components() YIELD versions, edition "
                "RETURN versions[0] AS v, edition AS e"
            ).single()
            print(f"[2/3] 连接成功（{label}）: Neo4j {version['v']} {version['e']}")

            # 写读回环
            session.run("MERGE (a:TmpCheck {id:'a'}) MERGE (b:TmpCheck {id:'b'}) "
                        "MERGE (a)-[r:CHECK]->(b) SET r.ok = true")
            rows = list(session.run(
                "MATCH (a:TmpCheck {id:'a'})-[r:CHECK]->(b:TmpCheck {id:'b'}) "
                "RETURN r.ok AS ok"))
            ok = bool(rows and rows[0]["ok"])
            session.run("MATCH (n:TmpCheck) DETACH DELETE n")
            print(f"[3/3] 写读回环: {'通过 ✅（已清理测试节点）' if ok else '失败'}")
            return 0 if ok else 1
    except Exception as exc:  # noqa: BLE001
        print(f"[3/3] 写读失败: {type(exc).__name__}: {exc}")
        return 1
    finally:
        driver.close()


def main() -> int:
    print(f"目标: {BOLT}  database={DATABASE}  "
          f"模式={'无认证' if NO_AUTH else '有认证'}\n")
    codes = [check_http(), check_driver()]
    print()
    if all(c == 0 for c in codes):
        print("[PASS] Neo4j 可用，可以开启图谱镜像")
        print("       后端启动时带上 NEO4J_AUTH=none（或 NEO4J_PASSWORD）")
        return 0
    print("[FAIL] 见上面哪一步没过")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
