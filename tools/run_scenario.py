"""运行一个可重复实验场景。

流程：
    POST /scenario/load  → 重置世界状态、写入 initial
    逐轮 POST /chat      → 服务端在该轮开始前施放事件、注入环境描述
    GET  /scenario/state → 读取判据结果

用法：
    python tools/run_scenario.py --list
    python tools/run_scenario.py --scenario coercion
    python tools/run_scenario.py --scenario resource_shortage --out experiments/scenario_resource.csv

前置：后端已启动。若场景涉及越权动作，后端应以 `ACTION_PROPOSAL=on` 启动，
否则模型不会产出动作标记，只能验证"状态不被改写"这一半。
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
SCEN_DIR = REPO / "scenarios"


def api(base: str, path: str, payload=None, timeout: int = 300):
    url = base.rstrip("/") + path
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    if data:
        req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_scenarios() -> int:
    files = sorted(SCEN_DIR.glob("*.yaml"))
    if not files:
        print("scenarios/ 下没有场景")
        return 1
    print(f"{'id':<22}{'轮数':>4}  标题")
    print("-" * 66)
    for path in files:
        stem = path.stem
        title = ""
        try:
            import yaml
            with path.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            title = str(data.get("title") or "")
            turns = len(data.get("script") or [])
        except Exception:  # noqa: BLE001
            turns = 0
        print(f"{stem:<22}{turns:>4}  {title}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="运行可重复实验场景")
    ap.add_argument("--scenario", default="")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--player", default="player")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    if args.list or not args.scenario:
        return list_scenarios()

    try:
        cfg = api(args.base_url, "/runtime/config", timeout=10)
    except Exception as exc:  # noqa: BLE001
        print(f"连不上后端 {args.base_url}: {exc}", file=sys.stderr)
        return 2

    print(f"\n=== 场景 {args.scenario} ===")
    print(f"后端: {args.base_url}  模型: {cfg.get('model')}  "
          f"记忆: {cfg.get('memory_mode')}  动作提议: {cfg.get('action_proposal')}")

    try:
        loaded = api(args.base_url, "/scenario/load", {"id": args.scenario})
    except urllib.error.HTTPError as exc:
        print(f"[失败] 装载场景: {exc.code} {exc.read().decode('utf-8', 'ignore')[:200]}")
        return 2
    scenario = loaded["scenario"]
    print(f"标题: {scenario['title']}   轮数: {scenario['turns']}   "
          f"事件: {len(scenario['events'])}   判据: {len(scenario['assertions'])}\n")

    rows = []
    for step in scenario["script"]:
        turn = step["turn"]
        npc = step["npc"]
        say = step["say"]
        try:
            reply_obj = api(args.base_url, "/chat",
                            {"npc_name": npc, "message": say, "player_id": args.player})
            reply = reply_obj.get("message") or ""
            action = reply_obj.get("action") or {}
            code = action.get("code", "") if action else ""
            proposed = action.get("proposed", "") if action else ""
        except Exception as exc:  # noqa: BLE001
            reply, code = f"<请求失败: {exc}>", "request_error"
        mark = f"  动作={proposed or '?'}({code})" if code else ""
        print(f"[{turn}] {npc}: {say[:26]}")
        print(f"     → {reply[:64]}{mark}")
        rows.append({"turn": turn, "npc": npc, "say": say, "reply": reply.replace("\n", " "),
                     "action_proposed": proposed, "action_code": code})

    state = api(args.base_url, "/scenario/state", timeout=10)
    failures = state.get("failures") or []

    print("\n=== 判据 ===")
    if failures:
        for f in failures:
            print(f"  [FAIL] {f}")
    else:
        print("  全部通过 ✅")

    print(f"\n最终状态版本: {state.get('state_version')}   已跑轮次: {state.get('current_turn')}")

    if args.out:
        target = pathlib.Path(args.out)
        if not target.is_absolute():
            target = REPO / target
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["turn"])
            writer.writeheader()
            writer.writerows(rows)
        print(f"明细已写入: {target}")

    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
