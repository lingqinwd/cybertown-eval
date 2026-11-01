"""用「服务器完全相同」的环境构造 embedder，确认它到底是本地还是远程。

按 backend/config.py 的加载顺序：先 load_dotenv(backend/.env)，再叠加 run_matrix 的 --env，
然后构造 embedder 并计时一次 encode。
"""
import os
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / "backend" / ".env")

# run_matrix 传进去的四个覆盖
os.environ["EMBED_MODEL_TYPE"] = "local"
os.environ["EMBED_MODEL_NAME"] = "sentence-transformers/all-MiniLM-L6-v2"
os.environ["EMBED_BASE_URL"] = ""
os.environ["EMBED_API_KEY"] = ""
os.environ.setdefault("HF_HOME", r"D:\HFCache")

print("生效的环境变量：")
for k in ("EMBED_MODEL_TYPE", "EMBED_MODEL_NAME", "EMBED_BASE_URL", "EMBED_API_KEY"):
    v = os.environ.get(k, "<未设置>")
    print(f"  {k:18} = {v!r}")

from hello_agents.memory.embedding import get_text_embedder  # noqa: E402

t0 = time.perf_counter()
emb = get_text_embedder()
print(f"\nembedder 类型 = {type(emb).__name__}  (首次含加载 {time.perf_counter() - t0:.2f}s)")

for i in range(3):
    t0 = time.perf_counter()
    emb.encode(["你还记得我的名字，以及我正在做什么项目吗？"])
    print(f"  第 {i + 1} 次 encode: {(time.perf_counter() - t0) * 1000:.0f} ms")

# 顺带看 Qdrant 集合规模
try:
    from hello_agents.memory.storage.qdrant_store import QdrantConnectionManager

    client = QdrantConnectionManager.get_instance(
        url=os.environ.get("QDRANT_URL", "http://localhost:6333"),
        collection_name="cybertown_stage_local",
    )
    info = client.client.get_collection("cybertown_stage_local")
    print(f"\n集合 cybertown_stage_local 点数 = {info.points_count}")
except Exception as exc:  # noqa: BLE001
    print(f"\n查集合失败: {exc}")

# ---- 追加：看 EpisodicMemory 内部用的是哪个 embedder，并计时 ----
print("\n=== EpisodicMemory 内部 embedder ===")
try:
    from hello_agents.memory import MemoryConfig, MemoryManager
    import shutil, time as _t

    bench = REPO / "backend" / "memory_data" / "_diag"
    shutil.rmtree(bench, ignore_errors=True)
    bench.mkdir(parents=True, exist_ok=True)
    cfg = MemoryConfig(storage_path=str(bench), working_memory_capacity=10, working_memory_tokens=2000)
    mm = MemoryManager(config=cfg, user_id="diag::p", enable_working=True,
                       enable_episodic=True, enable_semantic=False, enable_perceptual=False)
    epi = mm.memory_types.get("episodic")
    for attr in ("embedder", "_embedder", "embedding_model"):
        if hasattr(epi, attr):
            print(f"  episodic.{attr} = {type(getattr(epi, attr)).__name__}")
    for types in (["working"], ["episodic"], ["working", "episodic"]):
        ts = []
        for _ in range(3):
            t0 = _t.perf_counter()
            mm.retrieve_memories(query="你还记得我的名字吗？", memory_types=types,
                                 limit=5, min_importance=0.3)
            ts.append((_t.perf_counter() - t0) * 1000)
        print(f"  retrieve {str(types):<26} {'/'.join(f'{t:.0f}' for t in ts)} ms")
    shutil.rmtree(bench, ignore_errors=True)
except Exception as exc:
    import traceback
    traceback.print_exc()