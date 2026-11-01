# 延迟分解：一轮对话的时间花在哪

`backend/agents.py` 给每轮对话打 5 个阶段的时间戳，写进 `metrics_*.csv`；
`tools/run_matrix.py` 按臂汇总。`prompt_chars` / `reply_chars` 用来区分
「prompt 变长」与「检索变慢」。

## 分解结果（均值，ms）

| 阶段 | 本地·GPU off | 本地·GPU on | 远程·GPU on | 本地·CPU off | 本地·CPU on |
|---|---:|---:|---:|---:|---:|
| **retrieve** | 0 | **44** | **1112** | 0 | **64** |
| generate | 581 | 675 | 660 | 5161 | 6518 |
| affinity | 640 | 645 | 609 | **11179** | **11665** |
| save | 0 | 0 | 0 | 0 | 0 |
| prompt 字符 | 84 | 147 | 140 | 84 | 141 |
| 回复字符 | 74 | 87 | 79 | 74 | 85 |

## 三个读数

### 1. 本地 embedding：记忆几乎不花钱

retrieve 从 0 到 **44 ms**，总增量只有 **+150 ms**（1.12×）。生成多 94 ms，
只是 prompt 长了 63 个字符。

### 2. 远程 embedding：开销几乎全在检索

retrieve **1112 ms**，占 2.10× 里绝大部分。生成部分只多 79 ms。
**「记忆贵」在这里等价于「每轮多了几次远程 embedding 调用」**（1112 ÷ 340 ≈ 3 次）。

### 3. CPU：最贵的既不是检索也不是生成，而是好感度分析

**affinity 11179 ms，比 generate 5161 ms 还贵一倍多。**

原因在结构上：每轮其实调了**两次** LLM —— 一次生成 NPC 回复，一次把玩家消息和回复
一起喂进去判断好感度。第二次的 prompt 里塞了整段对话，而 CPU 的瓶颈在 **prompt 预处理**
（不是逐字生成），所以它反而更贵。

> **可落地的结论**：端侧优化应该先削减分析用的 prompt（缩短分析器系统提示词、
> 只传最近 1–2 轮、或把分析换成规则/小模型），而不是先优化生成。
> 这也说明把端侧开销全部归给「更长的回复」是不完整的。

## 为什么值得做阶段拆分

端到端只看到「3 倍」是不够的：拆到阶段才知道差异在 `retrieve`；
拆到子调用（`tools/bench_episodic.py`：embed / vector_search / doc_store 三段）才能确认
`retrieve` 里面到底是哪一段。

一个提醒：本机第一次搭这套环境时，`retrieve` 恒定 2 秒且与数据量无关，
最后查明是 `QDRANT_URL` 写了 `localhost`（双栈解析先连 IPv6）导致，与记忆系统无关。
配置已改为 `127.0.0.1`。**恒定而不随数据量变化的耗时，本身就是可疑信号** ——
真正的检索开销应该随条目数变化。

## 复现

```powershell
docker start helloagents-qdrant-ch15

# 子调用拆分
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
