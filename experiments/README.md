# 实验数据说明

四组 2×2 消融(模型 × 记忆),每组 6 轮固定脚本、零请求失败。所有延迟单位为毫秒。

## 文件清单

| 文件 | 组 | 采集点 | 内容 |
|---|---|---|---|
| `deepseek_memory_off_with_reply.csv` | A 云端·无记忆 | Godot 客户端 | 逐轮 `client_latency_ms`、`query`、`reply` 原文 |
| `deepseek_memory_on_with_reply.csv` | B 云端·有记忆 | Godot 客户端 | 同上 |
| `memory_off_screenshot_results.csv` | A | Godot 客户端 | 原始延迟记录(截图转录,无 reply 列) |
| `memory_on_screenshot_results.csv` | B | Godot 客户端 | 同上 |
| `aup_qwen_memory_off_metrics.csv` | C 端侧·无记忆 | 后端 | **服务端耗时**、`memory_recall_count`、好感度前后值 |
| `aup_qwen_memory_on_metrics.csv` | D 端侧·有记忆 | 后端 | 同上 |
| `aup_qwen_memory_on_dialogue.log` | D | 后端 | 逐轮对话、检索到的记忆原文、好感度变化原因 |
| `results_template.csv` | — | — | 空白模板 |
| `matrix_local_qwen1.5b.csv` | 本地复现（off/on × 2 次） | 服务端 | A-B-B-A 交错 24 轮的客户端/服务端延迟、召回数、回复原文 |
| `matrix_local_qwen1.5b.txt` | 同上 | 控制台 | 逐轮明细与汇总（倍数 3.75×） |
| `MATRIX_REPLICATION.md` | 同上 | — | **A/B/C 三组受控对照的设计、结果、归因与边界** |
| `matrix_local_embed.csv` | A 的 2 次子集（本地 embedding） | 服务端 | 比值 3.12×，用于确认重复次数不影响结果 |
| `matrix_gpu_local_embed_r4.csv` | B：GPU + 本地 embedding，4 次 | 服务端 | 48 轮，比值 3.13× |
| `matrix_cpu_local_embed.csv` | C：CPU + 本地 embedding，2 次 | 服务端 | 24 轮，比值 1.23×（**含 2 s 假开销，仅供翻车留证**） |
| `matrix_fixed_local_embed.csv` | **修正后**：GPU + 本地 embedding | 服务端 | 倍数 **1.12×**，retrieve 44 ms |
| `matrix_fixed_remote_embed.csv` | **修正后**：GPU + 远程 embedding | 服务端 | 倍数 **2.10×**，retrieve 1112 ms |
| `STAGE_TIMING.md` | — | — | **分阶段计时、2 s 假开销的定位过程与教训** |

> 端侧(C/D)的**客户端端到端延迟**单独保存在 `.turns.csv` 中,由浏览器控制台脚本导出,未纳入本仓库。如需完整重跑,脚本思路见 [../docs/EXPERIMENT_RESULTS.md](../docs/EXPERIMENT_RESULTS.md) §1。

## 两种延迟口径,不可混用

| 口径 | 含义 | 适用范围 |
|---|---|---|
| **服务端耗时** | 后端收到请求到返回,不含网络 | C/D 组主指标,排除网络抖动 |
| **客户端端到端** | 客户端 → 网络 → 后端 → 模型 | A/B 组唯一可得口径;跨模型比较时必须统一用它 |

端侧组曾观测到一次 **876 ms 的浏览器/代理抖动**(无记忆组第 2 轮,服务端其实只用了 695 ms)。因此端侧延迟以服务端耗时为准;若必须用客户端数据,应剔除该轮后报告 1.22 倍开销。详见报告 §2.3。

## 几个容易读错的字段

| 字段 | 陷阱 |
|---|---|
| `recall_name` / `recall_project` | 关键词匹配,**存在回声假阳性**。第 1 轮的姓名、第 4 轮的「赛博小镇」都来自当轮提问本身,不能计为记忆召回。真实判据只有第 2 轮人工核对。 |
| `fact_recall_success` | 只在第 2 轮(追问轮)有值,其余为空是正常的 |
| `timestamp` | 在所有 metrics 文件中均为空 —— logger 未写入该字段 |
| `memory_recall_count` | 仅 C/D 组可得。逐轮应为 `0, 2, 0, 2, 0, 2`,与 `dialogue.log` 的「检索到N条」完全一致 |

## 数据可信度

C/D 组有三份独立记录互相印证:

1. 浏览器导出的逐轮延迟与回复原文
2. 服务端 `metrics.csv` 的耗时与召回数
3. `dialogue.log` 的检索条数、记忆原文、好感度轨迹

三者在 `memory_recall_count`、好感度变化(50→56、56→61 …)和六轮回复原文上完全吻合。

A/B 组的 `reply` 列为截图 OCR 转录,已通过**双重校验**:逐轮耗时与原始 CSV 完全一致(12/12)、`query` 逐字一致(12/12)。原始截图未入库,如需复核请向作者索取。
