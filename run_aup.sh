#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_aup.sh v2 - AUP side runner for CyberTown memory ablation (Qwen2.5-1.5B)
#
#   bash run_aup.sh check              # 环境自检
#   bash run_aup.sh off                # 第一组:无记忆
#   bash run_aup.sh collect off        # 归档第一组数据
#   bash run_aup.sh on                 # 第二组:有记忆(含前置检查 + 冒烟)
#   SKIP_SMOKE=1 bash run_aup.sh on    # 跳过冒烟(清空记忆后正式开测用)
#   WIPE_QDRANT=1 bash run_aup.sh on   # 启动前删除 Qdrant 集合,彻底干净
#   bash run_aup.sh stop               # 停后端
#   STOP_MODEL=1 bash run_aup.sh stop  # 连模型服务一起停
#
# v2 相对 v1 的修正:
#   1. 记忆组默认 export EMBED_MODEL_TYPE=local(hello-agents 默认是 dashscope,
#      且回退链复用 model_name 会导致 local/tfidf 全部失败)
#   2. Qdrant 地址按 hello-agents 的真实默认值(localhost:6333)做可达性检查
#   3. 冒烟测试硬拦截"模拟模式"回复(agent=None 时接口仍返回 success:true)
#   4. 支持 SKIP_SMOKE / WIPE_QDRANT,避免冒烟写入污染正式实验的记忆库
#   5. EMBED_MODEL_NAME 被误设时给出警告(例如设成 text-embedding-v3)
# ---------------------------------------------------------------------------
set -uo pipefail

REPO_DIR="${REPO_DIR:-$HOME/cybertown-eval}"
BACKEND="$REPO_DIR/backend"
EXP="$REPO_DIR/experiments"
MODEL_PORT="${MODEL_PORT:-8001}"
API_PORT="${API_PORT:-8000}"
TODAY="$(date +%F)"
STAMP="$(date +%F-%H%M%S)"

c_ok()   { printf '\033[32m%s\033[0m\n' "$*"; }
c_warn() { printf '\033[33m%s\033[0m\n' "$*"; }
c_err()  { printf '\033[31m%s\033[0m\n' "$*"; }
hr()     { printf '%s\n' "--------------------------------------------------------"; }
die()    { c_err "$*"; exit 1; }

load_dotenv_value() {
    local key="$1" val=""
    if [ -f "$BACKEND/.env" ]; then
        val="$(grep -E "^${key}=" "$BACKEND/.env" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"' ')"
    fi
    printf '%s' "$val"
}

# ---------------------------------------------------------------------------
check_torch() {
    hr; echo "[1/4] PyTorch / GPU"
    python3 - <<'PY' 2>&1 || return 1
import sys
try:
    import torch
except Exception as exc:
    print("  torch 导入失败:", exc); sys.exit(1)
print("  torch   :", torch.__version__)
print("  path    :", torch.__file__)
print("  hip     :", torch.version.hip)
print("  gpu     :", torch.cuda.is_available(), "count =", torch.cuda.device_count())
if torch.cuda.is_available():
    print("  device  :", torch.cuda.get_device_name(0))
if torch.version.hip is None:
    print("  !! torch 不是 ROCm 构建,GPU 不可用")
    sys.exit(2)
PY
    local rc=$?
    [ $rc -eq 0 ] && c_ok "  torch/GPU 正常" || c_err "  torch/GPU 异常 (rc=$rc)"
    return $rc
}

check_model_server() {
    hr; echo "[2/4] 模型服务 :$MODEL_PORT"
    local out
    out="$(curl -s --max-time 10 "http://127.0.0.1:$MODEL_PORT/v1/models" || true)"
    if [ -z "$out" ]; then
        c_err "  $MODEL_PORT 无响应 → 另开一个终端运行: python3 serve_qwen.py"
        return 1
    fi
    echo "  $out" | head -c 300; echo
    c_ok "  模型服务在线"
    return 0
}

check_backend() {
    hr; echo "[3/4] 后端 :$API_PORT"
    local out
    out="$(curl -s --max-time 5 "http://127.0.0.1:$API_PORT/runtime/config" || true)"
    if [ -z "$out" ]; then
        c_warn "  后端未运行"
        return 0
    fi
    echo "  $out"
    c_ok "  后端在线"
    return 0
}

resolve_qdrant() {
    QURL="${QDRANT_URL:-$(load_dotenv_value QDRANT_URL)}"
    [ -z "$QURL" ] && QURL="http://127.0.0.1:6333"   # hello-agents 的真实默认
    QKEY="${QDRANT_API_KEY:-$(load_dotenv_value QDRANT_API_KEY)}"
    QCOLL="${QDRANT_COLLECTION:-$(load_dotenv_value QDRANT_COLLECTION)}"
    [ -z "$QCOLL" ] && QCOLL="cybertown_aup_qwen_memory"
}

preflight_memory() {
    hr; echo "[4/4] 记忆组前置检查"
    local rc=0

    # --- embedding ---
    local embed="${EMBED_MODEL_TYPE:-$(load_dotenv_value EMBED_MODEL_TYPE)}"
    if [ -z "$embed" ]; then
        c_warn "  EMBED_MODEL_TYPE 未设置 → hello-agents 默认走 dashscope(本机未装),会全线失败"
        c_warn "    本脚本会自动补成 local"
        export EMBED_MODEL_TYPE=local
        embed=local
    fi
    echo "  EMBED_MODEL_TYPE = $embed"

    local emname="${EMBED_MODEL_NAME:-$(load_dotenv_value EMBED_MODEL_NAME)}"
    if [ -n "$emname" ] && [ "$embed" = "local" ] && printf '%s' "$emname" | grep -qv 'all-MiniLM'; then
        c_err "  EMBED_MODEL_NAME=$emname 与 EMBED_MODEL_TYPE=local 冲突(会去加载同名的 ST 模型)"
        c_err "    这是 hello-agents 已知缺陷,请 unset EMBED_MODEL_NAME"
        rc=1
    fi

    if [ "$embed" = "local" ]; then
        if python3 -c "import sentence_transformers" 2>/dev/null; then
            c_ok "  sentence-transformers 可导入"
        else
            c_err "  缺 sentence-transformers: pip install sentence-transformers"
            rc=1
        fi
        # 真正加载一次,不能只验 import
        if python3 - <<'PY' 2>/dev/null
from sentence_transformers import SentenceTransformer
m = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
assert len(m.encode('probe')) == 384
PY
        then
            c_ok "  MiniLM 实际加载并编码成功 (dim=384)"
        else
            c_err "  MiniLM 加载失败,可能需要镜像: export HF_ENDPOINT=https://hf-mirror.com"
            rc=1
        fi
    fi

    # --- qdrant ---
    resolve_qdrant
    echo "  QDRANT_URL        = $QURL"
    echo "  QDRANT_COLLECTION = $QCOLL"
    if ! python3 -c "import qdrant_client" 2>/dev/null; then
        c_err "  缺 qdrant-client: pip install qdrant-client"
        rc=1
    fi
    local code
    if [ -n "$QKEY" ]; then
        code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -H "api-key: $QKEY" "$QURL/collections" || echo 000)"
    else
        code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$QURL/collections" || echo 000)"
    fi
    if [ "$code" = "200" ]; then
        c_ok "  Qdrant 可达"
    else
        c_err "  Qdrant 不可达: HTTP $code ($QURL)"
        c_err "    本地启动: QDRANT__STORAGE__STORAGE_PATH=\$HOME/qdrant_data ./qdrant"
        rc=1
    fi

    if [ $rc -ne 0 ] && [ "${FORCE:-0}" = "1" ]; then
        c_warn "  FORCE=1,忽略问题继续"
        return 0
    fi
    [ $rc -eq 0 ] && c_ok "  记忆组前置检查通过" || c_err "  前置检查未通过,修好再测(或 FORCE=1 跳过)"
    return $rc
}

# ---------------------------------------------------------------------------
rotate_logs() {
    local mode="$1"
    mkdir -p "$BACKEND/logs"
    for f in "$BACKEND/logs/metrics_${TODAY}.csv" "$BACKEND/logs/dialogue_${TODAY}.log"; do
        if [ -s "$f" ]; then
            mv "$f" "${f}.prev-${mode}-${STAMP}"
            echo "  归档旧日志: $(basename "$f")"
        fi
    done
}

start_api() {
    local mode="$1"

    pkill -f "uvicorn main:app" 2>/dev/null && { echo "  已停止旧后端"; sleep 2; }

    if [ "$mode" = "on" ]; then
        preflight_memory || die "记忆组前置检查失败,拒绝启动"
        export EMBED_MODEL_TYPE="${EMBED_MODEL_TYPE:-local}"
        export QDRANT_URL="$QURL"
        export QDRANT_COLLECTION="$QCOLL"
        [ -n "$QKEY" ] && export QDRANT_API_KEY="$QKEY"

        if [ "${WIPE_QDRANT:-0}" = "1" ]; then
            if [ -n "$QKEY" ]; then
                curl -s -X DELETE -H "api-key: $QKEY" "$QURL/collections/$QCOLL" >/dev/null 2>&1
            else
                curl -s -X DELETE "$QURL/collections/$QCOLL" >/dev/null 2>&1
            fi
            echo "  已删除 Qdrant 集合 $QCOLL(后端启动时会自动重建)"
        fi

        if [ "${FRESH_MEMORY:-1}" = "1" ]; then
            rm -rf "$BACKEND/memory_data"
            mkdir -p "$BACKEND/memory_data"
            echo "  已清空 backend/memory_data"
        fi
    fi

    rotate_logs "$mode"

    export MODEL_PROFILE=aup_local
    export LLM_PROVIDER=openai
    export LLM_MODEL_ID="Qwen/Qwen2.5-1.5B-Instruct"
    export LLM_API_KEY=local
    export LLM_BASE_URL="http://127.0.0.1:${MODEL_PORT}/v1"
    export MEMORY_MODE="$mode"
    export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

    cd "$BACKEND" || die "找不到 $BACKEND"
    nohup python3 -m uvicorn main:app --host 0.0.0.0 --port "$API_PORT" \
        > "aup-qwen-memory-${mode}.log" 2>&1 &
    local pid=$!
    echo "  后端启动中 (pid=$pid, MEMORY_MODE=$mode) ..."

    local i status=""
    for i in $(seq 1 60); do
        status="$(curl -s --max-time 2 "http://127.0.0.1:$API_PORT/health" || true)"
        [ -n "$status" ] && break
        sleep 1
    done
    if [ -z "$status" ]; then
        c_err "后端 60 秒内没起来,日志尾部:"
        tail -40 "aup-qwen-memory-${mode}.log"
        exit 1
    fi

    echo "  /health: $status"
    local cfg
    cfg="$(curl -s "http://127.0.0.1:$API_PORT/runtime/config")"
    echo "  /runtime/config: $cfg"
    if ! printf '%s' "$cfg" | grep -q "\"memory_mode\":\"$mode\""; then
        c_err "memory_mode 与预期不符(期望 $mode),检查 backend/.env"
        tail -20 "aup-qwen-memory-${mode}.log"
        exit 1
    fi
    c_ok "  后端就绪,memory_mode=$mode"

    # 记忆初始化失败会把 agent 置 None 并静默降级,必须在启动阶段就拦住
    if grep -q "Agent创建失败" "aup-qwen-memory-${mode}.log"; then
        c_err "  检测到 Agent 创建失败(agent=None,会降级为模拟模式):"
        grep "Agent创建失败" "aup-qwen-memory-${mode}.log" | head -5
        exit 1
    fi
}

# ---------------------------------------------------------------------------
smoke() {
    local mode="$1"
    hr; echo "冒烟测试 (memory_mode=$mode)"
    local t0 t1 payload resp
    payload='{"npc_name":"李四","message":"你好，我叫小林，我正在做一个赛博小镇课程项目，请记住我的名字和项目名称。"}'
    t0=$(date +%s%3N)
    resp="$(curl -s --max-time 300 -X POST "http://127.0.0.1:$API_PORT/chat" \
        -H 'Content-Type: application/json' -d "$payload" || true)"
    t1=$(date +%s%3N)
    echo "  耗时: $((t1 - t0)) ms"
    if [ -z "$resp" ]; then
        c_err "  /chat 无响应"
        tail -30 "$BACKEND/aup-qwen-memory-${mode}.log"
        return 1
    fi
    echo "  响应: $(printf '%s' "$resp" | head -c 400)"

    if printf '%s' "$resp" | grep -q "模拟模式"; then
        c_err "  === 后端处于模拟模式,回复不是模型生成的,数据无效 ==="
        grep -E "❌|创建失败" "$BACKEND/aup-qwen-memory-${mode}.log" | head -5
        return 1
    fi
    c_ok "  链路通,回复来自真实模型"

    if [ "$mode" = "on" ]; then
        hr; echo "记忆写入验证"
        c_warn "  注意: /npcs/{name}/memories 对工作记忆恒返回空"
        c_warn "        (agents.py 用 query=\"\" 检索,hello-agents 里 final_score>0 会把全零分数全过滤掉)"
        c_warn "        真实判据看后端日志,不看那个接口"
        if grep -q "已保存到" "$BACKEND/aup-qwen-memory-${mode}.log"; then
            c_ok "  日志确认: 对话已写入工作记忆"
        else
            c_err "  日志里没有'对话已保存到' → 记忆未写入"
            grep -E "❌|失败|error" "$BACKEND/aup-qwen-memory-${mode}.log" | tail -5
            return 1
        fi
        local recall
        recall="$(grep -oE '检索到[0-9]+条' "$BACKEND/aup-qwen-memory-${mode}.log" | tail -1)"
        echo "  最近一次召回: ${recall:-无记录}"
        if [ "$recall" = "检索到0条" ]; then
            c_warn "  召回 0 —— 中文在 TF-IDF 分词下可能完全匹配不上"
            c_warn "  若持续为 0,记忆组会退化成无记忆组,需打补丁后再测"
        fi
    fi
    return 0
}

# ---------------------------------------------------------------------------
collect() {
    local mode="$1"
    hr; echo "归档 $mode 组数据"
    mkdir -p "$EXP"
    local m="$BACKEND/logs/metrics_${TODAY}.csv"
    local d="$BACKEND/logs/dialogue_${TODAY}.log"
    if [ -s "$m" ]; then
        cp "$m" "$EXP/aup_qwen_memory_${mode}_metrics.csv"
        c_ok "  metrics  → experiments/aup_qwen_memory_${mode}_metrics.csv"
        echo "    行数: $(( $(wc -l < "$m") - 1 )) (不含表头)"
    else
        c_err "  没找到: $m"
    fi
    if [ -s "$d" ]; then
        cp "$d" "$EXP/aup_qwen_memory_${mode}_dialogue.log"
        c_ok "  dialogue → experiments/aup_qwen_memory_${mode}_dialogue.log"
    else
        c_warn "  没找到 dialogue 日志(若曾在后端运行时删除过,句柄指向已删文件,属正常)"
    fi
    ls -lh "$EXP" | sed 's/^/    /'
}

stop_api() {
    hr; echo "停止服务"
    pkill -f "uvicorn main:app" 2>/dev/null && c_ok "  后端已停" || echo "  后端本来就没运行"
    if [ "${STOP_MODEL:-0}" = "1" ]; then
        pkill -f "serve_qwen.py" 2>/dev/null && c_ok "  模型服务已停" || echo "  模型服务本来就没运行"
    else
        c_warn "  模型服务仍在运行;一起停请用 STOP_MODEL=1 bash run_aup.sh stop"
    fi
}

# ---------------------------------------------------------------------------
case "${1:-}" in
    check)
        rc=0
        check_torch || rc=1
        check_model_server || rc=1
        check_backend
        hr
        [ $rc -eq 0 ] && c_ok "自检通过" || c_err "自检未通过,先修上面的问题"
        exit $rc
        ;;
    off|on)
        MODE="$1"
        hr; echo "===== 启动实验: memory_mode=$MODE ====="
        check_torch || die "torch/GPU 异常"
        check_model_server || die "模型服务未运行: 另开终端运行 python3 serve_qwen.py"
        start_api "$MODE"
        if [ "${SKIP_SMOKE:-0}" = "1" ]; then
            c_warn "  SKIP_SMOKE=1,跳过冒烟测试(记忆库保持干净)"
        else
            smoke "$MODE" || die "冒烟测试失败,不要开始六轮测试"
        fi
        hr
        c_ok "可以开始六轮测试了"
        echo "  浏览器控制台跑 browser_turns.js,GROUP=\"$MODE\""
        echo "  测完执行:  bash run_aup.sh collect $MODE"
        ;;
    collect)
        MODE="${2:-}"
        [ -z "$MODE" ] && die "用法: bash run_aup.sh collect off|on"
        collect "$MODE"
        ;;
    stop)
        stop_api
        ;;
    *)
        cat <<'EOF'
用法:
  bash run_aup.sh check                 环境自检
  bash run_aup.sh off                   第一组:无记忆
  bash run_aup.sh collect off           归档第一组
  bash run_aup.sh on                    第二组:有记忆(含前置检查+冒烟)
  SKIP_SMOKE=1 bash run_aup.sh on       跳过冒烟(正式开测用,保持记忆库干净)
  WIPE_QDRANT=1 bash run_aup.sh on      启动前删集合
  bash run_aup.sh collect on            归档第二组
  bash run_aup.sh stop                  停后端
  STOP_MODEL=1 bash run_aup.sh stop     连模型服务一起停
  FRESH_MEMORY=0 bash run_aup.sh on     保留 memory_data
EOF
        ;;
esac
