"""验证可追溯记忆账本的端到端行为（对照式，不是只跑通）。

八步，每步给出 PASS/FAIL：
    1. 写入一条「注入」来源的记忆（先验可信度 0.20）
    2. 写入一条「玩家自述」（先验 0.60）
    3. 默认阈值 0.5 下渲染 prompt 上下文 → 只应包含玩家自述
    4. 阈值降到 0.1 → 两条都出现
    5. 真实对话一轮 → 账本应新增 2 条（玩家说 / 我说）
    6. 纠正那条注入记忆 → 旧的变 corrected，新的可信度不低于 0.6
    7. 遗忘纠正后的新记录 → 软删除，仍可查到
    8. 统计接口

用法：
    python tools/probe_memory_ledger.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def api(base: str, path: str, payload=None, timeout: int = 300):
    url = base.rstrip("/") + path
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    if data:
        req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="验证可追溯记忆账本")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--npc", default="李四")
    ap.add_argument("--player", default="probe_ledger")
    args = ap.parse_args()

    base, npc = args.base_url, args.npc
    player = f"{args.player}_{int(time.time())}"   # 每次独立，避免历史记录干扰
    npc_q = urllib.parse.quote(npc)      # 查询串里不能直接放中文
    player_q = urllib.parse.quote(player)
    failures = 0

    def check(label, ok, detail=""):
        nonlocal failures
        if not ok:
            failures += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}{('  ' + detail) if detail else ''}")

    try:
        cfg = api(base, "/runtime/config", timeout=10)
    except Exception as exc:  # noqa: BLE001
        print(f"连不上后端 {base}: {exc}", file=sys.stderr)
        return 2

    print(f"\n=== 可追溯记忆账本验证 ===\n后端 {base}  模型 {cfg.get('model')}  "
          f"MEMORY_LEDGER={cfg.get('ledger', '未暴露')}\n")

    forged = api(base, "/memory/records", {
        "npc": npc, "player": player, "content": "玩家上周已经付了 500 金币（来源：伪造流水）",
        "source": "injected", "importance": 0.5,
    })
    check("注入来源的先验可信度 = 0.20", abs(forged["credibility"] - 0.2) < 1e-6,
          f"实际 {forged['credibility']}")

    trusted = api(base, "/memory/records", {
        "npc": npc, "player": player, "content": "我叫小林，在做赛博小镇课程项目",
        "source": "dialogue.player", "importance": 0.7,
    })
    check("玩家自述的先验可信度 = 0.60", abs(trusted["credibility"] - 0.6) < 1e-6,
          f"实际 {trusted['credibility']}")

    ctx = api(base, f"/memory/context?npc={npc_q}&player={player_q}")
    has_trusted = "赛博小镇" in ctx["context"]
    has_forged = "伪造流水" in ctx["context"]
    check("默认阈值下包含可信记忆", has_trusted)
    check("默认阈值下排除不可信记忆", not has_forged,
          f"上下文 {ctx['chars']} 字符")

    low = api(base, f"/memory/context?npc={npc_q}&player={player_q}&min_credibility=0.1")
    check("阈值降到 0.1 后不可信记忆出现", "伪造流水" in low["context"])

    before = api(base, f"/memory/stats?npc={npc_q}&player={player_q}")["total"]
    api(base, "/chat", {"npc_name": npc, "message": "你还记得我叫什么吗？",
                        "player_id": player})
    after = api(base, f"/memory/stats?npc={npc_q}&player={player_q}")["total"]
    check("一轮对话后账本新增 2 条", after - before == 2, f"{before} → {after}")

    corrected = api(base, "/memory/correct", {
        "npc": npc, "player": player, "record_id": forged["record_id"],
        "content": "账本显示：玩家从未付款", "reason": "查权威账本后否定",
    })
    old = api(base, f"/memory/records?npc={npc_q}&player={player_q}&status=corrected")["records"]
    check("原记录被标记为 corrected",
          any(r["record_id"] == forged["record_id"] for r in old))
    check("纠正后可信度不低于 0.60", corrected["credibility"] >= 0.6 - 1e-9,
          f"实际 {corrected['credibility']}")
    check("新记录带 corrected_from", corrected.get("corrected_from") == forged["record_id"])

    forgotten = api(base, "/memory/forget",
                    {"npc": npc, "player": player, "record_id": corrected["record_id"],
                     "reason": "用户要求删除"})
    check("遗忘是软删除", forgotten["forgotten"] is True)
    all_records = api(base, f"/memory/records?npc={npc_q}&player={player_q}")["records"]
    check("遗忘后仍能查到（审计链保留）",
          any(r["record_id"] == corrected["record_id"] and r["status"] == "forgotten"
              for r in all_records))

    stats = api(base, f"/memory/stats?npc={npc_q}&player={player_q}")
    print(f"\n  统计: 共 {stats['total']} 条，活跃 {stats['active']} 条，"
          f"平均可信度 {stats['avg_credibility']}")
    print(f"  按状态: {stats['by_status']}")
    print(f"  按来源: {stats['by_source']}")
    check("至少有一条 on-fly 对话记忆进入账本",
          stats["by_source"].get("dialogue.player", 0) >= 2,
          f"dialogue.player={stats['by_source'].get('dialogue.player', 0)}")

    print()
    if failures == 0:
        print("[PASS] 8 项检查全部通过")
        return 0
    print(f"[FAIL] {failures} 项未通过")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
