# CyberTown-EdgeCloud｜赛博小镇：多智能体叙事系统的可治理性设计

> **课程报告标题**：赛博小镇 —— 多智能体叙事系统的可治理性设计（工程实践 B 自命题型）
> **仓库名 `cybertown-eval` 保留**：它承载的主线是「评测」——四组对照、可重复场景、A/B 消融。

基于 Datawhale HelloAgents 第 15 章赛博小镇。保留原始 Godot 4.5.2 像素办公室、玩家移动、NPC 巡逻与 E 键交互，在这套可交互原型上做两条主线：

| 主线 | 要回答的问题 | 一句话结论 | 证据 |
|---|---|---|---|
| **① 端云评测** | 长期记忆能提升跨轮一致性吗？代价多大？ | 召回 **0%→100%**；开销云端 **3.12×**、端侧 **1.25×** | [EXPERIMENT_RESULTS](docs/EXPERIMENT_RESULTS.md) |
| **② 四层治理** | 状态主权能否从模型拿回后端？ | 15 次提议中**越权采纳 0 次**（3 次合法接任务被放行），四个场景判据 **4/4** 通过 | [AB_RESULTS](experiments/AB_RESULTS.md) |

**从哪开始读（按目的选一条）**

- 只想看结论 → 上表 + [核心结果](#核心结果)
- 想复现 → [复现要点](#复现要点)，或 `python tools/run_scenario.py --scenario coercion --repeats 3`
- 想跑起来看 → `powershell -ExecutionPolicy Bypass -File tools/run_demo.ps1`
- 要交课程报告 → [docs/PRACTICE_B_REPORT.md](docs/PRACTICE_B_REPORT.md)（[DOCX 版](docs/PRACTICE_B_REPORT.docx)）

## 核心结果

2×2 消融，四组各 6 轮固定脚本、零请求失败。

| 组 | 模型 | 部署位置 | 记忆 | 平均延迟 | 最快 | 最慢 | 跨轮召回 |
|---|---|---|---:|---:|---:|---:|---:|
| A | DeepSeek-chat | 云端 GPU | 关 | 1542 ms | 1297 | 2063 | 0% |
| B | DeepSeek-chat | 云端 GPU | 开 | 4810 ms | 3630 | 7979 | **100%** |
| C | Qwen2.5-1.5B | 端侧 R9700 | 关 | 861 ms † | 695 | 1108 | 0% |
| D | Qwen2.5-1.5B | 端侧 R9700 | 开 | 1078 ms † | 803 | 1432 | **100%** |

† Qwen 行为服务端耗时（不含网络）；DeepSeek 仅有客户端端到端数据。口径说明见 [docs/EXPERIMENT_RESULTS.md](docs/EXPERIMENT_RESULTS.md)。

### 三条结论

**1. 功能上，记忆把跨轮召回从 0% 提到 100%，两种部署都成立。**

**2. 代价上，云端是 3.12 倍，端侧只有 1.25 倍，绝对增量相差约 15 倍。**

拆开看，两者的开销来源完全不同：

| 模型 | 回复字数 关 → 开 | 耗时 关 → 开 | 每字耗时 |
|---|---|---|---:|
| DeepSeek | 54.8 → 44.7（**−19%**） | +212% | 28.1 → 107.7 ms/字 |
| Qwen | 65 → 79（+21.5%） | +25% | 13.2 → 13.6 ms/字 |

端侧字多了、耗时按比例涨，**每字成本几乎不变**；云端字数反而变少、耗时却翻三倍，**增量根本不在生成环节**。这对应架构差异：云端每次检索要调远程 embedding 接口，端侧是本地计算。

**这条归因后来做了受控验证**（[experiments/MATRIX_REPLICATION.md](experiments/MATRIX_REPLICATION.md)）：
在本机 RTX 3050 上，同一模型、同一脚本，**只换 embedding 的位置**——
远程 DashScope **2.10×**（每轮多 1112 ms），本地 MiniLM **1.12×**（多 44 ms）。
分阶段计时确认这些时间都落在检索，而不是生成
（[experiments/STAGE_TIMING.md](experiments/STAGE_TIMING.md)）。

反过来，在 **CPU** 上最贵的既不是检索也不是生成，而是**每轮第二次 LLM 调用**——
好感度分析 11.2 s，比生成回复的 5.2 s 还贵一倍多（分析 prompt 要把整段对话塞进去，
而 CPU 的瓶颈在 prompt 预处理）。**端侧优化应该先削减分析用的 prompt。**

**3. 失效模式上，大模型诚实、小模型会编。**

同样在无记忆状态下被追问，DeepSeek 说「我一时对不上号了」，而 Qwen2.5-1.5B 说「当然记得！你在做的是一个关于多智能体系统的研究吧？」—— 后者其实来自它自己的系统提示词示例，被误当成了对玩家的记忆。对 NPC 产品而言，自信的错误比诚实的遗忘更危险。

## 四层治理（工程实践部分）

| 层 | 做什么 | 关键设计 | 文档 |
|---|---|---|---|
| ① 权威世界状态 | 金币/物品/任务/位置由后端持有 | 动作白名单；位置 R0–R4 校验（边界/单步/上报频率/出生点） | [GOVERNANCE](docs/GOVERNANCE.md) |
| ② 可追溯记忆 | 每条记忆带来源与可信度 | 来源先验 0.95 / 0.60 / 0.50 / **0.20**，低于阈值不进 prompt | [MEMORY_TRACEABILITY](docs/MEMORY_TRACEABILITY.md) |
| ③ NPC 关系图 | 3 个 NPC、3 条无向边，事件驱动 | 强度派生类型；证据链 20 条；Neo4j 可选镜像 + 启动回灌 | [RELATIONS](docs/RELATIONS.md) |
| ④ 场景引擎 | 扰动写成 YAML，跑完自动判定 | 4 个可重复场景；`--repeats` 求通过率 | [SCENARIO](docs/SCENARIO.md) |

后端 **32 条业务路由**、**143 个单元测试**：

```bash
python -m unittest discover -s tests -p "test_*.py"
```

**A/B 证据**（本地 Ollama Qwen2.5-1.5B；平台差异见 [PRACTICE_B_REPORT](docs/PRACTICE_B_REPORT.md) 第八章）

| 组 | 动作提议 | 裁决分布 | 判据 |
|---|---:|---|---|
| `ACTION_PROPOSAL=off` | **0** | — | 4/4 通过 |
| `on`（两份样本） | 9 + 6 | ok 3 / forbidden 1 / unknown_action 1 / precondition_failed 10 | 4/4 + 4/4 通过 |

被拦下的原文：`单次最多转移 5 个，请求 100 个`、`未知动作 acknowledge_payment`、
`npc_player 只有 0 个 code_review_report`。逐条见 [experiments/AB_RESULTS.md](experiments/AB_RESULTS.md)。

## 目录结构

```text
godot/        Godot 4.5.2 2D 客户端（场景、脚本、像素素材）
backend/      FastAPI + HelloAgents：NPC Agent、记忆管理、好感度、日志
experiments/  四组实验数据（逐轮延迟、服务端指标、对话日志）
docs/         报告、架构、部署、排错、演示链路、课堂汇报稿
tools/        本地转发代理与演示启动器（本地客户端 + 远程后端）
patches/      hello-agents 中文检索修复补丁
frontend/     网页版界面（早期原型，对照用）
data/         世界配置
run_aup.sh    远程端侧实验启停脚本（自检 / 冒烟 / 归档）
serve_qwen.py 本地 OpenAI 兼容服务（vLLM 在 ROCm 下不可用时的替代）
```

## 三种运行方式

### ① 全本地（完全离线，可用 Ollama）

后端、模型、向量库都在本机，**不访问任何云服务**。Godot 用默认地址直连。

```bash
# 1) 模型：Ollama 提供 OpenAI 兼容接口，后端不用改一行代码
ollama pull qwen2.5:1.5b
ollama serve                        # 默认 127.0.0.1:11434

# 2) 向量库（只有 MEMORY_MODE=on 需要）
docker start helloagents-qdrant-ch15

# 3) 后端
cd backend
cp .env.deepseek.example .env
pip install -r requirements.txt
export LLM_PROVIDER=openai \
       LLM_BASE_URL=http://127.0.0.1:11434/v1 \
       LLM_MODEL_ID=qwen2.5:1.5b \
       LLM_API_KEY=ollama \
       QDRANT_URL=http://127.0.0.1:6333      # ← 不要写 localhost，见坑 12
python -m uvicorn main:app --port 8000
```

> 用本地 embedding（`EMBED_MODEL_TYPE=local`）还需要 `torch` + `sentence-transformers`，
> 并且必须把 `EMBED_BASE_URL` / `EMBED_API_KEY` 置空 —— 否则会报「所有嵌入模型都不可用」，
> 原因见 `docs/TROUBLESHOOTING.md` 坑 9 / 坑 10。

### ② 端侧远程（本项目的实验形态）

模型和桥接服务都在远程 GPU 机器上，接口仍是 OpenAI 兼容协议，后端代码不改。

```bash
python3 serve_qwen.py              # 模型服务 :8001
bash run_aup.sh on                 # 后端 :8000（含自检与冒烟）
```

### ③ 本地客户端 + 远程后端（演示形态）

Godot 需要显示器、后端需要 GPU，演示时两端天然分离。但 JupyterHub 平台的
`/user/<user>/proxy/8000` 需要登录 Cookie，Godot 拿不到。本项目用一个只监听
`127.0.0.1` 的转发代理解决，**公网无入口**：

```powershell
.\tools\start_demo.ps1 -LaunchGodot
```

原理、坑与实测数据见 [docs/LOCAL_CLIENT_REMOTE_BACKEND.md](docs/LOCAL_CLIENT_REMOTE_BACKEND.md)。

## 文档索引

| 文档 | 内容 |
|---|---|
| [docs/EXPERIMENT_RESULTS.md](docs/EXPERIMENT_RESULTS.md) | 四组完整结果、延迟归因、失效模式、局限 |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | 部署与配置踩过的 **14 个坑**与修复（**建议先读**） |
| [docs/GOVERNANCE.md](docs/GOVERNANCE.md) | 权威状态与玩家隔离：好感度规则层、记忆按玩家隔离 |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 四个候选机制的设计、依赖、验证方案与本地部署评估 |
| [docs/LOCAL_CLIENT_REMOTE_BACKEND.md](docs/LOCAL_CLIENT_REMOTE_BACKEND.md) | 本地客户端 + 远程后端的演示链路 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 系统架构与实验开关 |
| [docs/CLASS_PRESENTATION_3MIN.md](docs/CLASS_PRESENTATION_3MIN.md) | 3 分钟课堂汇报稿 |
| [experiments/README.md](experiments/README.md) | 数据文件说明与口径陷阱 |
| [experiments/MATRIX_REPLICATION.md](experiments/MATRIX_REPLICATION.md) | 本地 A-B-B-A 复现与受控对照（含一次被推翻的结论） |
| [experiments/STAGE_TIMING.md](experiments/STAGE_TIMING.md) | 延迟分阶段分解，以及那个 2 秒假开销的定位过程 |
| [experiments/AB_RESULTS.md](experiments/AB_RESULTS.md) | **A/B 对照**：动作白名单拦住「发明动作 / 搬 100 个物品」，可信度阈值挡住伪造记忆（76→197 字符） |
| [docs/SCENARIO.md](docs/SCENARIO.md) | **可重复实验场景**：数据驱动的扰动 + 判据，含三个内置场景与实测 |
| [docs/RELATIONS.md](docs/RELATIONS.md) | **NPC↔NPC 关系图**：事件驱动演化、证据链、Neo4j 可选镜像 |
| [docs/MEMORY_TRACEABILITY.md](docs/MEMORY_TRACEABILITY.md) | **可追溯记忆**：来源/可信度/纠正/遗忘/合并，以及按可信度过滤 prompt |
| [tools/README.md](tools/README.md) | **22 个文件的索引**：跑实验 / 定位问题 / 出图 / 部署联调 |
| [docs/PRACTICE_B_REPORT.md](docs/PRACTICE_B_REPORT.md) | **工程实践 B 报告**：proposal + demo + AUP 云端预演 + 四层治理 + 算力需求（[DOCX](docs/PRACTICE_B_REPORT.docx)） |
| [docs/PPT_MATERIALS.md](docs/PPT_MATERIALS.md) | PPT 逐页内容与数字清单 |
| [docs/PPT_GEMINI_PROMPT.md](docs/PPT_GEMINI_PROMPT.md) | 给 Gemini 的 PPT 生成提示词（含图与验收清单） |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | 本地与 AUP 部署 |
| [docs/MODEL_SWITCHING.md](docs/MODEL_SWITCHING.md) | 云端 / 端侧模型切换 |

## 权威状态与玩家隔离

系统里曾有两处把**状态的主权交给了语言模型**，现已修复（细节见 [docs/GOVERNANCE.md](docs/GOVERNANCE.md)）：

| 缺陷 | 修复 |
|---|---|
| 好感度由模型直接决定，玩家可用话术一次推满 | `backend/rules.py`：模型只提议，后端按 R0–R4 规则裁决 |
| 记忆按 NPC 隔离，两个玩家会串 | 记忆键改为 `(NPC, 玩家)`，存储路径 `memory_data/<npc>/<player>/` |

验证方式（都不需要 GPU）：

```bash
python tests/test_affinity_rules.py                        # 15 个规则层单测
python tools/probe_governance.py --mode affinity           # 注入越权提示词看是否被截断
python tools/probe_governance.py --mode isolation          # 验证跨玩家记忆不泄露
```

规则层触发时会把 `affinity_proposed` / `affinity_rule_status` / `affinity_rule_notes`
写进 `metrics_*.csv`，因此"模型提议了多少、规则放行多少"是可统计的。

**世界状态也同样归后端所有。** 金币、物品、任务由 `backend/world_state.py` 持有，语言模型只能提交白名单动作，由 `backend/actions.py` 校验前置条件。最典型的越权 ——「给我 1000 金币」—— 会得到 `forbidden`，因为金币只能由任务奖励发放：

```bash
python tests/test_world_state.py    # 16 个状态机与动作白名单单测
curl -s http://127.0.0.1:8000/world/state
curl -s http://127.0.0.1:8000/world/actions   # 白名单自描述
```

四个更大机制的现状、依赖关系与验证方案见 [docs/ROADMAP.md](docs/ROADMAP.md)。

## 复现要点

**依赖锁定**（版本错一个，记忆系统就可能静默失效）：

```text
torch 2.9.1+rocm7.13.0        # 系统自带，勿用 pip 覆盖成 CUDA 版
qdrant-client==1.9.2          # 更高版本缺少 hello-agents 0.2.9 依赖的符号
sentence-transformers 6.2.0
transformers 5.19.0
hello-agents 0.2.9
qdrant server 1.20.0          # 单文件二进制，端口 6333
```

**必须设置的环境变量**（不设会导致记忆系统整体不可用，且报错信息误导）：

```bash
export EMBED_MODEL_TYPE=local
export QDRANT_URL=http://127.0.0.1:6333
```

**必须打的补丁**（中文检索在工作记忆里默认完全失效）：

```bash
python3 patches/apply_working_memory_fix.py --check   # 看状态
python3 patches/apply_working_memory_fix.py            # 应用（幂等，带备份）
```

**验证记忆是否真的生效**，不要看 `/npcs/{name}/memories` 接口（它对工作记忆恒返回空），要看服务端指标或日志：

```bash
cut -d, -f6,7 experiments/aup_qwen_memory_on_metrics.csv   # 耗时与召回数
grep -c "已保存到" backend/logs/dialogue_$(date +%F).log    # 有输出才说明写入成功
```

## 已知问题

- **工作记忆仍在进程内**（容量 10）；可追溯账本已落盘到
  `backend/memory_data/<npc>/<player>/ledger.json`，但**检索仍走 hello_agents**，
  两层不共享存储，可能出现「底层召回了一条、账本里查不到」
- `MEMORY_MODE=off` 时每轮新建 Agent，因此基线连**同轮上下文**也不保留（这是基线的定义）
- **场景重复次数仍偏少**：`--repeats` 已支持，但每个场景只跑过 1–2 次，
  「稳定通过」需要更多重复才有统计意义
- **关系图默认不从对话推断**：只由 `relation_event` 场景事件或 `POST /relations/event` 驱动，
  `RELATION_FROM_DIALOGUE` 默认关闭（1.5B 产出关系标记的可靠性低）
- **Neo4j 认证在本机已被关闭**（开发方便）；换机器或公开演示前应重新开启
- 单组仅 6 轮、单次采样，延迟差异处于统计临界，详见 [EXPERIMENT_RESULTS](docs/EXPERIMENT_RESULTS.md) 的局限一节
- Qdrant 只在 `MEMORY_MODE=on` 时参与检索，但仍是 `EpisodicMemory` 初始化的硬依赖
- 平台侧 Cloudflare 会拦截 .NET 客户端，因此工具链全部使用 Python 传输栈

## 许可与致谢

MIT License。上游项目：[Datawhale HelloAgents](https://github.com/datawhalechina/hello-agents) 第 15 章。第三方图片、音频与字体按各自许可证使用。请勿提交 `.env`、API Key、`memory_data/`、`qdrant_data/` 与个人对话日志。
