"""2×2 / A-B-A-B 矩阵实验自动运行器。

为什么需要它
------------
归档的四组数据是**手工**跑的（Godot 点对话 / 浏览器控制台逐条发），既不可复现也无法
做重复实验。这个脚本把"按固定脚本跑满一组、记录每轮延迟与召回、最后出汇总"自动化。

设计要点
--------
1. **交错顺序抵消时间漂移**：`--repeats 2` 时顺序是 A,B,B,A —— 每个臂各有一次靠前
   和一次靠后，时间趋势对称，这正是归档实验缺的那一步。
2. **一个臂一个后端进程**：`MEMORY_MODE` 是启动期开关，运行时改不了。所以每个 block
   单独拉起后端、跑完即停。好处是顺带控制了模型热缓存等跨臂污染。
3. **召回数取自服务端 CSV**：每轮前后对 `backend/logs/metrics_*.csv` 做行数差，
   拿到该请求真实写入的 `memory_recall_count`，与归档数据同一口径。
4. **每个 block 用独立 player_id**：记忆按 (NPC, 玩家) 隔离，因此无需清库就能保证
   block 之间互不污染。

用法
----
    # 先看一眼计划
    python tools/run_matrix.py --repeats 2 --dry-run

    # 正式跑（本地 Ollama）
    python tools/run_matrix.py --repeats 2 --out experiments/matrix_local_qwen.csv

    # 只跑 2 轮冒烟
    python tools/run_matrix.py --repeats 1 --turns 2

记忆开启（MEMORY_MODE=on）需要本地 Qdrant：
    docker start helloagents-qdrant-ch15
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# 与归档实验完全一致的六轮脚本（3 个 NPC × 2 轮）
SCRIPT = [
    ("李四", "你好，我叫小林，我正在做一个赛博小镇课程项目，请记住我的名字和项目名称。"),
    ("李四", "你还记得我的名字，以及我正在做什么项目吗？"),
    ("张三", "你主要负责什么？"),
    ("张三", "你能给我的赛博小镇项目一个建议吗？"),
    ("王五", "你主要负责什么？"),
    ("王五", "你能给我的赛博小镇项目一个建议吗？"),
]

RECALL_TURN = 1                      # 0 基：第二轮是"你还记得…"的追问
FACT_TOKENS = ("小林", "赛博小镇")   # 命中其一即认为事实被召回

REPO = pathlib.Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
LOGS = BACKEND / "logs"


# ---------------------------------------------------------------- HTTP
def api(base: str, path: str, payload=None, timeout: int = 300):
    url = base.rstrip("/") + path
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    if data:
        req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wait_health(base: str, proc: subprocess.Popen, timeout: float = 120.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"后端启动即退出（exit={proc.returncode}），看 {LOGS} 下的日志")
        try:
            api(base, "/health", timeout=3)
            return
        except Exception:  # noqa: BLE001
            time.sleep(1)
    raise RuntimeError(f"后端 {timeout:.0f}s 内未就绪")


# ---------------------------------------------------------------- metrics CSV
def metrics_file() -> pathlib.Path:
    return LOGS / f"metrics_{time.strftime('%Y-%m-%d')}.csv"


def metrics_row_count() -> int:
    path = metrics_file()
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return sum(1 for _ in fh) - 1          # 减表头


def metrics_new_rows(since: int):
    """取第 since 行之后追加的记录（含表头解析）。"""
    path = metrics_file()
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return rows[since:]


# ---------------------------------------------------------------- server
def parse_env_pairs(pairs):
    """把 ["K=V", ...] 解析成 dict。"""
    out = {}
    for item in pairs or []:
        if "=" not in item:
            raise SystemExit(f"--env 需要 K=V 形式，收到: {item}")
        key, value = item.split("=", 1)
        out[key.strip()] = value
    return out


def start_server(args, memory_mode: str, port: int) -> subprocess.Popen:
    env = dict(os.environ)
    env.update({
        "MEMORY_MODE": memory_mode,
        "ACTION_PROPOSAL": args.action_proposal,
        "MODEL_PROFILE": args.model_profile,
        "LLM_PROVIDER": args.provider,
        "LLM_MODEL_ID": args.model_id,
        "LLM_BASE_URL": args.base_url,
        "LLM_API_KEY": args.api_key,
        "LLM_TIMEOUT": str(args.llm_timeout),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",   # 否则 print 在 SIGTERM 时丢失，失败会静默
        "PYTHONUTF8": "1",
        "QDRANT_COLLECTION": args.collection,
    })
    env.update(parse_env_pairs(args.env))
    if args.qdrant_url:
        env["QDRANT_URL"] = args.qdrant_url
    log = open(LOGS / f"matrix_server_{memory_mode}_{int(time.time())}.log", "wb")
    python_exe = args.python or sys.executable
    return subprocess.Popen(
        [python_exe, "-m", "uvicorn", "main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(BACKEND), env=env, stdout=log, stderr=subprocess.STDOUT,
    )


def stop_server(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=15)


# ---------------------------------------------------------------- plan
def build_plan(arms, repeats):
    """A,B,B,A,... 每个臂一次靠前、一次靠后，抵消时间漂移。"""
    plan = []
    for r in range(repeats):
        order = arms if r % 2 == 0 else list(reversed(arms))
        for arm in order:
            plan.append((r + 1, arm))
    return plan


def run_block(args, port, memory_mode, repeat, turns):
    base = f"http://127.0.0.1:{port}"
    player = f"matrix_{memory_mode}_r{repeat}"
    rows = []
    proc = start_server(args, memory_mode, port)
    try:
        wait_health(base, proc, timeout=args.ready_timeout)
        cfg = api(base, "/runtime/config", timeout=10)
        print(f"    后端就绪: mode={cfg.get('memory_mode')} model={cfg.get('model')} "
              f"action={cfg.get('action_proposal')}")
        for idx, (npc, message) in enumerate(SCRIPT[:turns]):
            before = metrics_row_count()
            started = time.perf_counter()
            ok, reply, act = True, "", None
            try:
                out = api(base, "/chat", {"npc_name": npc, "message": message,
                                          "player_id": player}, timeout=args.turn_timeout)
                reply = out.get("message") or ""
                act = out.get("action")
            except Exception as exc:  # noqa: BLE001
                ok, reply = False, f"<request failed: {exc}>"
            latency = (time.perf_counter() - started) * 1000
            new_rows = metrics_new_rows(before)
            rec = new_rows[-1] if new_rows else {}
            recall = int(rec.get("memory_recall_count") or 0)
            fact_hit = any(tok in reply for tok in FACT_TOKENS) if idx == RECALL_TURN else None
            rows.append({
                "repeat": repeat, "memory_mode": memory_mode,
                "model_profile": cfg.get("model_profile", ""),
                "model": cfg.get("model", ""), "turn": idx + 1, "npc": npc,
                "message": message, "client_latency_ms": round(latency, 1),
                "server_latency_ms": rec.get("latency_ms", ""),
                "memory_recall_count": recall,
                "affinity_after": rec.get("affinity_after", ""),
                "action_code": (act or {}).get("code", "") if act else "",
                "fact_recall_hit": "" if fact_hit is None else int(fact_hit),
                "request_ok": int(ok), "reply": reply.replace("\n", " "),
            })
            flag = ""
            if idx == RECALL_TURN:
                flag = "  ← 事实命中" if fact_hit else "  ← 未命中"
            print(f"    [{idx+1}/{turns}] {npc} {latency:8.0f} ms  recall={recall}"
                  f"{flag}  {reply[:26]}")
    finally:
        stop_server(proc)
    return rows


# ---------------------------------------------------------------- summary
def summarize(rows):
    if not rows:
        return
    print("\n=== 汇总 ===")
    print(f"{'记忆':<6}{'样本':>5}{'均值 ms':>10}{'中位 ms':>10}{'召回总数':>9}")
    print("-" * 44)
    by_arm = {}
    for row in rows:
        by_arm.setdefault(row["memory_mode"], []).append(row)
    stats = {}
    for arm, items in by_arm.items():
        lat = [r["client_latency_ms"] for r in items if r["request_ok"]]
        recall = sum(r["memory_recall_count"] for r in items)
        stats[arm] = (statistics.mean(lat), statistics.median(lat))
        print(f"{arm:<6}{len(lat):>5}{statistics.mean(lat):>10.0f}"
              f"{statistics.median(lat):>10.0f}{recall:>9}")
    if "on" in stats and "off" in stats:
        ratio = stats["on"][0] / stats["off"][0]
        print("-" * 44)
        print(f"记忆开销倍数（均值 on/off）: {ratio:.2f}×"
              f"   （中位: {stats['on'][1] / stats['off'][1]:.2f}×）")
    hits = [r["fact_recall_hit"] for r in rows if r["fact_recall_hit"] != ""]
    if hits:
        print(f"追问事实命中: {sum(hits)}/{len(hits)}")


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="2×2 / A-B-A-B 矩阵实验运行器")
    ap.add_argument("--arms", default="off,on", help="逗号分隔的 MEMORY_MODE 列表")
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--turns", type=int, default=len(SCRIPT))
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--out", default="")
    ap.add_argument("--dry-run", action="store_true")

    ap.add_argument("--model-profile", default="local_ollama")
    ap.add_argument("--provider", default="openai")
    ap.add_argument("--model-id", default="qwen2.5:1.5b")
    ap.add_argument("--base-url", default="http://127.0.0.1:11434/v1")
    ap.add_argument("--api-key", default="ollama")
    ap.add_argument("--llm-timeout", type=int, default=300)
    ap.add_argument("--action-proposal", default="off",
                    help="矩阵实验默认关闭，保持与归档实验同口径")
    ap.add_argument("--collection", default="cybertown_matrix")
    ap.add_argument("--qdrant-url", default="")
    ap.add_argument("--skip-qdrant-check", action="store_true")
    ap.add_argument("--env", action="append", default=[],
                    help="额外环境变量 K=V，可重复；用于 EMBED_MODEL_TYPE 等")
    ap.add_argument("--python", default="",
                    help="启动后端用的解释器路径，默认与当前脚本相同")
    ap.add_argument("--ready-timeout", type=float, default=180.0)
    ap.add_argument("--turn-timeout", type=int, default=300)
    args = ap.parse_args()

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    plan = build_plan(arms, args.repeats)

    print("=== 计划 ===")
    for i, (repeat, arm) in enumerate(plan, 1):
        print(f"  block {i}: 第 {repeat} 次 / MEMORY_MODE={arm} / {args.turns} 轮")
    print(f"  模型: {args.model_id} @ {args.base_url}")
    if args.env:
        print(f"  额外环境: {args.env}")
    if args.python:
        print(f"  后端解释器: {args.python}")
    if args.dry_run:
        return 0

    if "on" in arms and not args.skip_qdrant_check:
        qdrant = args.qdrant_url or os.getenv("QDRANT_URL") or "http://127.0.0.1:6333"
        try:
            api(qdrant, "/collections", timeout=5)
            print(f"  Qdrant 可用: {qdrant}")
        except Exception as exc:  # noqa: BLE001
            print(f"\n[中止] MEMORY_MODE=on 需要 Qdrant，连不上 {qdrant}: {exc}")
            print("       先执行: docker start helloagents-qdrant-ch15")
            return 2

    try:
        api(f"http://127.0.0.1:{args.port}", "/health", timeout=3)
        print(f"\n[中止] 端口 {args.port} 已有后端在跑，请先停止它（本脚本要自己拉起进程）")
        return 2
    except Exception:  # noqa: BLE001
        pass

    LOGS.mkdir(parents=True, exist_ok=True)
    all_rows = []
    for i, (repeat, arm) in enumerate(plan, 1):
        print(f"\n[block {i}/{len(plan)}] 第 {repeat} 次 · MEMORY_MODE={arm}")
        try:
            all_rows.extend(run_block(args, args.port, arm, repeat, args.turns))
        except Exception as exc:  # noqa: BLE001
            print(f"  [失败] {exc}")

    summarize(all_rows)

    if args.out and all_rows:
        target = pathlib.Path(args.out)
        if not target.is_absolute():
            target = REPO / target
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(all_rows[0].keys()))
            writer.writeheader()
            writer.writerows(all_rows)
        print(f"\n明细已写入: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
