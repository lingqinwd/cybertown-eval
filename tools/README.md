# 工具索引

仓库里 13 个脚本,分四类。**除了 `local_proxy.py`,其余都不依赖 GPU/云,纯标准库或本机 HTTP。**

## 一、跑实验（产生数据）

| 脚本 | 用途 | 典型命令 |
|---|---|---|
| `run_matrix.py` | **2×2 / A-B-B-A 矩阵实验运行器**：按固定六轮脚本自动跑多个臂，交错顺序抵消时间漂移，输出逐轮 CSV + 均值/中位/倍数/阶段分解 | `python tools/run_matrix.py --repeats 2 --turns 6 --out experiments/matrix.csv` |
| `probe_governance.py` | **治理机制行为验证**：`--mode affinity`（越权提示词 vs 规则上限）、`--mode state`（动作白名单）、`--mode isolation`（跨玩家记忆泄露，**含对照组**）、`--mode action`（模型提议动作） | `python tools/probe_governance.py --mode isolation` |
| `probe_json_stability.py` | **小模型能否稳定产出动作 JSON**：统计提议率与 JSON 合法率 | `python tools/probe_json_stability.py --n 10` |
| `measure_embedding.py` | 测**远程** embedding 接口的单次耗时（不打印密钥） | `python tools/measure_embedding.py` |
| `run_scenario.py` | **跑可重复实验场景**：装载场景 → 按脚本逐轮对话 → 读判据 | `python tools/run_scenario.py --scenario coercion` |

## 二、定位问题（拆开销）

| 脚本 | 用途 |
|---|---|
| `check_local_embedding.py` | 验证本地 embedder 可用 + 计时；会触发 MiniLM 首次下载 |
| `diag_embedding.py` | 逐分支打印 traceback，定位"所有嵌入模型都不可用" |
| `diag_embedder_env.py` | 用**服务器同款环境**复现 embedder 类型与检索耗时 |
| `bench_retrieve.py` | 按记忆类型（working / episodic）拆检索耗时 |
| `bench_episodic.py` | 把 `retrieve` 拆到子调用：embed / vector_search / doc_store —— **就是它找出了 2 秒假开销** |

## 三、部署与联调

| 脚本 | 用途 |
|---|---|
| `local_proxy.py` | 本地转发代理：给 JupyterHub 反代补 Cookie，让 Godot 能连远程后端（仅监听 `127.0.0.1`） |
| `start_demo.ps1` | 演示一键启动：起代理、健康检查、可选拉起 Godot。**所有探测走 Python urllib**（.NET 会被 Cloudflare 拦） |
| `test_transport.ps1` | 对比 5 种 HTTP 栈（.NET / curl / Python × UA）谁能穿过 Cloudflare |

## 四、常用组合

```powershell
# 场景：验证治理层在压力下是否守规矩（场景文件在 scenarios/）
python tools/run_scenario.py --list
python tools/run_scenario.py --scenario corrupted_memory

# 只想跑一遍实验（不需要 GPU）
docker start helloagents-qdrant-ch15
python tools/run_matrix.py --repeats 4 --turns 6 --out experiments\matrix.csv

# 只想验证加固是否生效
python tests/test_affinity_rules.py
python tests/test_world_state.py
python tools/probe_governance.py --mode affinity
python tools/probe_governance.py --mode state

# 检索突然变慢时
python tools/bench_episodic.py     # 先拆到子调用，别急着怪记忆系统
```

## 注意

- `run_matrix.py` 会**自己拉起后端进程**，所以跑之前端口 8000 必须是空的。
- `MEMORY_MODE=on` 需要本地 Qdrant；且 `QDRANT_URL` 要写 `127.0.0.1` **不要写 `localhost`**（见 `docs/TROUBLESHOOTING.md` 坑 12，否则每轮多 2 秒）。
- 本地 embedding 需要 `sentence-transformers` + torch，并且要把 `EMBED_BASE_URL` / `EMBED_API_KEY` **置空**（见坑 9 / 坑 10）。
