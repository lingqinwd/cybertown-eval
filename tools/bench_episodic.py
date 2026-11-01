"""把 EpisodicMemory.retrieve 拆到子调用级别，定位那 2 秒。

retrieve 里其实有两条路径：
  1) importance_threshold / time_range 非空  -> doc_store.search_memories（SQLite）
  2) 总是执行                                -> embedder.encode + vector_store.search_similar
分别计时即可判断 2 秒花在哪一条。
"""
import os
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / "backend" / ".env")
os.environ["EMBED_MODEL_TYPE"] = "local"
os.environ["EMBED_MODEL_NAME"] = "sentence-transformers/all-MiniLM-L6-v2"
os.environ["EMBED_BASE_URL"] = ""
os.environ["EMBED_API_KEY"] = ""
os.environ.setdefault("HF_HOME", r"D:\HFCache")
os.environ.setdefault("QDRANT_URL", "http://127.0.0.1:6333")

import shutil  # noqa: E402

from hello_agents.memory import MemoryConfig, MemoryManager  # noqa: E402

bench = REPO / "backend" / "memory_data" / "_bench2"
shutil.rmtree(bench, ignore_errors=True)
bench.mkdir(parents=True, exist_ok=True)
cfg = MemoryConfig(storage_path=str(bench), working_memory_capacity=10, working_memory_tokens=2000)
mm = MemoryManager(config=cfg, user_id="bench2::p", enable_working=True,
                   enable_episodic=True, enable_semantic=False, enable_perceptual=False)
epi = mm.memory_types["episodic"]
query = "你还记得我的名字，以及我正在做什么项目吗？"


def timeit(label, fn, n=3):
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            print(f"  {label:<44} 异常: {type(exc).__name__}: {exc}")
            return
        ts.append((time.perf_counter() - t0) * 1000)
    print(f"  {label:<44} {'/'.join(f'{t:.0f}' for t in ts)} ms")


print("=== 子调用拆分 ===")
timeit("epi.retrieve(无 kwargs)", lambda: epi.retrieve(query, limit=5))
timeit("epi.retrieve(importance_threshold=0.3)",
       lambda: epi.retrieve(query, limit=5, importance_threshold=0.3))
timeit("epi.embedder.encode(query)", lambda: epi.embedder.encode(query))
vec = epi.embedder.encode(query)
if hasattr(vec, "tolist"):
    vec = vec.tolist()

timeit("epi.vector_store.search_similar",
       lambda: epi.vector_store.search_similar(query_vector=vec, limit=20,
                                               where={"memory_type": "episodic"}))
timeit("epi.doc_store.search_memories(episodic)",
       lambda: epi.doc_store.search_memories(memory_type="episodic", limit=1000))

shutil.rmtree(bench, ignore_errors=True)
print("\n完成")
