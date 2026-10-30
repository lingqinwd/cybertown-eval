# 模型切换与 AUP 小模型实验

后端使用同一个 `/chat` 接口，通过 `MODEL_PROFILE` 选择模型。Godot 客户端不需要修改。

## 已完成的两组

1. `MODEL_PROFILE=deepseek` + `MEMORY_MODE=off`
2. `MODEL_PROFILE=deepseek` + `MEMORY_MODE=on`

这两组已经完成，结果见 `experiments/memory_on_screenshot_results.csv` 和 `experiments/memory_off_screenshot_results.csv`。

## AUP 小模型服务

在 AUP 服务器上启动一个 OpenAI 兼容推理服务，推荐先使用 Qwen2.5-1.5B-Instruct 或 Qwen2.5-3B-Instruct。服务地址假设为：

```text
http://127.0.0.1:8001/v1
```

如果使用 vLLM，示例：

```bash
python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-1.5B-Instruct \
  --host 0.0.0.0 --port 8001
```

然后在后端 `.env` 中切换：

```dotenv
MODEL_PROFILE=aup_local
LLM_PROVIDER=openai
LLM_MODEL_ID=Qwen/Qwen2.5-1.5B-Instruct
LLM_API_KEY=local
LLM_BASE_URL=http://127.0.0.1:8001/v1
MEMORY_MODE=off
```

重启 FastAPI 后，通过 `/runtime/config` 检查当前配置。不要把模型权重或密钥提交到 GitHub。

## 两组 AUP 实验

### AUP 小模型 + 无记忆

设置 `MEMORY_MODE=off`，清空旧的结构化指标 CSV，使用与 DeepSeek 基线完全相同的六条问题。记录模型回复、客户端延迟、服务端延迟、失败次数和事实回忆成功率。

### AUP 小模型 + 有记忆

设置 `MEMORY_MODE=on`，恢复或新建干净记忆数据，再使用完全相同的六条问题。记录记忆召回次数、事实回忆成功率、延迟和好感度变化。

四组实验唯一变化是模型位置和记忆开关。每组至少运行一次完整流程，最好重复 3 次并报告均值与范围。
