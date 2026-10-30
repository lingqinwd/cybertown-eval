# 部署说明

项目支持本地部署和 AUP Learning Cloud 部署。Godot 客户端通过 `CYBERTOWN_API_BASE_URL` 选择后端地址。

## 本地部署

```powershell
docker start helloagents-qdrant-ch15
cd E:\graduate_student\AI\cybertown-eval\backend
conda activate helloagents
$env:MEMORY_MODE="on"
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

基线实验把 `MEMORY_MODE` 改为 `off`。该模式不会创建、读取或保存 WorkingMemory、SQLite 和 Qdrant 记忆，也会为每轮请求创建新的 Agent，避免进程内短期上下文干扰。

使用 Godot 4.5.2 导入 `godot/project.godot` 并运行项目。默认后端地址为 `http://127.0.0.1:8000`。

## AUP Learning Cloud 部署

AUP 负责运行后端，Godot 客户端仍可在本机运行。

1. 在 AUP 中选择 CPU/GPU 环境，进入 JupyterLab。
2. 上传或克隆仓库到 `/home/jovyan/cybertown-eval`。
3. 安装依赖并配置 `backend/.env`：

   ```bash
   cd /home/jovyan/cybertown-eval
   pip install -r backend/requirements.txt
   cd backend
   export MEMORY_MODE=on
   nohup python -m uvicorn main:app --host 0.0.0.0 --port 8000 > server.log 2>&1 &
   ```

4. 通过 AUP 的 8000 端口代理地址检查：

   ```text
   https://<AUP域名>/user/<用户名>/proxy/8000/health
   ```

5. 在本机启动 Godot 前设置：

   ```powershell
   $env:CYBERTOWN_API_BASE_URL="https://<AUP域名>/user/<用户名>/proxy/8000"
   ```

AUP 额度有限时，优先在本地完成重复实验；AUP 用于远程后端展示或 GPU 推理。公开仓库不得上传 `.env`、API Key、日志和 `memory_data`。
