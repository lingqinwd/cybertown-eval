# 本地 2×2 复现与受控对照（含一次被推翻的结论）

归档的四组数据是**手工**跑的，既难复现也无法做重复与对照。`tools/run_matrix.py` 把这件事
自动化，本文是它跑出来的结果 —— 包括**一个先被接受、后来被推翻的结论**，因为推翻过程本身
比结论更有价值。

## 设计

| 项 | 值 |
|---|---|
| 模型 | `qwen2.5:1.5b`（Ollama Q4，0.92 GB） |
| 六轮脚本 | **与归档实验完全一致**（李四 ×2、张三 ×2、王五 ×2） |
| 顺序 | **A-B-B-A**：每个臂各有一次靠前、一次靠后，抵消时间漂移 |
| 隔离 | 每 block 独立后端进程 + 独立 `player_id` |
| 工具 | `tools/run_matrix.py`（`--env` 透传，`--repeats` 重复） |

## 最终结果（已修正）

| 条件 | n | off (ms) | on (ms) | **倍数** | retrieve |
|---|---:|---:|---:|---:|---:|
| GPU + **远程** embedding | 12 | 1147 | 2404 | **2.10×** | **1112 ms** |
| GPU + **本地** embedding | 12 | 1236 | 1386 | **1.12×** | **44 ms** |
| 归档 · R9700（参照） | 12 | 861 | 1078 | 1.25× | — |

**召回**：两组的 off 臂 0 命中、on 臂全部命中，与归档一致。

## 这个结论是怎么被推翻的（重要）

第一轮我用 `.env` 里的 `QDRANT_URL=http://localhost:6333` 跑，得到：

| 条件 | off | on | 倍数 |
|---|---:|---:|---:|
| GPU + 远程 | 1238 | 4637 | 3.75× |
| GPU + 本地 | 1131 | 3542 | 3.13× |

当时我据此写了"embedding 位置主导开销"，甚至声称 3050 上有个无法归因的 2.4 s。
**这些都是错的。**

### 分阶段计时发现了异常

给 `chat()` 打点后（见 [STAGE_TIMING.md](STAGE_TIMING.md)）：

```
              off      on
retrieve        0    2080 ms   ← 增量几乎全在这里
generate      497     817 ms
affinity      640     653 ms
```

而本地 embedding 单次只要 12 ms、集合里 0 个点 —— 检索却恒定 2.08 秒。

### 用子调用拆分钉死

`tools/bench_episodic.py` 把 `retrieve` 拆成子调用：

```
epi.embedder.encode(query)                 9/11/8 ms
epi.vector_store.search_similar          2051/2061/2071 ms   ← 就是它
epi.doc_store.search_memories(episodic)    1/0/0 ms
```

换 `qdrant-client==1.9.2`（AUP 用的版本）**依然是 2.05 s** —— 排除客户端版本。

### 根因：`localhost` 解析到 IPv6

这台机器 `localhost` 同时解析出 `::1` 与 `127.0.0.1`，而 Docker 的端口只绑了 `127.0.0.1`。
每次请求先去连 `[::1]:6333`，等超时（约 2 s）再回退到 IPv4。

把 `QDRANT_URL` 改成 `http://127.0.0.1:6333`：

```
epi.vector_store.search_similar            6/5/6 ms      ← 2051 → 6 ms
```

**一个 URL 里的 `localhost` 造成了每轮 2 秒的假开销，并被误读成"记忆系统的成本"。**

## 修正后的三条结论

### 1. 记忆开销主要取决于 embedding 在哪跑（受控对照，成立）

同一台设备、同一个模型、同一个脚本，只换 embedder：

- 远程 DashScope：每轮多 **1112 ms**，倍数 **2.10×**
- 本地 MiniLM：每轮多 **44 ms**，倍数 **1.12×**

直测：远程 **340 ms/次**（首次建连 1970 ms）、本地 **12.8 ms/次**，差约 26 倍。
1112 ms ≈ 3 次远程 embedding 调用。

**这解释了归档数据里 3.12×（云端）与 1.25×（端侧）的差距**：
不是设备快慢，而是 embedding 的位置。

### 2. 设备快慢对倍数的影响，在去掉这个 artifact 后变得很温和

本地 embedding 下，3050 上是 1.12×，AUP 的 R9700 是 1.25× —— 同一量级。
之前"设备越弱倍数越小/越大"的讨论，**在真实开销只有 44–200 ms 时基本没有讨论价值**；
倍数主要由 embedder 位置决定。

### 3. 无记忆时会编造记忆（复现）

off 臂被追问"你还记得我是谁吗"，多次给出**错误且自信**的答案：

- 「当然记得了！你是我们的用户分析团队的成员，正在设计一个…」
- 「当然记住了！你叫林峰，最近在开发一款虚拟现实社交应用…」
- 「当然记得！你最近在做的项目是关于多智能体系统的，对吧」

这三条都不是真的（玩家从未说过），其中"多智能体系统"来自系统提示词的示例。
对照组：DeepSeek 在同一问题上是「我一时对不上号了」。

## 边界

1. 模型是 **Q4 量化 + Ollama 栈**，与 AUP 的 fp16 + transformers 不同；
   **只有同一次运行内 on/off 的比值可比**，绝对值不可跨设备比较。
2. 每臂 12 个样本。召回是定性结论；延迟的置信区间偏宽。
3. "远程 embedding 每次约 340 ms"来自独立计时，未在服务端逐次打点验证是 3 次调用。
4. 修正前的数据（`matrix_*.csv`）**保留在仓库里**，作为这次翻车的证据，不要引用。

## 复现

```powershell
cd E:\graduate_student\AI\cybertown-eval
docker start helloagents-qdrant-ch15

# 关键：QDRANT_URL 用 127.0.0.1，不要用 localhost
# 本地 embedding（D 盘 venv）
D:\Venvs\st\Scripts\python.exe tools\run_matrix.py --repeats 2 --turns 6 `
    --qdrant-url http://127.0.0.1:6333 `
    --env QDRANT_URL=http://127.0.0.1:6333 `
    --env EMBED_MODEL_TYPE=local `
    --env EMBED_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2 `
    --env EMBED_BASE_URL= --env EMBED_API_KEY= `
    --out experiments\matrix_fixed_local_embed.csv

# 远程 embedding（conda 环境）
E:\Conda\envs\helloagents\python.exe tools\run_matrix.py --repeats 2 --turns 6 `
    --qdrant-url http://127.0.0.1:6333 `
    --env QDRANT_URL=http://127.0.0.1:6333 `
    --out experiments\matrix_fixed_remote_embed.csv
```

## 文件

| 文件 | 说明 |
|---|---|
| `matrix_fixed_local_embed.csv` | **修正后**，本地 embedding，倍数 1.12× |
| `matrix_fixed_remote_embed.csv` | **修正后**，远程 embedding，倍数 2.10× |
| `matrix_local_qwen1.5b.csv` 等 | 修正前（含 2 s 假开销），仅作翻车留证 |
| `matrix_stage_local.csv` | 带阶段计时的修正前数据，用来说明 2 s 落在哪 |
