# CyberTown-EdgeCloud

**面向可交互 AI NPC 的端云协同推理与记忆增强研究**

基于 Datawhale HelloAgents 第 15 章赛博小镇。项目保留原始 Godot 4.5.2 像素办公室、玩家移动、NPC 巡逻和 E 键交互，只增加可测量的**记忆**、**好感度**和**响应延迟**，用来回答一个清晰的问题：

> 在不同模型部署位置下，长期情景记忆能否提升 NPC 的跨轮对话一致性？它会带来多少响应延迟？

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

**3. 失效模式上，大模型诚实、小模型会编。**

同样在无记忆状态下被追问，DeepSeek 说「我一时对不上号了」，而 Qwen2.5-1.5B 说「当然记得！你在做的是一个关于多智能体系统的研究吧？」—— 后者其实来自它自己的系统提示词示例，被误当成了对玩家的记忆。对 NPC 产品而言，自信的错误比诚实的遗忘更危险。

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

### ① 全本地（最简单，适合开发）

后端和模型都在本机，Godot 用默认地址直连。

```bash
cd backend
cp .env.deepseek.example .env      # 填 DEEPSEEK_API_KEY
pip install -r requirements.txt
python -m uvicorn main:app --port 8000
```

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
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | 端侧部署踩过的 8 个坑与修复（**建议先读**） |
| [docs/LOCAL_CLIENT_REMOTE_BACKEND.md](docs/LOCAL_CLIENT_REMOTE_BACKEND.md) | 本地客户端 + 远程后端的演示链路 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 系统架构与实验开关 |
| [docs/CLASS_PRESENTATION_3MIN.md](docs/CLASS_PRESENTATION_3MIN.md) | 3 分钟课堂汇报稿 |
| [experiments/README.md](experiments/README.md) | 数据文件说明与口径陷阱 |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | 本地与 AUP 部署 |
| [docs/MODEL_SWITCHING.md](docs/MODEL_SWITCHING.md) | 云端 / 端侧模型切换 |

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

- 记忆仅存活于进程内（写入 `working` 记忆，不落盘），后端重启即清空
- `MEMORY_MODE=off` 时每轮重建 Agent，因此基线连**同轮上下文**也不保留
- 单组仅 6 轮、单次采样，延迟差异处于统计临界，详见报告 §4 局限
- Qdrant 在本实验中并未真正参与检索，只是 `EpisodicMemory` 初始化的硬依赖
- 平台侧 Cloudflare 会拦截 .NET 客户端，因此工具链全部使用 Python 传输栈

## 许可与致谢

MIT License。上游项目：[Datawhale HelloAgents](https://github.com/datawhalechina/hello-agents) 第 15 章。第三方图片、音频与字体按各自许可证使用。请勿提交 `.env`、API Key、`memory_data/`、`qdrant_data/` 与个人对话日志。
