# 本地客户端 + 远程后端（演示模式）

## 为什么需要这个模式

| 约束 | 后果 |
|---|---|
| Godot 需要一个**显示器**才能跑 | 客户端必须在自己的电脑上 |
| 端侧推理需要 **GPU**，且模型在远程 | 后端必须在远程 GPU 机器上 |

所以演示时两端天然分离：**Godot 在本机，FastAPI + 模型在远程**。

问题在于，这类平台（JupyterHub，例如 AUP Learning Cloud）的后端端口
`https://<host>/user/<user>/proxy/8000` **不是裸端口**，而是经 JupyterHub 反向代理，
靠浏览器的登录 Cookie 鉴权。Godot 是原生 HTTP 客户端，没有 Cookie，
直接访问只会拿到登录页 HTML。

## 三条可选路径

| 方案 | 公网暴露 | 前置条件 | 适用 |
|---|:--:|---|---|
| SSH 端口转发 | 无 | 平台开放 SSH | **最优**，但多数 JupyterHub 平台不提供 |
| 公网隧道（cloudflared 等） | **有** | 无 | 最后手段；临时 URL 会进入证书透明日志，可能被爬虫发现 |
| **本地转发代理（本仓库采用）** | 无 | 手动复制一次 Cookie | 只监听 `127.0.0.1`，安全性等同 SSH |

判断平台有没有 SSH：

```bash
ps aux | grep -c '[s]shd'      # 0 = 容器里没有 sshd
ls -la ~/.ssh 2>/dev/null      # 不存在 = 平台没预置公钥
```

JupyterHub 的标准镜像（用户名 `jovyan`）默认不装 sshd，所以通常只剩后两条。

## 实现要点

`tools/local_proxy.py` 在本机起一个**只监听 `127.0.0.1:8000`** 的 HTTP 服务，
把请求转发到远程并自动补上 `Cookie` 头。Godot 因此完全不用改代码，
也不需要设 `CYBERTOWN_API_BASE_URL` —— 它以为自己在连本地后端。

### 关键坑一：Cookie 是 HttpOnly，只能从 Network 面板复制

JupyterHub 的会话 Cookie 带 `HttpOnly`，在控制台执行 `document.cookie` **看不到**。
必须：

1. 打开平台页面 → `F12` → **Network**
2. 点任意一个发往该平台的请求
3. `Headers` → `Request Headers` → 复制 `Cookie:` 后面**一整行**

复制不全（例如漏了 `jupyterhub-hub-login`）会表现为"Cookie 无效"。

### 关键坑二：Cloudflare 拦截 .NET，但放行 Python 和 curl

平台的站点在 Cloudflare 后面，而 `cf_clearance` 绑定 TLS 指纹 + User-Agent。
实测同一个 URL、同一串 Cookie，五种客户端的差异极大：

| 客户端 | TLS 实现 | 结果 |
|---|---|:--:|
| 浏览器 | BoringSSL + HTTP/2 | ✅ |
| .NET `Invoke-WebRequest` | Schannel | ❌ 返回登录页 |
| curl.exe | Schannel | ✅ |
| **Python `urllib`** | **OpenSSL** | ✅ |

所以：

- **代理和所有自检都必须用 Python 发请求**。`tools/start_demo.ps1` 里的 `Probe()`
  就是用内联 Python 实现的，不要改成 `Invoke-WebRequest`，否则会误报"Cookie 无效"。
- 这个问题曾导致排查走过一大段弯路：前置检查用 .NET 写，失败后一直以为是 Cookie 或服务端的问题。

## 使用步骤

**远程侧**（见 [DEPLOYMENT.md](DEPLOYMENT.md)）：

```bash
python3 serve_qwen.py        # 模型服务 :8001，等 [serve] ready
bash run_aup.sh on           # FastAPI 后端 :8000
```

**本机侧**：

```powershell
.\tools\start_demo.ps1 -LaunchGodot
```

脚本会依次：校验 Cookie（Python）→ 检查 8000 端口 → 起代理 → 经代理探通 → 启动 Godot。

若 Godot 不在 PATH，手动打开 `godot/project.godot` 即可，**不要**设 `CYBERTOWN_API_BASE_URL`。

## 实测结果

本链路已在真实混合部署下验证通过（本机 Godot + AMD Radeon R9700 远程后端）：

| 轮次 | NPC | 回复要点 | 端到端耗时 |
|---|---|---|---:|
| 1 | 李四 | 复述"小林"与"赛博小镇课程项目" | 2162 ms |
| 2 | 李四 | **正确回忆**：「当然记得了，小林！你在做的那个赛博小镇课程项目…」 | 2513 ms |

## 延迟口径：不能与实验数据混用

经过本地代理后，每一次 `/chat` 都比直连多**两跳**（Godot → 本地代理 → 远程反代 → 后端）。
上表的 2162 / 2513 ms 与 `experiments/` 里的 861 / 1078 ms **不是同一口径**：

| 口径 | 组成 | 用在哪里 |
|---|---|---|
| 服务端耗时 | 后端收到请求到返回 | `aup_qwen_memory_*_metrics.csv`，**报告主指标** |
| 浏览器直连 | 浏览器 → 反代 → 后端 | `aup_qwen_memory_*_turns.csv` |
| 本地代理 | 上者 + 本地一跳 | 仅演示，**不要写进报告** |

## 排错

| 现象 | 原因 | 处理 |
|---|---|---|
| `[FAIL] 远程返回的是登录页` | Cookie 不全或已过期 | 重新从 Network 面板复制整行 |
| `[FAIL] 直连失败（状态 500）` | 远程后端没启动 | 到远程执行 `bash run_aup.sh on` |
| `[FAIL] 8000 端口已被占用` | 本机还有别的后端 | `Get-NetTCPConnection -LocalPort 8000` 找到并停掉 |
| Godot 连不上，代理窗口无输出 | Godot 没把请求发出去 | 检查 Godot 控制台是否打印 `[INFO] API地址: http://127.0.0.1:8000` |
| 代理窗口打印"收到 HTML" | Cookie 过期 | 重新复制并重跑脚本 |
| 突然全部请求失败 | Cookie 到期（通常几小时） | 同上 |

`tools/test_transport.ps1` 可以一次性比较五种客户端的连通性，用来判断到底是
Cookie 问题还是传输层问题。
