"""拆开 retrieve_memories 的耗时：working / episodic 各占多少。

用法（必须用装了 torch + sentence-transformers 的解释器，且 EMBED_* 指向本地）；
    D:\\Venvs\\st\\Scripts\\python.exe tools\\bench_retrieve.py
"""
import os
import pathlib
import sys
import time
import shutil

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

os.environ["EMBED_MODEL_TYPE"] = "local"
os.environ["EMBED_MODEL_NAME"] = "sentence-transformers/all-MiniLM-L6-v2"
os.environ.pop("EMBED_BASE_URL", None)
os.environ.pop("EMBED_API_KEY", None)
os.environ.setdefault("HF_HOME", r"D:\HFCache")
os.environ["QDRANT_URL"] = "http://127.0.0.1:6333"
os.environ["QDRANT_COLLECTION"] = "cybertown_bench"
os.environ.pop("QDRANT_API_KEY", None)

from hello_agents.memory import MemoryConfig, MemoryManager  # noqa: E402

bench_dir = REPO / "backend" / "memory_data" / "_bench"
if bench_dir.exists():
    shutil.rmtree(bench_dir, ignore_errors=True)
bench_dir.mkdir(parents=True, exist_ok=True)

cfg = MemoryConfig(storage_path=str(bench_dir), working_memory_capacity=10, working_memory_tokens=2000)
t0 = time.perf_counter()
mm = MemoryManager(config=cfg, user_id="bench::player", enable_working=True, enable_episodic=True,
                   enable_semantic=False, enable_perceptual=False)
print(f"MemoryManager 初始化: {(time.perf_counter() - t0) * 1000:.0f} ms")

# 写入 6 条对话记忆（与真实 chat 一样不进 episodic）
t0 = time.perf_counter()
for i in range(3):
    mm.add_memory(content=f"玩家说: 第{i}轮问题，我叫小林，在做赛博小镇课程项目。",
                  memory_type="working", importance=0.5, auto_classify=False)
    mm.add_memory(content=f"我说: 第{i}轮回答，很高兴认识你小林。",
                  memory_type="working", importance=0.6, auto_classify=False)
    time.sleep(0.005)  # 绕开 hello_agents 的堆比较 bug：同 timestamp+同优先级会崩
print(f"写入 6 条: {(time.perf_counter() - t0) * 1000:.0f} ms")

query = "你还记得我的名字，以及我正在做什么项目吗？"
for types in (["working"], ["episodic"], ["working", "episodic"]):
    times = []
    for _ in range(3):
        t0 = time.perf_counter()
        got = mm.retrieve_memories(query=query, memory_types=types, limit=5, min_importance=0.3)
        times.append((time.perf_counter() - t0) * 1000)
    print(f"retrieve {str(types):<28} 返回 {len(got)} 条   "
          f"{'/'.join(f'{t:.0f}' for t in times)} ms")

shutil.rmtree(bench_dir, ignore_errors=True)
print("\n完成（bench 目录已清理）")
