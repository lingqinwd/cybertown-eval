"""在本地电脑转发 Godot 请求到远程后端，并自动注入 JupyterHub Cookie。

为什么需要它
------------
如果后端部署在 JupyterHub 平台（如 AUP Learning Cloud），
`https://<host>/user/<user>/proxy/8000` 不是裸端口，而是 JupyterHub 反向代理，
靠浏览器的登录 Cookie 鉴权。Godot 是原生 HTTP 客户端，没有 Cookie，
直接访问只会拿到登录页 HTML。而这类平台通常不开放 SSH，无法用端口转发。

本脚本在本地建一个只监听 127.0.0.1 的"假后端"，把请求转发到远程并补上 Cookie。
这样 Godot 用默认的 http://127.0.0.1:8000 就能正常对话，不需要改任何 Godot 代码，
也不需要在公网暴露任何端口。

重要：本脚本用 Python 的 urllib 转发。不要改成 .NET（Invoke-WebRequest）或 PowerShell
原生客户端 —— 实测 .NET 的 TLS 指纹会被 Cloudflare 判定为机器人并返回登录页，
而 Python 和 curl 可以正常通过。

用法（Windows PowerShell）
--------------------------
1) 从浏览器取 Cookie：
   F12 → Network → 点任一发往该平台的请求 → Request Headers → 复制 Cookie: 整行
   （JupyterHub 的 Cookie 是 HttpOnly，document.cookie 看不到，必须在 Network 面板复制）

2) 设置环境变量并启动：
   $env:AUP_COOKIE="jupyterhub-user-xxx=eyJ...; jupyterhub-hub-login=..."
   python tools/local_proxy.py

3) 保持本窗口运行，另开窗口启动 Godot（不需要设 CYBERTOWN_API_BASE_URL）。

注意
----
* Cookie 通常几小时过期，失效后重新复制。
* 只用于演示。经过本代理采集的延迟多出两跳网络，不能与 experiments/ 里
  已有的实验数据混用 —— 那些数据是浏览器直连采集的。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TARGET = os.getenv("AUP_PROXY_TARGET", "").rstrip("/")
COOKIE = os.getenv("AUP_COOKIE", "").strip()
LISTEN_PORT = int(os.getenv("LOCAL_PROXY_PORT", "8000"))
TIMEOUT = int(os.getenv("LOCAL_PROXY_TIMEOUT", "300"))

# 默认值指向作者用的 AUP 路径，换成你自己的即可（或用 AUP_PROXY_TARGET 覆盖）
DEFAULT_TARGET = "https://tpe.aupcloud.io/user/bjut_teach_068/proxy/8000"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # 静音默认日志
        return

    def _forward(self, method: str) -> None:
        started = time.perf_counter()
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None

        url = TARGET + self.path
        req = urllib.request.Request(url, data=body, method=method)
        ctype = self.headers.get("Content-Type", "application/json")
        if body:
            req.add_header("Content-Type", ctype)
        req.add_header("Cookie", COOKIE)
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", "cybertown-local-proxy/1.0")

        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = resp.read()
                status = resp.status
                out_type = resp.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as exc:
            data = exc.read()
            status = exc.code
            out_type = exc.headers.get("Content-Type", "text/plain")
        except Exception as exc:  # noqa: BLE001
            data = json.dumps(
                {"error": f"{type(exc).__name__}: {exc}", "target": url}, ensure_ascii=False
            ).encode("utf-8")
            status = 502
            out_type = "application/json"

        # 明确区分 HTML 登录页，避免 Godot 静默解析失败
        head = data[:200].lstrip().lower()
        if head.startswith((b"<!doctype", b"<html")) or head.startswith(b"<!--"):
            print(
                "  !! 收到 HTML（多半是登录页）：Cookie 已失效或不完整。\n"
                "     重新从浏览器 F12 → Network → Request Headers 复制 Cookie 整行。",
                flush=True,
            )

        elapsed = (time.perf_counter() - started) * 1000
        print(f"  {method:4s} {self.path:38s} {status}  {elapsed:7.0f} ms", flush=True)

        self.send_response(status)
        self.send_header("Content-Type", out_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        self._forward("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._forward("POST")

    def do_DELETE(self) -> None:  # noqa: N802
        self._forward("DELETE")


def main() -> int:
    global TARGET  # noqa: PLW0603
    if not TARGET:
        TARGET = DEFAULT_TARGET
        print(f"[proxy] AUP_PROXY_TARGET 未设置，使用默认值:\n        {TARGET}")
        print("[proxy] 换成你自己的路径： $env:AUP_PROXY_TARGET=\"https://<host>/user/<user>/proxy/8000\"")
    if not COOKIE:
        print(
            "[proxy] 缺少 AUP_COOKIE 环境变量。\n"
            "        PowerShell 示例:\n"
            '        $env:AUP_COOKIE="jupyterhub-user-xxx=eyJ...; jupyterhub-hub-login=..."',
            file=sys.stderr,
        )
        return 2

    print(f"[proxy] 监听 http://127.0.0.1:{LISTEN_PORT}  ->  {TARGET}")
    print("[proxy] Godot 端不需要设置 CYBERTOWN_API_BASE_URL，直接运行即可。")
    print("[proxy] Ctrl+C 停止。\n")

    server = ThreadingHTTPServer(("127.0.0.1", LISTEN_PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[proxy] 已停止")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
