# CyberTown-Memory-Eval

基于 Datawhale HelloAgents 第 15 章赛博小镇的记忆增强 NPC 实验项目。

项目保留原始 Godot 4.5.2 像素办公室、玩家移动、NPC 巡逻和 E 键交互，只增加可测量的记忆、好感度和响应延迟信息，用来回答一个清晰的问题：

> 长期情景记忆能否提升 NPC 的跨轮对话一致性？它会带来多少响应延迟？

## 当前工作副本

```text
godot/   原始 Godot 2D 项目
backend/ 原始 FastAPI + HelloAgents 后端
experiments/      记忆消融实验
docs/             设计和复现说明
```

`godot` 由教程原始项目复制而来，包含 `main.tscn`、`player.tscn`、`npc.tscn` 和 `dialogue_ui.tscn`。之前的简化原型保存在 `prototype_minimal/`，用于对照，不作为最终演示项目。

## DeepSeek 配置

后端已经支持 OpenAI 兼容的 DeepSeek 接口。复制配置模板：

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
```

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

## 实验设计

固定同一模型、同一 NPC 和同一组问题，比较：

| 条件 | 工作记忆 | 情景记忆 | 好感度 |
|---|---:|---:|---:|
| Baseline | 否 | 否 | 固定 |
| Memory | 是 | 是 | 动态 |

记录平均、最快、最慢响应延迟，记忆召回次数，事实回忆成功率，好感度变化和请求失败次数。这样可以在不训练模型的情况下形成可复现的课程实验。

## 开源注意事项

- 保留 Datawhale HelloAgents 上游项目链接和致谢。
- 不提交 `.env`、API Key、Qdrant 数据目录和个人对话日志。
- 第三方图片、音频和字体按各自许可证使用。


