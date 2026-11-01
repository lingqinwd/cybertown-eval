"""A/B 实验：动作提议开关对「越权拦截」的影响。

对一个正在运行的后端跑全部场景，输出每个场景的：提议轮数、裁决分布、判据是否通过。
两次运行（后端 ACTION_PROPOSAL=off / on）拼起来就是对照表。

用法：
    python tools/run_ab_scenarios.py --label action_off
    python tools/run_ab_scenarios.py --label action_on --out experiments/ab_action_on.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
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


def run_one(base: str, scenario_id: str, player: str) -> dict:
    loaded = api(base, "/scenario/load", {"id": scenario_id})["scenario"]
    script = loaded["script"]

    proposals = 0
    codes: dict = {}
    detail = []
    for step in script:
        resp = api(base, "/chat", {"npc_name": step["npc"], "message": step["say"],
                                   "player_id": player})
        action = resp.get("action") or {}
        if action:
            proposals += 1
            name = str(action.get("proposed") or "?")
            code = str(action.get("code") or "?")
            codes[code] = codes.get(code, 0) + 1
            message = str(action.get("message") or "").replace(";", ",")[:40]
            detail.append(f"t{step['turn']}:{name}/{code}/{message}")

    state = api(base, "/scenario/state", timeout=10)
    failures = state.get("failures") or []
    return {
        "scenario": scenario_id,
        "turns": len(script),
        "proposals": proposals,
        "codes": ";".join(f"{k}×{v}" for k, v in sorted(codes.items())),
        "detail": ";".join(detail),
        "failures": len(failures),
        "passed": "PASS" if not failures else "FAIL",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--label", default="run")
    ap.add_argument("--player", default="ab_user")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    cfg = api(args.base_url, "/runtime/config", timeout=10)
    rows = []
    for path in sorted(SCEN_DIR.glob("*.yaml")):
        rows.append(run_one(args.base_url, path.stem, args.player))

    total_proposals = sum(r["proposals"] for r in rows)
    total_fail = sum(r["failures"] for r in rows)
    print(f"\n=== A/B 组: {args.label} ===")
    print(f"后端: model={cfg.get('model')} memory={cfg.get('memory_mode')} "
          f"action_proposal={cfg.get('action_proposal')}")
    print(f"{'scenario':<20}{'提议':>4}   {'裁决':<34}{'判据'}")
    print("-" * 74)
    for r in rows:
        print(f"{r['scenario']:<20}{r['proposals']:>4}   {(r['codes'] or '-'):<34}{r['passed']}")
    print("-" * 74)
    print(f"合计: 提议 {total_proposals} 次，判据失败 {total_fail} 项")

    if args.out:
        target = pathlib.Path(args.out)
        if not target.is_absolute():
            target = REPO / target
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8-sig", newline="") as fh:
            fields = ["label", "action_proposal"] + (list(rows[0].keys()) if rows else [])
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for r in rows:
                writer.writerow({"label": args.label,
                                 "action_proposal": cfg.get("action_proposal"), **r})
        print(f"明细: {target}")
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
