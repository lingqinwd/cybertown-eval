# 本地 2×2 复现与受控对照

归档的四组数据是**手工**跑的，既难复现也无法做重复与对照。`tools/run_matrix.py` 把这件事
自动化，本文是它跑出来的三组受控实验。

## 设计

| 项 | 值 |
|---|---|
| 模型 | `qwen2.5:1.5b`（Ollama Q4，0.92 GB） |
| 六轮脚本 | **与归档实验完全一致**（李四 ×2、张三 ×2、王五 ×2） |
| 顺序 | **A-B-B-A**：每个臂各有一次靠前、一次靠后，抵消时间漂移 |
| 隔离 | 每 block 独立后端进程 + 独立 `player_id` |
| 工具 | `tools/run_matrix.py`（`--env` 透传，`--repeats` 重复） |

三组条件，每次只变一个因素：

| 组 | 推理 | embedding | 重复 |
|---|---|---|---|
| A | RTX 3050 Laptop 4 GB | **远程** DashScope `text-embedding-v3` | 2 |
| B | RTX 3050 Laptop 4 GB | **本地** MiniLM（384 维） | 2 |
| C | **CPU**（`CUDA_VISIBLE_DEVICES=-1`） | **本地** MiniLM | 2 |

## 结果

| 组 | 推理 | embedding | n | off (ms) | on (ms) | **倍数** | retrieve |
|---|---|---|---:|---:|---:|---:|---:|
| A | GPU | **远程** DashScope | 12 | 1147 | 2404 | **2.10×** | **1112 ms** |
| B | GPU | **本地** MiniLM | 12 | 1236 | 1386 | **1.12×** | **44 ms** |
| C | **CPU** | **本地** MiniLM | 12 | 17963 | 20105 | **1.12×** | **64 ms** |
| — | R9700（归档参照） | 本地 | 12 | 861 | 1078 | 1.25× | — |

**召回**：三组的 off 臂 0 命中、on 臂全部命中，与归档一致。

## 四条结论

### 1. 记忆开销主要由 embedding 的位置决定（受控对照）

同一台设备、同一个模型、同一个脚本，只换 embedder：

- 远程 DashScope：每轮多 **1112 ms**，**2.10×**
- 本地 MiniLM：每轮多 **44 ms**，**1.12×**

直测：远程 **340 ms/次**（首次建连 1970 ms）、本地 **12.8 ms/次**，差约 26 倍。
1112 ms ≈ 3 次远程调用。

**这解释了归档数据里 3.12×（云端）与 1.25×（端侧）的差距** —— 不是设备快慢，
而是 embedding 的位置。

### 2. 绝对开销随设备变慢而变大，但倍数基本不动

本地 embedding 下，**GPU 1.12×、CPU 1.12×**，R9700 是 1.25× —— 同一量级。

| 设备 | 基线 off | 绝对增量 | 倍数 |
|---|---:|---:|---:|
| R9700（归档） | 861 | +217 | 1.25× |
| RTX 3050 | 1236 | +150 | 1.12× |
| CPU | 17963 | +2142 | 1.12× |

绝对值差了 14 倍，倍数几乎相同 —— 因为基线也同比变大。

### 3. CPU 上最贵的一环不是生成，是**好感度分析**

| 阶段 | off | on |
|---|---:|---:|
| generate | 5161 | 6518 |
| **affinity（好感度分析）** | **11179** | **11665** |

**每轮其实调了两次 LLM**：一次生成 NPC 回复，一次分析该不该改好感度。
CPU 上第二次比第一次**还贵一倍多**，因为它的 prompt 要把整段对话塞进去，
而 CPU 的瓶颈在 prompt 预处理。

> 对端侧优化的直接含义：**先削减分析用的 prompt，比优化生成更快见效。**
> 这也说明把端侧开销全部归给「更长的回复」是不完整的。

### 4. 无记忆时会编造记忆（复现）

off 臂被追问"你还记得我是谁吗"，多次给出**错误且自信**的答案：

- 「当然记得了！你是我们的用户分析团队的成员，正在设计一个…」
- 「当然记住了！你叫林峰，最近在开发一款虚拟现实社交应用…」
- 「当然记得！你最近在做的项目是关于多智能体系统的，对吧」

这些都从未发生过，其中"多智能体系统"来自系统提示词的示例。
对照组：DeepSeek 在同一问题上是「我一时对不上号了」。

## 边界

1. 模型是 **Q4 量化 + Ollama 栈**，与 AUP 的 fp16 + transformers 不同；
   **只有同一次运行内 on/off 的比值可比**，绝对值不可跨设备比较。
2. 每臂 12 个样本。召回是定性结论；延迟的置信区间偏宽。
3. "远程 embedding 每次约 340 ms"来自独立计时，未在服务端逐次打点验证是 3 次调用。

> **关于 `matrix_local_*.csv` / `matrix_stage_local.csv` / `matrix_cpu_local_embed.csv`：
> 这几份是早期运行的数据，本机 `localhost` 解析到 IPv6 导致每轮多约 2 秒（配置已改为
> `127.0.0.1`）。保留在仓库仅为留档，**引用请用 `matrix_fixed_*.csv`**。

## 复现

```powershell
cd E:\graduate_student\AI\cybertown-eval
docker start helloagents-qdrant-ch15

# B：本地 embedding（D 盘 venv，装了 torch + sentence-transformers）
D:\Venvs\st\Scripts\python.exe tools\run_matrix.py --repeats 2 --turns 6 `
    --qdrant-url http://127.0.0.1:6333 `
    --env QDRANT_URL=http://127.0.0.1:6333 `
    --env EMBED_MODEL_TYPE=local `
    --env EMBED_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2 `
    --env EMBED_BASE_URL= --env EMBED_API_KEY= `
    --out experiments\matrix_fixed_local_embed.csv

# A：远程 embedding
E:\Conda\envs\helloagents\python.exe tools\run_matrix.py --repeats 2 --turns 6 `
    --qdrant-url http://127.0.0.1:6333 `
    --env QDRANT_URL=http://127.0.0.1:6333 `
    --out experiments\matrix_fixed_remote_embed.csv

# C：CPU 推理（先把 ollama 的 GPU 屏蔽掉）
#   Stop-Process ollama; $env:CUDA_VISIBLE_DEVICES='-1'; ollama serve
#   确认 /api/ps 里 size_vram 为 0 再跑
```

## 文件

| 文件 | 说明 |
|---|---|
| `matrix_fixed_local_embed.csv` | **B**，本地 embedding，1.12× |
| `matrix_fixed_remote_embed.csv` | **A**，远程 embedding，2.10× |
| `matrix_fixed_cpu_local_embed.csv` | **C**，CPU + 本地 embedding，1.12× |
| `matrix_*.csv`（其余） | 早期留档，不要引用（见上方边界说明） |
