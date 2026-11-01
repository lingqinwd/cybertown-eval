# 本地 2×2 复现（A-B-B-A 交错）

归档的四组数据是**手工**跑的（Godot 点对话 / 浏览器控制台逐条发），既难复现也无法做重复。
`tools/run_matrix.py` 把这件事自动化，本文是第一次用它跑出来的结果。

## 设计

| 项 | 值 |
|---|---|
| 模型 | `qwen2.5:1.5b`（Ollama Q4，0.92 GB） |
| 设备 | 本机 RTX 3050 Laptop，4 GB 显存 |
| 六轮脚本 | **与归档实验完全一致**（李四 ×2、张三 ×2、王五 ×2） |
| 顺序 | **off → on → on → off**（A-B-B-A），每个臂各有一次靠前、一次靠后，抵消时间漂移 |
| 隔离 | 每个 block 独立后端进程 + 独立 `player_id`，记忆按 (NPC, 玩家) 天然隔离 |
| 记忆后端 | 本地 Qdrant 容器 `helloagents-qdrant-ch15`，集合 `cybertown_matrix` |
| embedding | `.env` 的 `dashscope/text-embedding-v3`（**远程**） |

共 4 个 block × 6 轮 = **24 次对话**，全程约 3 分钟、零费用。

## 结果

| 记忆 | 样本 | 均值 ms | 中位 ms | 召回总数 |
|---|---:|---:|---:|---:|
| off | 12 | **1238** | 1123 | 0 |
| on | 12 | **4637** | 4650 | 12 |

**记忆开销倍数：均值 3.75×，中位 4.14×**
**追问事实命中：on 2/2，off 0/2**

明细：`matrix_local_qwen1.5b.csv`；控制台输出：`matrix_local_qwen1.5b.txt`
（`tools/run_matrix.py --repeats 2 --turns 6`）

## 三个发现

### 1. 召回结论复现

服务端 `memory_recall_count` 在 off 组 12 轮全为 0，on 组每轮的追问轮都是 2；行为上
李四在 on 组两次都准确说出"小林 / 赛博小镇"，off 组两次都说不出。**与归档数据（0% → 100%）一致。**

### 2. 幻觉式回忆复现

off 组被追问"你还记得我的名字吗"，两次的真实回复是：

- 「当然记得了！你是在为**"多智能体系统"**项目忙碌吧」
- 「记得你哦！你在做关于**多智能体系统**的项目，对吧？」

这与归档里 Qwen 的表现**同型**：不是承认遗忘，而是把系统提示词里的示例当作记忆。
对照组是 DeepSeek 在同一问题上的「我一时对不上号了」。**这条在第二台设备上复现了。**

### 3. 延迟倍数与归档不同，而且方向相反

| 组 | embedding | Qdrant | on/off 倍数 |
|---|---|---|---:|
| DeepSeek（归档） | **远程 DashScope** | 本地 docker | 3.12× |
| 本地 Qwen（本次） | **远程 DashScope** | 本地 docker | **3.75×** |
| AUP Qwen（归档） | **本地 MiniLM** | 本地 | 1.25× |

## 我原来的预测错了

跑之前我预测：RTX 3050 比 R9700 弱得多 → 生成占比更高 → 记忆开销倍数应该**更小**（≈1.1×）。

**实测是反过来，而且是 3.75×。** 原因不是设备强弱，而是 **embedding 在哪跑**：

- 本次的 memory=on 每轮固定多出约 **3.4 s**，而且**即使 recall=0（每块第 1 轮）也一样**。
  说明这段开销与"检索到几条"无关，是每轮固定的一次远程调用。
- 直接测该接口：**稳态 0.34 s，首次建连 1.97 s**（`tools/measure_embedding.py`）。
  如果每轮有 1–2 次调用且未复用连接，就与 3.4 s 对得上。
- DeepSeek 组也用同一个远程 embedding，所以它的 3.12× 很可能同源；
  而 AUP 的 Qwen 组用的是本地 MiniLM，没有这次网络往返，才有 1.25×。

**这个解释比原报告里的"开销在生成长度"更完整**：AUP 那次的正向归因（端侧多出来的 216 ms
来自更长的输出）仍然成立，但它只是 1.25× 里的 **216 ms**；一旦 embedding 走远程，
它会直接主导整个倍数。

## 边界（必须说清）

1. **缺一个对照**：同一台设备、只把 embedder 换成本地（`sentence-transformers` + torch，
   本机未装）。补上它才能把"embedding 位置"从强推断变成受控结论。这是唯一缺的一环。
2. 每臂 12 个样本，仍偏小；不过召回是定性差异，不依赖样本量。
3. `qwen2.5:1.5b` 是 **Q4 量化 + Ollama 服务栈**，与 AUP 的 fp16 + transformers 不是同一实现，
   绝对值不可与归档数字直接比较，**只有"同一次运行内 on/off 的比值"是可比的**。
4. 服务端 `latency_ms` 与客户端实测在本轮几乎一致（同一台机器），归档数据里两者相差一个数量级
   （网络跳数），不能混用。

## 复现

```powershell
cd E:\graduate_student\AI\cybertown-eval
docker start helloagents-qdrant-ch15          # memory=on 需要

# 计划预览
E:\Conda\envs\helloagents\python.exe tools\run_matrix.py --repeats 2 --dry-run

# 正式跑（约 3 分钟，零费用）
E:\Conda\envs\helloagents\python.exe tools\run_matrix.py --repeats 2 --turns 6 `
    --out experiments\matrix_local_qwen1.5b.csv

# 单次远程 embedding 耗时
E:\Conda\envs\helloagents\python.exe tools\measure_embedding.py
```
