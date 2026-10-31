<#
.SYNOPSIS
    诊断：为什么浏览器能访问 AUP，而命令行工具不能。

.DESCRIPTION
    对同一个 URL 依次用五种传输方式请求，比较结果。关键在于 E 项 ——
    local_proxy.py 就是用 Python 转发的，所以 E 的结果决定这条路走不走得通。

    Cookie 只从环境变量或提示读取，绝不出现在任何输出里。

.EXAMPLE
    .\test_transport.ps1
#>
param(
    [string]$Cookie = $env:AUP_COOKIE,
    [string]$Url = "https://tpe.aupcloud.io/user/bjut_teach_068/proxy/8000/runtime/config"
)

$ErrorActionPreference = 'Continue'
$ChromeUA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'

function Say($m) { Write-Host $m }
function Row($name, $status, $ok, $snippet) {
    $flag = 'MISS'
    if ($ok) { $flag = 'HIT ' }
    Write-Host ("  {0,-38} {1,-4} {2}   {3}" -f $name, $status, $flag, $snippet)
}
function Snip([string]$t) {
    if (-not $t) { return '(空)' }
    $t = $t.Trim()
    if ($t.Length -gt 52) { $t = $t.Substring(0, 52) }
    return ($t -replace '\s+', ' ')
}
function IsHit([string]$t) { return ($t -match '"memory_mode"') }

Say ''
Say '================================================================'
Say ' 传输层诊断：浏览器能过，命令行能不能过？'
Say '================================================================'
Say ''

if (-not $Cookie -or $Cookie.Trim() -eq '') {
    Say '请粘贴浏览器里的 Cookie（不会显示在结果里）：'
    $Cookie = Read-Host 'Cookie'
}
if (-not $Cookie) { Write-Host '没有 Cookie，退出' -ForegroundColor Red; exit 1 }
$Cookie = $Cookie.Trim()
Say ("Cookie 长度: " + $Cookie.Length)
Say ("目标 URL   : " + $Url)
Say ''
Say ' 测试项                                 状态  结果   响应开头'
Say ' ----------------------------------------------------------------------'

$res = @{}
$tmp = Join-Path $env:TEMP 'aup_probe_body.txt'

# --- A: .NET Invoke-WebRequest，默认 UA ---
$st = 'ERR'; $ok = $false; $sn = ''
try {
    $r = Invoke-WebRequest -Uri $Url -Headers @{ Cookie = $Cookie } -UseBasicParsing -TimeoutSec 25
    $st = [string]$r.StatusCode; $ok = IsHit ([string]$r.Content); $sn = Snip ([string]$r.Content)
} catch { $st = 'EXC'; $sn = Snip ($_.Exception.Message) }
Row 'A. .NET Invoke-WebRequest（默认 UA）' $st $ok $sn
$res['A'] = $ok

# --- B: .NET + Chrome UA ---
$st = 'ERR'; $ok = $false; $sn = ''
try {
    $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 25 `
            -Headers @{ Cookie = $Cookie; 'User-Agent' = $ChromeUA; 'Accept' = 'application/json' }
    $st = [string]$r.StatusCode; $ok = IsHit ([string]$r.Content); $sn = Snip ([string]$r.Content)
} catch { $st = 'EXC'; $sn = Snip ($_.Exception.Message) }
Row 'B. .NET + Chrome UA' $st $ok $sn
$res['B'] = $ok

# --- C: curl.exe，默认 UA ---
$st = 'ERR'; $ok = $false; $sn = ''
if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
    Remove-Item $tmp -ErrorAction SilentlyContinue
    $code = & curl.exe -s -m 25 -o $tmp -w '%{http_code}' -H "Cookie: $Cookie" $Url 2>$null
    $st = [string]$code
    if (Test-Path $tmp) {
        $b = [string](Get-Content $tmp -Raw -ErrorAction SilentlyContinue)
        $ok = IsHit $b; $sn = Snip $b
    }
    Row 'C. curl.exe（默认 UA）' $st $ok $sn
    $res['C'] = $ok
} else { Row 'C. curl.exe（未安装）' '-' $false ''; $res['C'] = $false }

# --- D: curl.exe + Chrome UA（不跟随重定向，保留原始状态码）---
$st = 'ERR'; $ok = $false; $sn = ''
if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
    Remove-Item $tmp -ErrorAction SilentlyContinue
    $code = & curl.exe -s -m 25 -o $tmp -w '%{http_code}' `
                -A $ChromeUA -H "Cookie: $Cookie" -H 'Accept: application/json' $Url 2>$null
    $st = [string]$code
    if (Test-Path $tmp) {
        $b = [string](Get-Content $tmp -Raw -ErrorAction SilentlyContinue)
        $ok = IsHit $b; $sn = Snip $b
    }
    Row 'D. curl.exe + Chrome UA' $st $ok $sn
    $res['D'] = $ok
} else { Row 'D. curl.exe（未安装）' '-' $false ''; $res['D'] = $false }

# --- E: Python urllib（就是 local_proxy.py 用的那条路）---
$st = 'ERR'; $ok = $false; $sn = ''
$pyOk = $false
if (Get-Command python -ErrorAction SilentlyContinue) {
    $env:PROBE_URL = $Url
    $env:PROBE_COOKIE = $Cookie
    $env:PROBE_UA = $ChromeUA
    $pyCode = @'
import os, urllib.request, urllib.error
url = os.environ["PROBE_URL"]; cookie = os.environ["PROBE_COOKIE"]; ua = os.environ["PROBE_UA"]
req = urllib.request.Request(url, headers={"Cookie": cookie, "Accept": "application/json", "User-Agent": ua})
try:
    with urllib.request.urlopen(req, timeout=25) as r:
        body = r.read().decode("utf-8", "replace")
        print(r.status); print(body[:4000].replace("\n", " "))
except urllib.error.HTTPError as e:
    print(e.code); print(e.read().decode("utf-8", "replace")[:4000].replace("\n", " "))
except Exception as e:
    print("EXC"); print(type(e).__name__ + ": " + str(e)[:120])
'@
    $raw = $pyCode | & python - 2>&1
    if ($raw -and $raw.Count -ge 2) {
        $st = [string]($raw | Select-Object -First 1)
        # 必须把完整响应体拼起来再判定：只取前 N 字符会把 memory_mode 截掉（这是之前的 bug）
        $body = (($raw | Select-Object -Skip 1) -join ' ')
        $ok = IsHit $body
        $sn = Snip $body
        $pyOk = $true
    } else {
        $st = 'ERR'; $sn = Snip (($raw -join ' ') -replace '\s+', ' ')
    }
    Remove-Item Env:PROBE_COOKIE -ErrorAction SilentlyContinue
    Row 'E. Python urllib（local_proxy 用的）' $st $ok $sn
    $res['E'] = $ok
} else { Row 'E. Python（未安装）' '-' $false ''; $res['E'] = $false }

Say ''
Say ' ----------------------------------------------------------------------'
$anyOk = $false
foreach ($k in @('A','B','C','D','E')) { if ($res[$k]) { $anyOk = $true } }

if ($res['E']) {
    Write-Host ' 结论：Python urllib 能通过 —— local_proxy.py 这条路可行。' -ForegroundColor Green
    Write-Host '   → 直接用 start_demo.ps1 即可；它之前失败是因为校验用的是 .NET，而转发用的是 Python。' -ForegroundColor Green
    Write-Host '   → 我可以把 start_demo.ps1 的前置校验也改成走 Python，避免误判。' -ForegroundColor Green
} elseif ($anyOk) {
    Write-Host ' 结论：别的传输能过，但 Python 不行。' -ForegroundColor Yellow
    Write-Host '   → 需要把 local_proxy.py 的转发后端换成能通过的那种（curl 或 .NET）。' -ForegroundColor Yellow
} else {
    Write-Host ' 结论：五种方式全部失败，只有浏览器可以。' -ForegroundColor Red
    Write-Host '   → 确认是 Cloudflare 按 TLS 指纹拦截非浏览器客户端，Cookie 再补也没用。' -ForegroundColor Red
    Write-Host '   → Godot 自带 HTTP 栈同样会被拦，需要换演示方案。' -ForegroundColor Red
}
Say ''
Write-Host ' 本脚本从不打印 Cookie 内容，这份输出可以直接分享。' -ForegroundColor DarkGray
Say ''
