# CyberTown-EdgeCloud：面向可交互 AI NPC 的端云协同推理与记忆增强研究

基于 Datawhale HelloAgents 第 15 章赛博小镇的端云协同 NPC 实验项目。

项目保留原始 Godot 4.5.2 像素办公室、玩家移动、NPC 巡逻和 E 键交互，只增加可测量的记忆、好感度和响应延迟信息，用来回答一个清晰的问题：

> 在不同模型部署位置下，长期情景记忆能否提升 NPC 的跨轮对话一致性？它会带来多少响应延迟？

## 当前工作副本

```text
godot/   原始 Godot 2D 项目
backend/ 原始 FastAPI + HelloAgents 后端
experiments/      记忆消融实验
docs/             设计和复现说明
```

`godot` 由教程原始项目复制而来，包含 `main.tscn`、`player.tscn`、`npc.tscn` 和 `dialogue_ui.tscn`。之前的简化原型保存在 `prototype_minimal/`，用于对照，不作为最终演示项目。

## 项目结构

```text
godot/       原始 Godot 4.5.2 2D 游戏客户端
backend/     FastAPI、NPC Agent、DeepSeek 适配和记忆系统
experiments/ 消融实验脚本、日志和 CSV 结果模板
docs/        架构、实验设计、本地部署和 AUP 部署说明
```

## 模型配置与切换

后端通过统一的 OpenAI 兼容接口切换 DeepSeek 云端模型和 AUP 本地小模型。复制配置模板：

```powershell
cd backend
Copy-Item .env.deepseek.example .env
notepad .env
```

在 `.env` 中填写本机密钥：

```dotenv
LLM_PROVIDER=deepseek
LLM_MODEL_ID=deepseek-chat
LLM_API_KEY=你的DeepSeek密钥
DEEPSEEK_API_KEY=你的DeepSeek密钥
LLM_BASE_URL=https://api.deepseek.com
MODEL_PROFILE=deepseek
```

AUP 小模型使用同一套 `/chat` 接口，只需把 `MODEL_PROFILE` 改为 `aup_local`，并填写 AUP 上 vLLM/Ollama 的 OpenAI 兼容地址。详见 [docs/MODEL_SWITCHING.md](docs/MODEL_SWITCHING.md)。

Embedding 仍使用原有的 DashScope `text-embedding-v3`，因为本项目的长期记忆需要向量化接口；DeepSeek 负责 NPC 回复和好感度分析。`.env` 不得提交到 GitHub。

## Godot 与后端地址

Godot 默认连接本机：

```text
http://127.0.0.1:8000
```

如果以后使用 AUP 后端，可以在启动 Godot 前设置：

```powershell
$env:CYBERTOWN_API_BASE_URL="https://你的AUP代理地址"
```

这样不需要修改 Godot 场景或脚本。

完整的本地和 AUP 部署流程见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。

## 实验设计

固定同一 NPC 和同一组问题，比较模型部署位置与记忆开关：

| 条件 | 模型 | 工作/情景记忆 |
|---|---|---:|
| 1 | DeepSeek 云端 | 关闭 |
| 2 | DeepSeek 云端 | 开启 |
| 3 | AUP 本地小模型 | 关闭 |
| 4 | AUP 本地小模型 | 开启 |

记录平均、最快、最慢响应延迟，记忆召回次数，事实回忆成功率，好感度变化和请求失败次数。这样可以在不训练模型的情况下形成可复现的课程实验。

实验结果模板见 [experiments/results_template.csv](experiments/results_template.csv)。
课堂汇报稿见 [docs/CLASS_PRESENTATION_3MIN.md](docs/CLASS_PRESENTATION_3MIN.md)。

### 当前截图实验结果

基于 6 次唯一对话的客户端端到端耗时：

| 模式 | 平均 | 最快 | 最慢 | 李四事实回忆 |
|---|---:|---:|---:|---:|
| 记忆模式 | 4810 ms | 3630 ms | 7979 ms | 1/1（100%） |
| 基线模式 | 1542 ms | 1297 ms | 2063 ms | 0/1（0%） |

记忆模式在当前小样本测试中平均多等待约 3268 ms，约为基线的 3.12 倍；代价换来跨轮事实回忆能力。该结果是一次课程实验样本，后续可增加重复次数以降低 DeepSeek 网络波动影响。原始截图数据分别保存在 `experiments/memory_on_screenshot_results.csv` 和 `experiments/memory_off_screenshot_results.csv`。

后端运行时会在 `backend/logs/metrics_YYYY-MM-DD.csv` 写入每轮服务端耗时、记忆召回数、好感度前后值和失败状态；Godot 界面显示的是包含网络往返的客户端端到端耗时。两者分别用于分析后端处理开销和玩家实际等待时间。

## 开源注意事项

- 保留 Datawhale HelloAgents 上游项目链接和致谢。
- 不提交 `.env`、API Key、Qdrant 数据目录和个人对话日志。
- 第三方图片、音频和字体按各自许可证使用。


