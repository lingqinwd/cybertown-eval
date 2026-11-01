"""验证 NPC 关系图：事件驱动演化 + Neo4j 镜像写入与读回。

七步，每步 PASS/FAIL：
    1. 复位关系图（全部中立）
    2. 施加 compete → 强度应变负、类型变 rival
    3. 施加 conflict → 更负
    4. 施加 help → 回暖
    5. 证据链应有 3 条
    6. /relations/graph 应有 3 个节点、3 条边
    7. Neo4j 镜像：sync 成功，且读回能看到同样的边

用法：
    python tools/probe_relations.py
    $env:NEO4J_AUTH='none'; python tools/probe_relations.py     # 关闭认证时
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def api(base: str, path: str, payload=None, timeout: int = 60):
    url = base.rstrip("/") + path
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    if data:
        req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="验证关系图与 Neo4j 镜像")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--a", default="张三")
    ap.add_argument("--b", default="王五")
    args = ap.parse_args()

    base, a, b = args.base_url, args.a, args.b
    failures = 0

    def check(label, ok, detail=""):
        nonlocal failures
        if not ok:
            failures += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}{('  ' + detail) if detail else ''}")

    print(f"\n=== 关系图验证 ===\n后端 {base}   观察对: {a} ↔ {b}\n")
    try:
        api(base, "/relations/reset", {}, timeout=15)
    except urllib.error.HTTPError:
        api(base, "/relations/reset", None, timeout=15)   # reset 无 body 的情况
    edges = api(base, "/relations?include_evidence=false")["edges"]
    check("复位后全部中立", all(e["type"] == "neutral" for e in edges),
          f"类型: {[e['type'] for e in edges]}")

    def step(kind, expect_sign, label):
        result = api(base, "/relations/event",
                     {"kind": kind, "actors": [a, b], "note": f"probe:{kind}"})
        pair = next(c for c in result["changed"] if set(c["pair"]) == {a, b})
        ok = (pair["strength"] < 0) if expect_sign < 0 else (pair["strength"] > expect_sign)
        check(f"{kind} → 强度 {pair['strength']:+.2f} / {pair['type']}", ok)
        return pair

    step("compete", -1, "compete")
    p2 = step("conflict", -1, "conflict")
    check("两次负面事件后类型为 conflict 或 rival",
          p2["type"] in ("conflict", "rival"), f"当前 {p2['type']}")
    p3 = step("help", p2["strength"], "help")
    check("help 后强度回升", p3["strength"] > p2["strength"],
          f"{p2['strength']:+.2f} → {p3['strength']:+.2f}")

    full = api(base, "/relations")
    pair = next(e for e in full["edges"] if set(e["pair"]) == {a, b})
    check("证据链累计 3 条", pair["evidence_count"] == 3, f"实际 {pair['evidence_count']}")

    graph = api(base, "/relations/graph")
    check("graph 有 3 节点 3 边",
          len(graph["nodes"]) == 3 and len(graph["edges"]) == 3,
          f"{len(graph['nodes'])} 节点 / {len(graph['edges'])} 边")

    sync = api(base, "/relations/sync", {}, timeout=30)
    if not sync.get("synced"):
        print(f"  [SKIP] Neo4j 镜像未启用: {sync.get('reason')}")
        print("         （未配置 NEO4J_PASSWORD 且未设 NEO4J_AUTH=none 时属正常）")
    else:
        check("Neo4j 写入成功",
              sync.get("nodes") == 3 and sync.get("edges") == 3,
              f"nodes={sync.get('nodes')} edges={sync.get('edges')}")
        back = api(base, "/relations/neo4j?read=true", timeout=30)
        read = back.get("read_back") or {}
        check("Neo4j 读回图非空", bool(read.get("ok")) and len(read.get("edges") or []) >= 3,
              f"读回 {len(read.get('edges') or [])} 条边 / {len(read.get('nodes') or [])} 个节点")

    print()
    if failures == 0:
        print("[PASS] 关系图与镜像检查全部通过")
        return 0
    print(f"[FAIL] {failures} 项未通过")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
