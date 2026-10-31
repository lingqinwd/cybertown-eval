<#
.SYNOPSIS
    演示启动器：Godot 跑在本机，后端跑在远程（JupyterHub 平台，如 AUP）。

.DESCRIPTION
    远程后端位于 /user/<user>/proxy/8000，是 JupyterHub 反向代理，需要登录 Cookie；
    这类平台通常不开放 SSH，无法端口转发。本脚本在本地起一个只监听 127.0.0.1 的
    转发代理（tools/local_proxy.py），把请求送到远程并补上 Cookie —— 公网无入口。

    重要：本脚本所有检查都走 Python 的 urllib，与代理使用完全相同的传输栈。
    不要改成 Invoke-WebRequest —— 实测 .NET 的 TLS 指纹会被 Cloudflare 判为机器人
    并返回登录页，导致误报“Cookie 无效”。

    启动前请确认远程侧已经跑好（见 docs/DEPLOYMENT.md）：
        终端 1:  python3 serve_qwen.py     # 端侧模型服务 :8001
        终端 2:  bash run_aup.sh on        # FastAPI 后端 :8000

.PARAMETER Target
    远程代理地址。默认读环境变量 AUP_PROXY_TARGET，否则用脚本内默认值。

.PARAMETER LaunchGodot
    就绪后顺便启动 Godot。

.EXAMPLE
    .\tools\start_demo.ps1 -LaunchGodot
.EXAMPLE
    .\tools\start_demo.ps1 -Target "https://<host>/user/<user>/proxy/8000"
#>
param(
    [string]$Cookie = $env:AUP_COOKIE,
    [string]$Target = $(if ($env:AUP_PROXY_TARGET) { $env:AUP_PROXY_TARGET } else { "https://tpe.aupcloud.io/user/bjut_teach_068/proxy/8000" }),
    [string]$GodotDir,
    [switch]$LaunchGodot,
    [switch]$KeepProxyOnFail
)

$ErrorActionPreference = 'Stop'
$toolsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $toolsDir
$proxyScript = Join-Path $toolsDir 'local_proxy.py'
if (-not $GodotDir) { $GodotDir = Join-Path $repoRoot 'godot' }
$script:proxyProc = $null

function Say($m)   { Write-Host $m }
function Ok($m)    { Write-Host "  [OK]   $m" -ForegroundColor Green }
function Bad($m)   { Write-Host "  [FAIL] $m" -ForegroundColor Red }
function Warn2($m) { Write-Host "  [WARN] $m" -ForegroundColor Yellow }

function Snip([string]$t, [int]$n = 120) {
    if (-not $t) { return '(空)' }
    $t = $t.Trim()
    if ($t.Length -gt $n) { $t = $t.Substring(0, $n) }
    return ($t -replace '\s+', ' ')
}

function Stop-ProxyWindow {
    if ($null -ne $script:proxyProc) {
        if (-not $script:proxyProc.HasExited) {
            & taskkill /T /F /PID $script:proxyProc.Id 2>$null | Out-Null
        }
    }
}

# 用 Python 的 urllib 发请求 —— 与 local_proxy.py 完全同一条传输栈
function Probe([string]$Url, [string]$CookieText) {
    $env:PROBE_URL = $Url
    $env:PROBE_COOKIE = $CookieText
    $py = @'
import os, sys, urllib.request, urllib.error
url = os.environ["PROBE_URL"]; cookie = os.environ.get("PROBE_COOKIE", "")
h = {"Accept": "application/json", "User-Agent": "cybertown-demo/1.0"}
if cookie:
    h["Cookie"] = cookie
req = urllib.request.Request(url, headers=h)
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8", "replace"); st = r.status
except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8", "replace"); st = e.code
except Exception as e:
    print("EXC"); print(type(e).__name__ + ": " + str(e)[:150]); sys.exit(0)
print(st); print(body[:4000].replace("\n", " "))
'@
    $raw = $py | & python - 2>&1
    $status = 'ERR'; $body = '(无输出)'
    if ($raw) {
        if ($raw.Count -ge 2) {
            $status = [string]($raw | Select-Object -First 1)
            $body = (($raw | Select-Object -Skip 1) -join ' ')
        } else {
            $body = ($raw -join ' ')
        }
    }
    Remove-Item Env:PROBE_COOKIE -ErrorAction SilentlyContinue
    return [pscustomobject]@{
        Status = $status
        Body   = $body
        Ok     = ($body -match '"memory_mode"')
    }
}

Say ''
Say '================================================================'
Say ' CyberTown 演示启动器  (Godot 本地 + 后端在远程)'
Say '================================================================'
Say ''

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Bad '找不到 python，请先安装 Python 3 或激活 conda 环境'
    exit 1
}
if (-not (Test-Path $proxyScript)) {
    Bad "找不到 local_proxy.py，应位于: $proxyScript"
    exit 1
}

if (-not $Cookie -or $Cookie.Trim() -eq '') {
    Say '需要浏览器里的 JupyterHub Cookie：'
    Say '  1) 浏览器打开平台的 JupyterLab 页面'
    Say '  2) F12 -> Network 面板'
    Say '  3) 点任意一个发往该平台的请求'
    Say '  4) Headers -> Request Headers -> 复制 Cookie: 后面那一整串'
    Say ''
    $Cookie = Read-Host '把 Cookie 整串粘贴到这里，然后回车'
    if (-not $Cookie -or $Cookie.Trim() -eq '') { Bad 'Cookie 为空，退出'; exit 1 }
}
$Cookie = $Cookie.Trim()
Ok ("Cookie 长度 " + $Cookie.Length + " 字符")

Say ''
Say '[1/4] 验证 Cookie（直连远程，走 Python 传输栈）'
$probe = Probe "$Target/runtime/config" $Cookie
if (-not $probe.Ok) {
    if ($probe.Body -match 'Login to |hub/native/login|hub/github/oauth_login') {
        Bad '远程返回的是登录页 —— Cookie 无效或已过期'
        Warn2 '重新复制一次 Cookie；注意要整行，包含所有 name=value'
    } else {
        Bad ("直连失败 / 返回异常（状态 " + $probe.Status + "）")
        Warn2 ('响应开头: ' + (Snip $probe.Body))
        Warn2 '若状态是 500，多半是远程后端没启动'
    }
    exit 1
}
Ok ('拿到配置: ' + (Snip $probe.Body 160))

Say ''
Say '[2/4] 检查本地端口 8000'
$busy = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    Bad ("本地 8000 端口已被占用 (PID " + $busy[0].OwningProcess + ")")
    Warn2 '先停掉占用者： Get-NetTCPConnection -LocalPort 8000'
    exit 1
}
Ok '8000 端口空闲'

Say ''
Say '[3/4] 启动本地转发代理（会新开一个窗口，演示期间不要关）'
$env:AUP_COOKIE = $Cookie
$env:AUP_PROXY_TARGET = $Target
$cmd = "cd `"$toolsDir`"; python local_proxy.py"
$script:proxyProc = Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoExit', '-Command', $cmd -PassThru

$throughProxy = $false
for ($i = 1; $i -le 12; $i++) {
    $p2 = Probe 'http://127.0.0.1:8000/runtime/config' ''
    if ($p2.Ok) {
        Ok ('经代理访问正常: ' + (Snip $p2.Body 160))
        $throughProxy = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $throughProxy) {
    Bad '经代理访问失败'
    if ($KeepProxyOnFail) {
        Warn2 '-KeepProxyOnFail 已指定，代理窗口保留，请查看它的报错'
    } else {
        Warn2 '已关闭代理窗口。如需排查，加 -KeepProxyOnFail 参数重跑'
        Stop-ProxyWindow
    }
    exit 1
}

if (Test-Path Env:CYBERTOWN_API_BASE_URL) {
    Remove-Item Env:CYBERTOWN_API_BASE_URL
    Warn2 '已清除 CYBERTOWN_API_BASE_URL，Godot 将使用默认的 127.0.0.1:8000'
}

Say ''
Say '[4/4] 启动 Godot'
$projFile = Join-Path $GodotDir 'project.godot'
if ($LaunchGodot) {
    if (-not (Test-Path $projFile)) {
        Bad "没找到项目文件: $projFile"
    } elseif (Get-Command godot -ErrorAction SilentlyContinue) {
        Start-Process -FilePath 'godot' -ArgumentList '--path', $GodotDir
        Ok 'Godot 已启动'
    } else {
        Warn2 'godot 不在 PATH 里，请手动打开 Godot 4.5.2 并导入:'
        Warn2 $projFile
    }
} else {
    Say '  未加 -LaunchGodot，请手动启动 Godot 4.5.2：'
    Say "    $projFile"
}

Say ''
Say '================================================================'
Say ' 就绪。注意：'
Say '   * Godot 不要设置 CYBERTOWN_API_BASE_URL，用默认 127.0.0.1:8000'
Say '   * 连不上时先看代理窗口的报错'
Say '   * Cookie 通常几小时后过期，重新复制并重跑本脚本'
Say '   * 演示结束直接关代理窗口即可，公网本来就没有入口'
Say '================================================================'
Say ''
