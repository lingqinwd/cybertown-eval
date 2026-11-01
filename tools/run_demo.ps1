# 一键起演示：后端 + 造关系数据 + 打开游戏
#
#   powershell -ExecutionPolicy Bypass -File tools\run_demo.ps1
#   powershell -ExecutionPolicy Bypass -File tools\run_demo.ps1 -NoGame    # 只起后端并造数据
#   powershell -ExecutionPolicy Bypass -File tools\run_demo.ps1 -Python "D:\path\to\python.exe"
#
# 为什么要这个脚本：
#   1) PATH 上的 python 可能是 Anaconda 基础环境，没有 uvicorn/fastapi；
#   2) PowerShell 里用 curl.exe 传中文 JSON，引号转义极易出错（会得到 422）；
#   3) 关系面板没数据时最常见的原因就是这两条，脚本替你把坑填了。

param(
    [string]$Python = "",
    [switch]$NoGame,
    [switch]$Force   # 允许强杀占用 8000 端口的进程
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $repo 'backend'
$godotExe = 'E:\Software\Godot\Godot-4.5.2\Godot_v4.5.2-stable_win64.exe'
$base = 'http://127.0.0.1:8000'

function Say($msg, $color = 'Gray') { Write-Host $msg -ForegroundColor $color }

# PowerShell 5.1 的 Invoke-RestMethod 对没有 charset 的 JSON 会按 ANSI 解码，
# 中文全变乱码。这里手工按 UTF-8 解。
function Get-JsonUtf8([string]$url) {
    $resp = Invoke-WebRequest -Uri $url -UseBasicParsing
    $text = [Text.Encoding]::UTF8.GetString($resp.RawContentStream.ToArray())
    return $text | ConvertFrom-Json
}

# ---------- 1) 找可用解释器 ----------
if (-not $Python) {
    $candidates = @(
        'E:\Conda\envs\helloagents\python.exe',
        (Join-Path $env:USERPROFILE 'anaconda3\python.exe')
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $Python = $c; break }
    }
    if (-not $Python) {
        $cmd = Get-Command python -ErrorAction SilentlyContinue
        if ($cmd) { $Python = $cmd.Source }
    }
}
if (-not $Python) { throw "找不到 python，请用 -Python 指定" }

& $Python -c "import uvicorn, fastapi" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "这个 Python 缺 uvicorn/fastapi：`n  $Python`n请用 -Python 指定可用环境，例如：`n  -Python E:\Conda\envs\helloagents\python.exe"
}
Say "[1/4] 解释器: $Python" 'Green'

# ---------- 2) 若 8000 已被占用，先清掉 ----------
$conn = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($conn) {
    $oldPid = $conn[0].OwningProcess
    if (-not $Force) {
        Say "[2/4] 端口 8000 已被 PID=$oldPid 占用，已中止（可能是你别的服务）" 'Yellow'
        Say "      确认可以杀掉再加 -Force，或先手动停掉它" 'Yellow'
        exit 1
    }
    Say "[2/4] 端口 8000 被 PID=$oldPid 占用，按 -Force 强制停掉" 'Yellow'
    Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 800
}

# ---------- 3) 起后端（独立窗口，方便看日志；关掉窗口即停止） ----------
Say "[3/4] 启动后端（新窗口）..."
$inner = "`$Host.UI.RawUI.WindowTitle='Cybertown Backend'; " +
         "cd '$backend'; " +
         "`$env:MEMORY_MODE='off'; " +
         "& '$Python' -m uvicorn main:app --host 127.0.0.1 --port 8000"
Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoExit', '-Command', $inner | Out-Null

$ok = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 1
    try {
        Invoke-WebRequest "$base/health" -UseBasicParsing -TimeoutSec 3 | Out-Null
        $ok = $true; break
    } catch { }
}
if (-not $ok) { throw "后端 30 秒内没起来，去看那个新弹出的窗口报了什么错" }
Say "      后端就绪: $base" 'Green'

# ---------- 4) 造关系数据（用 Invoke-RestMethod，避免引号转义地狱） ----------
function Send-Event([string]$kind, [string[]]$actors, [string]$note = '') {
    $payload = @{ kind = $kind; actors = $actors; note = $note } | ConvertTo-Json
    $bytes = [Text.Encoding]::UTF8.GetBytes($payload)
    return Invoke-RestMethod -Method Post -Uri "$base/relations/event" `
        -ContentType 'application/json; charset=utf-8' -Body $bytes
}

Invoke-RestMethod -Method Post -Uri "$base/relations/reset" `
    -ContentType 'application/json' -Body '{}' | Out-Null

Send-Event 'conflict' @('张三', '王五') '争夺任务起冲突' | Out-Null
Send-Event 'conflict' @('张三', '王五') '公开互相指责'   | Out-Null
Send-Event 'help'     @('张三', '李四') '帮李四看了报告' | Out-Null
Send-Event 'cooperate' @('李四', '王五') '一起整理设计稿' | Out-Null

$rel = Get-JsonUtf8 "$base/relations?include_evidence=false"
Say "[4/4] 关系数据:" 'Green'
foreach ($e in $rel.edges) {
    Say ("      {0}↔{1}  {2,-9} {3,6}" -f $e.a, $e.b, $e.type, $e.strength)
}

# ---------- 5) 开游戏 ----------
if ($NoGame) {
    Say ""
    Say "已跳过游戏。面板数据接口: $base/relations/graph" 'Cyan'
    Say "关掉后端窗口即可停止服务。" 'Cyan'
    return
}
if (-not (Test-Path $godotExe)) {
    Say "找不到 Godot: $godotExe" 'Yellow'
    Say "请手动打开 godot/project.godot" 'Yellow'
    return
}
Say ""
Say "打开游戏（fullscreen，关系面板在右上角，按 R 隐藏/显示）..." 'Cyan'
Start-Process -FilePath $godotExe -ArgumentList '--path', (Join-Path $repo 'godot')
Say "关闭游戏窗口后，记得再关掉后端那个窗口。" 'Cyan'
