"""测一次远程 embedding API 的耗时（不打印任何密钥）。

用途：本地跑 matrix 时 memory=on 每轮多出约 3.4 s，怀疑是远程 embedding 调用。
把这个数字量出来，就能判断"记忆开销大"到底是因为生成变长，还是因为多了一次网络往返。
"""
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / "backend" / ".env")

import os  # noqa: E402

from openai import OpenAI  # noqa: E402

base = os.getenv("EMBED_BASE_URL", "")
key = os.getenv("EMBED_API_KEY", "") or os.getenv("LLM_API_KEY", "")
model = os.getenv("EMBED_MODEL_NAME", "text-embedding-v3")
provider = os.getenv("EMBED_MODEL_TYPE", "")

print(f"EMBED_MODEL_TYPE = {provider}")
print(f"EMBED_BASE_URL   = {base}")
print(f"EMBED_MODEL_NAME = {model}")
print(f"EMBED_API_KEY    = {'已配置(' + str(len(key)) + ' 字符)' if key else '缺失'}")

if not base or not key:
    raise SystemExit("缺 EMBED_BASE_URL 或 EMBED_API_KEY，无法测量")

client = OpenAI(api_key=key, base_url=base, timeout=60)

texts = ["你好，我叫小林，我正在做一个赛博小镇课程项目。"]
times = []
for i in range(3):
    started = time.perf_counter()
    resp = client.embeddings.create(model=model, input=texts)
    elapsed = (time.perf_counter() - started) * 1000
    times.append(elapsed)
    dim = len(resp.data[0].embedding) if resp.data else -1
    print(f"第 {i + 1} 次: {elapsed:7.0f} ms   维度 {dim}")

print(f"\n平均 {sum(times) / len(times):.0f} ms（首次含建连，取后两次更接近稳态: {sum(times[1:]) / len(times[1:]):.0f} ms）")
