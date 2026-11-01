# 本地 2×2 复现与受控对照（A / B / C 三组）

归档的四组数据是**手工**跑的（Godot 点对话 / 浏览器控制台逐条发），既难复现也无法做重复与
对照。`tools/run_matrix.py` 把这件事自动化，本文是用它跑出来的三组实验。

## 设计

| 项 | 值 |
|---|---|
| 模型 | `qwen2.5:1.5b`（Ollama Q4，0.92 GB） |
| 六轮脚本 | **与归档实验完全一致**（李四 ×2、张三 ×2、王五 ×2） |
| 顺序 | **A-B-B-A**：每个臂各有一次靠前、一次靠后，抵消时间漂移 |
| 隔离 | 每个 block 独立后端进程 + 独立 `player_id` |
| 记忆后端 | 本地 Qdrant 容器，每条件独立集合 |
| 工具 | `tools/run_matrix.py`（`--env` 透传配置，`--repeats` 控制重复） |

三组条件，只变一个因素：

| 组 | 推理设备 | embedding | 重复 |
|---|---|---|---|
| A | RTX 3050 Laptop 4 GB | **远程** DashScope `text-embedding-v3` | 2 |
| B | RTX 3050 Laptop 4 GB | **本地** MiniLM（`sentence-transformers`，384 维） | 4 |
| C | **CPU**（`CUDA_VISIBLE_DEVICES=-1`） | **本地** MiniLM | 2 |

## 结果

| 条件 | n | off (ms) | on (ms) | **倍数** | 绝对增量 |
|---|---:|---:|---:|---:|---:|
| A · GPU + 远程 embedding | 12 | 1238 | 4637 | **3.75×** | +3399 ms |
| B · GPU + 本地 embedding | 24 | 1131 | 3542 | **3.13×** | +2411 ms |
| C · CPU + 本地 embedding | 12 | 15879 | 19506 | **1.23×** | +3626 ms |
| — 归档 · R9700（参照） | 12 | 861 | 1078 | 1.25× | +217 ms |

明细：`matrix_local_qwen1.5b.csv`（A）、`matrix_gpu_local_embed_r4.csv`（B）、
`matrix_cpu_local_embed.csv`（C）；另有 `matrix_local_embed.csv` 是 B 的 2 次子集（3.12×），
用于确认重复次数不影响比值。

**召回**：三组都是 off 组 0 命中、on 组全部命中（服务端 `memory_recall_count` 与行为一致）。

**漂移控制**（B 组，同臂 4 个 block 的均值）：

| 臂 | 第 1 次 | 第 2 次 | 第 3 次 | 第 4 次 |
|---|---:|---:|---:|---:|
| off | 1128 | 1159 | 1173 | 1063 |
| on | 3568 | 3560 | 3535 | 3503 |

臂内极差 ≤ 110 ms（约 10%），无单调趋势 → **A-B-B-A 确实把时间漂移压住了**。

## 三条结论

### 1. 远程 vs 本地 embedding：受控对照，成立

同一台设备、同一个模型、同一个脚本，**只换 embedding 的位置**：

- 远程 DashScope：+3399 ms/轮，3.75×
- 本地 MiniLM：+2411 ms/轮，3.13×

直测该接口：稳态 **340 ms**、首次建连 **1970 ms**（`tools/measure_embedding.py`）；
本地 MiniLM 单次 **12.8 ms**（`tools/check_local_embedding.py`）。差约 26 倍，与 ~1 s 的差额一致。

**这是本文唯一一处严格受控的因果证据。**

### 2. 设备快慢会改变倍数，但不是单调的

| 设备 | 基线 off | 绝对增量 | 倍数 |
|---|---:|---:|---:|
| R9700（归档） | 861 | +217 | 1.25× |
| RTX 3050 | 1131 | +2411 | 3.13× |
| CPU | 15879 | +3626 | **1.23×** |

我之前预测"设备越弱 → 倍数越小"。**在 CPU 上成立（1.23× ≈ 归档的 1.25×），在 3050 上完全不成立。**

机制解释（**部分为推断**）：记忆带来的开销近似是**加性固定成本**（更长的 prompt、
额外的 embed/检索/写库），倍数 ≈ 1 + Δ/基线。CPU 上基线巨大（15.9 s），固定的 3.6 s
被稀释成 1.23×；R9700 上 Δ 本身就极小（217 ms），所以也只有 1.25×。
**3050 夹在中间却反而最大** —— 3.13× 的 2.4 s 增量用"加性成本被稀释"解释不了。

### 3. 3050 上那 2.4 s 的增量，目前**无法归因**

已经排除的：

- **不是上下文变长**：逐轮增量恒定（第 1 轮还没有任何记忆，Δ 就已 2227 ms），无随轮次增长趋势。
- **不是多调了 LLM**：`MemoryManager.add_memory` / `retrieve_memories` 里没有 LLM 调用。
- **不是检索到几条**：recall=0 与 recall=2 的轮次增量几乎相同。

最可疑的是 **4 GB 显存的压力**：memory=on 时 prompt 更长，可能在 4 GB 卡上触发模型重载或
上下文裁剪，从而产生秒级抖动。但这只是**假设，未验证**。要验证需要读 Ollama 的
`/api/ps` 与加载日志配合逐轮打点。

## 边界

1. `qwen2.5:1.5b` 是 **Q4 量化 + Ollama 栈**，与 AUP 的 fp16 + transformers 不是同一实现；
   绝对值不可与归档数字直接比较，**只有同一运行内 on/off 的比值可比**。
2. 每臂 12–24 个样本；召回复现是定性结论，不依赖样本量，但延迟的置信区间仍然偏宽。
3. C 组的 CPU 推理是 Ollama 的 CPU 后端（约 40 tok/s），不是 AUP 的 ROCm 路径。
4. 两处环境陷阱（远程 embedding 参数污染本地分支、回退链复用模型名）已写入
   `docs/TROUBLESHOOTING.md` 坑 9 / 坑 10 —— 不踩过这两步，本地 embedding 根本起不来
   （会报"所有嵌入模型都不可用"）。

## 复现

```powershell
cd E:\graduate_student\AI\cybertown-eval
docker start helloagents-qdrant-ch15

# A：远程 embedding（默认）
E:\Conda\envs\helloagents\python.exe tools\run_matrix.py --repeats 2 --turns 6 `
    --out experiments\matrix_local_qwen1.5b.csv

# B：本地 embedding（解释器换成装了 torch+sentence-transformers 的 D 盘 venv）
D:\Venvs\st\Scripts\python.exe tools\run_matrix.py --repeats 4 --turns 6 `
    --env EMBED_MODEL_TYPE=local `
    --env EMBED_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2 `
    --env EMBED_BASE_URL= --env EMBED_API_KEY= `
    --env HF_HOME=D:\HFCache --env HF_ENDPOINT=https://hf-mirror.com `
    --out experiments\matrix_gpu_local_embed_r4.csv

# C：CPU 推理（先把 ollama 的 GPU 屏蔽掉）
#   Stop-Process ollama; $env:CUDA_VISIBLE_DEVICES='-1'; ollama serve
#   确认 /api/ps 里 size_vram 为 0 再跑
```

> 注意：`--env EMBED_BASE_URL=` 这种"传空值"是必须的。见 TROUBLESHOOTING 坑 9。
