# CyberTown-Eval

一个面向长期记忆、社会关系演化与可控多智能体的浏览器赛博小镇实验。

## 目标

玩家可以在浏览器中操作角色，在小镇中接近 NPC、对话、完成任务，并观察 NPC 如何根据记忆和好感度改变后续行为。后端保存权威世界状态，模型只提出对话或行动建议，规则层负责验证状态变化。

## 启动

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m backend.main
```

访问 `http://127.0.0.1:8000`。GPU embedding 可设置：

```powershell
$env:CYBERTOWN_EMBEDDING_MODEL="BAAI/bge-small-zh-v1.5"
$env:CYBERTOWN_DEVICE="cuda"
```

首次启动时才下载 embedding 权重；服务器准备阶段不会下载。没有 GPU 或模型时会自动回退到轻量检索。

## 操作

- WASD 或方向键：移动玩家
- 点击 NPC：选择居民
- 走到 NPC 附近后点击“开始对话”
- 查看右侧记忆、好感度和底部事件时间线
- 点击“重置世界”重新开始实验

## 实验版本

| 版本 | 记忆 | 好感度 | 规则校验 | 目的 |
|---|---|---|---|---|
| A | 无 | 无 | 弱 | 基础聊天 NPC |
| B | 有 | 无 | 弱 | 测量记忆作用 |
| C | 有 | 有 | 弱 | 测量关系变化 |
| D | 有 | 有 | 强 | 完整可控版本 |

正式实验使用固定事件脚本和 20～30 轮交互，记录角色一致性、记忆正确率、非法状态修改次数、关系变化、P95 延迟、GPU embedding 延迟和单轮成本。人工评分表暂时留空。

## 目录

- `backend/`：FastAPI API、世界状态机、记忆检索、模型适配
- `frontend/`：浏览器游戏界面
- `experiments/`：实验设计和结果模板
- `data/`：NPC、任务和事件配置
