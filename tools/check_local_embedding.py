"""验证 hello_agents 能用本地 embedding（不发远程请求）。

用 D 盘 venv 的 python 跑：
    D:\\Venvs\\st\\Scripts\\python.exe tools\\check_local_embedding.py
"""
import os
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / "backend" / ".env")

# 覆盖成"本地 MiniLM"，并把模型缓存放到 D 盘
os.environ["EMBED_MODEL_TYPE"] = "local"
os.environ["EMBED_MODEL_NAME"] = "all-MiniLM-L6-v2"
os.environ.setdefault("HF_HOME", r"D:\HFCache")
os.environ.pop("EMBED_BASE_URL", None)   # 确保不会走 REST 分支
os.environ.pop("EMBED_API_KEY", None)

print("EMBED_MODEL_TYPE =", os.environ["EMBED_MODEL_TYPE"])
print("EMBED_MODEL_NAME =", os.environ["EMBED_MODEL_NAME"])
print("HF_HOME          =", os.environ["HF_HOME"])

from hello_agents.memory.embedding import get_text_embedder  # noqa: E402

started = time.perf_counter()
embedder = get_text_embedder()
load_ms = (time.perf_counter() - started) * 1000
print(f"\nembedder 类型: {type(embedder).__name__}   初始化(含下载) {load_ms:.0f} ms")

texts = ["你好，我叫小林，我正在做一个赛博小镇课程项目。", "你还记得我的名字吗？"]
times = []
for i in range(3):
    t0 = time.perf_counter()
    vecs = embedder.encode(texts)
    times.append((time.perf_counter() - t0) * 1000)

first = vecs[0]
dim = len(first) if hasattr(first, "__len__") else -1
print(f"编码 2 条文本: {times[0]:.0f} / {times[1]:.0f} / {times[2]:.0f} ms   维度 {dim}")
print(f"稳态单次约 {sum(times[1:]) / 2:.1f} ms")
print("\n[OK] 本地 embedding 可用" if dim > 0 else "\n[FAIL] 编码结果为空")
