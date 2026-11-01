# 延迟分解：memory=on 的时间到底花在哪

`backend/agents.py` 给每轮对话打 5 个阶段的时间戳，写进 `metrics_*.csv`；
`tools/run_matrix.py` 按臂汇总。`prompt_chars` / `reply_chars` 用来区分
"prompt 变长"与"检索变慢"。

## 修正后的分解（QDRANT_URL 已改为 127.0.0.1）

| 阶段 | 本地·GPU off | 本地·GPU on | 远程·GPU on | 本地·CPU off | 本地·CPU on |
|---|---:|---:|---:|---:|---:|
| **retrieve** | 0 | **44** | **1112** | 0 | **64** |
| generate | 581 | 675 | 660 | 5161 | 6518 |
| affinity | 640 | 645 | 609 | **11179** | **11665** |
| save | 0 | 0 | 0 | 0 | 0 |
| prompt 字符 | 84 | 147 | 140 | 84 | 141 |
| 回复字符 | 74 | 87 | 79 | 74 | 85 |

> CPU 那一列最值得注意：**好感度分析（11179 ms）比生成回复（5161 ms）还贵一倍多**。
> 每轮其实调了两次 LLM，而 CPU 的瓶颈在分析 prompt 的预处理。
> 端侧优化应该先削减分析用的 prompt。

结论：
- **本地 embedding 下，检索几乎不花钱（44 ms）**，总开销只有 +150 ms（1.12×）。
- **远程 embedding 下，检索 1112 ms**，成为主要开销（2.10×）。
- 生成阶段只多 ~90–150 ms（prompt 变长 56 字符 + 回复变长 13 字符）。
- 好感度分析、存记忆都不受记忆开关影响。

## 这份分解的价值：它推翻了一个 3 倍假象

在修正 `QDRANT_URL` 之前，同一套打点给出的是：

| 阶段 | off | on | 差 |
|---|---:|---:|---:|
| **retrieve** | 0 | **2080** | **+2080** |
| generate | 497 | 817 | +320 |

当时"多出来的 2.4 秒几乎全在检索"看起来已经很明确了，但**检索里那 2.08 秒并不是记忆系统的成本**。

子调用拆分（`tools/bench_episodic.py`，空集合、本地 embedder）：

```
epi.embedder.encode(query)                 9/11/8 ms
epi.vector_store.search_similar          2051/2061/2071 ms
epi.doc_store.search_memories(episodic)    1/0/0 ms
```

根因：`QDRANT_URL=http://localhost:6333`，`localhost` 先解析到 IPv6 `::1`，而 Docker 只绑
`127.0.0.1` —— 每次连接等约 2 s 超时后回退。改成 `http://127.0.0.1:6333` 后：

```
epi.vector_store.search_similar            6/5/6 ms
```

**每轮 2 秒的"记忆开销"是一个 URL 写法造成的。** 顺带排除了客户端版本因素：
换成 AUP 用的 `qdrant-client==1.9.2` 依然是 2.05 s。

## 教训

1. **端到端拆到"检索"还不够**，要拆到子调用。否则会把网络配置的锅算到记忆系统头上。
2. 恒定值（而不是随数据量增长）本身就是可疑信号 —— 真正的检索开销应该随条目数变化。
3. `localhost` 在双栈机器上不是一个可靠的"本地"地址；配置里应该写 `127.0.0.1`。
   已写入 `docs/TROUBLESHOOTING.md` 坑 12。

## 复现

```powershell
docker start helloagents-qdrant-ch15

# 子调用拆分（本地 embedding 解释器）
D:\Venvs\st\Scripts\python.exe tools\bench_episodic.py

# 打点版矩阵实验
D:\Venvs\st\Scripts\python.exe tools\run_matrix.py --repeats 2 --turns 6 `
    --qdrant-url http://127.0.0.1:6333 `
    --env QDRANT_URL=http://127.0.0.1:6333 `
    --env EMBED_MODEL_TYPE=local `
    --env EMBED_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2 `
    --env EMBED_BASE_URL= --env EMBED_API_KEY= `
    --out experiments\matrix_fixed_local_embed.csv
```
