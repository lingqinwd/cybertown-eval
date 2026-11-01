# 延迟分解：memory=on 多出来的时间花在哪

`backend/agents.py` 现在给每轮对话打 5 个阶段的时间戳，写进 `metrics_*.csv`；
`tools/run_matrix.py` 会把它们按臂汇总。

## 分解结果（GPU + 本地 embedding，n=12/臂）

| 阶段 | off | on | 差 |
|---|---:|---:|---:|
| **retrieve（检索）** | 0 | **2080** | **+2080 ms** |
| generate（生成） | 497 | 817 | +320 ms |
| affinity（好感度分析） | 640 | 653 | +13 ms |
| save（存记忆） | 0 | 0 | 0 |
| prompt 字符数 | 84 | 141 | +57 |
| 回复字符数 | 58 | 76 | +18 |

端到端倍数 3.10×，**增量几乎全部落在 `retrieve` 这一阶段**。

这直接修正了一个此前只能靠间接推断的说法：memory=on 的开销**不在生成**。
生成只多 320 ms（prompt 变长 57 字符 + 回复变长 18 字符），其余 2.08 s 全在检索。

## 那 2.08 s 不是 embedding，也不是数据量

在隔离环境里复现（`tools/diag_embedder_env.py`，服务器同款环境）：

```
embedder 类型 = LocalTransformerEmbedding        ← 本地，不是远程
  单次 encode: 12 ms
集合 cybertown_stage_local 点数 = 0              ← 一条数据都没有
  retrieve ['working']              0/0/0 ms
  retrieve ['episodic']          2055/2054/2060 ms   ← 恒定 2.05 s
  retrieve ['working','episodic'] 2101/2065/2079 ms
```

**空集合、本地 embedder、本地 Qdrant，仍然恒定 2.05 s。** 说明：

- 与"检索到几条"无关（这也解释了为什么逐轮增量是平的、第 1 轮就已 +2227 ms）；
- 与 embedding 位置无关（远程/本地都各自叠加）；
- 是一个**固定成本**，出现在 `EpisodicMemory.retrieve` → `vector_store.search_similar`。

`search_similar` 的兼容分支是"先试 `query_points()`，`AttributeError` 再退回 `search()`"。
2.05 s 这个量级像是**某个请求在超时后回退**。**最后一层没有定位到** ——
要确认需要在 `search_similar` 内部打点，或直接对空集合计时一次 `query_points()`。
本轮到此为止，如实记录为未完成。

## 已知代价

- 这段开销**每个 NPC 每轮付一次**：当前实现下，memory=on 的对话在其设备上
  至少多 2 s，与模型快慢无关。
- 在 R9700 上归档数据只多 217 ms，说明 AUP 那次的 `hello_agents`/`qdrant-client` 组合
  没有这个固定成本（AUP 用 `qdrant-client==1.9.2`，本地是 **1.15.1**）。
  这是一个可检验的推测：**换回 1.9.2 后 2 s 应该消失**。未验证。

## 复现

```powershell
# 打点版矩阵实验（任选 A/B/C 条件）
D:\Venvs\st\Scripts\python.exe tools\run_matrix.py --repeats 2 --turns 6 `
    --env EMBED_MODEL_TYPE=local `
    --env EMBED_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2 `
    --env EMBED_BASE_URL= --env EMBED_API_KEY= `
    --out experiments\matrix_stage_local.csv

# 隔离复现 2.05 s
D:\Venvs\st\Scripts\python.exe tools\diag_embedder_env.py
```

明细：`matrix_stage_local.csv`（含 `t_retrieve_ms` / `t_generate_ms` / `t_affinity_ms` /
`prompt_chars` / `reply_chars` 等列）。
