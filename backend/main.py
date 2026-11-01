"""赛博小镇 FastAPI 后端主程序"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn
import time
from logger import log_metrics_csv

from config import settings
from models import (
    ChatRequest, ChatResponse, 
    NPCStatusResponse, NPCListResponse, NPCInfo
)
from agents import get_npc_manager
from models import WorldActionRequest
from state_manager import get_state_manager

# 生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    print("\n" + "="*60)
    print("🎮 赛博小镇后端服务启动中...")
    print("="*60)
    
    # 验证配置
    settings.validate()
    
    # 初始化NPC管理器
    npc_manager = get_npc_manager()
    
    # 初始化并启动状态管理器
    state_manager = get_state_manager(settings.NPC_UPDATE_INTERVAL)
    await state_manager.start()
    
    print("\n✅ 所有服务已启动!")
    print(f"📡 API地址: http://{settings.API_HOST}:{settings.API_PORT}")
    print(f"📚 API文档: http://{settings.API_HOST}:{settings.API_PORT}/docs")
    print("="*60 + "\n")
    
    yield
    
    # 关闭时
    print("\n🛑 正在关闭服务...")
    await state_manager.stop()
    print("✅ 服务已关闭\n")

# 创建FastAPI应用
app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    description="赛博小镇 - 基于HelloAgents的AI NPC对话系统",
    lifespan=lifespan
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 获取全局实例
npc_manager = None
state_manager = None

def get_managers():
    """获取管理器实例"""
    global npc_manager, state_manager
    if npc_manager is None:
        npc_manager = get_npc_manager()
    if state_manager is None:
        state_manager = get_state_manager()
    return npc_manager, state_manager

# ==================== API路由 ====================

@app.get("/")
async def root():
    """根路径 - API信息"""
    return {
        "service": settings.API_TITLE,
        "version": settings.API_VERSION,
        "status": "running",
        "model_profile": settings.MODEL_PROFILE,
        "memory_mode": settings.MEMORY_MODE,
        "features": ["AI对话", "NPC记忆系统", "好感度系统", "批量状态更新"],
        "endpoints": {
            "docs": "/docs",
            "chat": "/chat",
            "npcs": "/npcs",
            "npcs_status": "/npcs/status",
            "npc_memories": "/npcs/{npc_name}/memories",
            "npc_affinity": "/npcs/{npc_name}/affinity",
            "all_affinities": "/affinities"
        }
    }

@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy", "timestamp": "now", "model_profile": settings.MODEL_PROFILE,
            "model": settings.LLM_MODEL_ID, "memory_mode": settings.MEMORY_MODE}

@app.get("/runtime/config")
async def runtime_config():
    """返回当前实验配置，不包含 API 密钥。"""
    return {"model_profile": settings.MODEL_PROFILE, "provider": settings.LLM_PROVIDER,
            "model": settings.LLM_MODEL_ID, "base_url": settings.LLM_BASE_URL,
            "memory_mode": settings.MEMORY_MODE,
            "action_proposal": settings.ACTION_PROPOSAL}

# ==================== 权威世界状态 ====================
@app.get("/world/state")
async def get_world_state_view(player_id: str = "player"):
    """世界状态快照（只读副本）与最近的审计事件。"""
    from world_state import get_world_state

    state = get_world_state()
    state.ensure_player(player_id)
    return {
        "player_id": player_id,
        "version": state.version,
        "state": state.snapshot(player_id),
        "events": state.recent_events(10),
    }


@app.get("/world/actions")
async def list_world_actions():
    """允许的动作白名单 —— 语言模型只能从中选择，不能自由发挥。"""
    from actions import describe_actions

    return {"actions": describe_actions()}


@app.post("/world/action")
async def post_world_action(request: WorldActionRequest):
    """提交一个世界动作。不在白名单、或前置条件不满足时一律拒绝并留审计记录。"""
    from actions import apply_action
    from world_state import get_world_state

    verdict = apply_action(get_world_state(), request.action, request.args, request.player_id)
    return verdict.to_dict()



@app.post("/chat", response_model=ChatResponse)
async def chat_with_npc(request: ChatRequest):
    """与NPC对话接口
    
    玩家与指定NPC进行实时对话,使用独立的Agent处理
    """
    npc_mgr, _ = get_managers()
    
    # 验证NPC是否存在
    npc_info = npc_mgr.get_npc_info(request.npc_name)
    if not npc_info:
        raise HTTPException(
            status_code=404,
            detail=f"NPC '{request.npc_name}' 不存在"
        )
    
    try:
        started = time.perf_counter()
        # 调用NPC Agent处理对话
        response_text = npc_mgr.chat(request.npc_name, request.message, request.player_id)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        metrics = dict(getattr(npc_mgr, "last_metrics", {}))
        metrics["latency_ms"] = elapsed_ms
        log_metrics_csv(metrics)
        
        return ChatResponse(
            npc_name=request.npc_name,
            npc_title=npc_info["title"],
            message=response_text,
            success=True,
            action=metrics.get("action")
        )
        
    except Exception as e:
        metrics = dict(getattr(npc_mgr, "last_metrics", {}))
        metrics.update({"model_profile": settings.MODEL_PROFILE,
                        "mode": "memory_on" if settings.MEMORY_MODE == "on" else "memory_off",
                        "npc": request.npc_name, "message": request.message,
                        "request_failed": True, "latency_ms": 0})
        log_metrics_csv(metrics)
        raise HTTPException(
            status_code=500,
            detail=f"对话处理失败: {str(e)}"
        )

@app.get("/npcs", response_model=NPCListResponse)
async def list_npcs():
    """获取所有NPC列表"""
    npc_mgr, _ = get_managers()
    
    npcs_data = npc_mgr.get_all_npcs()
    npcs = [NPCInfo(**npc) for npc in npcs_data]
    
    return NPCListResponse(
        npcs=npcs,
        total=len(npcs)
    )

@app.get("/npcs/status", response_model=NPCStatusResponse)
async def get_npcs_status():
    """获取所有NPC的当前状态
    
    返回批量生成的NPC对话内容,用于显示NPC的自主行为
    """
    _, state_mgr = get_managers()
    
    state = state_mgr.get_current_state()
    
    return NPCStatusResponse(
        dialogues=state["dialogues"],
        last_update=state["last_update"],
        next_update_in=state["next_update_in"]
    )

@app.post("/npcs/status/refresh")
async def refresh_npcs_status():
    """强制刷新NPC状态
    
    立即触发一次批量对话生成
    """
    _, state_mgr = get_managers()
    
    await state_mgr.force_update()
    state = state_mgr.get_current_state()
    
    return {
        "message": "NPC状态已刷新",
        "dialogues": state["dialogues"]
    }

@app.get("/npcs/{npc_name}")
async def get_npc_info(npc_name: str):
    """获取指定NPC的详细信息"""
    npc_mgr, state_mgr = get_managers()

    npc_info = npc_mgr.get_npc_info(npc_name)
    if not npc_info:
        raise HTTPException(
            status_code=404,
            detail=f"NPC '{npc_name}' 不存在"
        )

    # 添加当前对话
    current_dialogue = state_mgr.get_npc_dialogue(npc_name)
    npc_info["current_dialogue"] = current_dialogue

    return npc_info

@app.get("/npcs/{npc_name}/memories")
async def get_npc_memories(npc_name: str, limit: int = 10, player_id: str = "player"):
    """获取NPC的记忆列表

    Args:
        npc_name: NPC名称
        limit: 返回的记忆数量限制 (默认10条)

    Returns:
        NPC的记忆列表
    """
    npc_mgr, _ = get_managers()

    # 验证NPC是否存在
    npc_info = npc_mgr.get_npc_info(npc_name)
    if not npc_info:
        raise HTTPException(
            status_code=404,
            detail=f"NPC '{npc_name}' 不存在"
        )

    try:
        memories = npc_mgr.get_npc_memories(npc_name, player_id=player_id, limit=limit)

        return {
            "npc_name": npc_name,
            "player_id": player_id,
            "memories": memories,
            "total": len(memories)
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取记忆失败: {str(e)}"
        )

@app.delete("/npcs/{npc_name}/memories")
async def clear_npc_memories(npc_name: str, memory_type: str = None, player_id: str = "player"):
    """清空NPC的记忆 (用于测试)

    Args:
        npc_name: NPC名称
        memory_type: 记忆类型 (working/episodic), 不指定则清空所有

    Returns:
        操作结果
    """
    npc_mgr, _ = get_managers()

    # 验证NPC是否存在
    npc_info = npc_mgr.get_npc_info(npc_name)
    if not npc_info:
        raise HTTPException(
            status_code=404,
            detail=f"NPC '{npc_name}' 不存在"
        )

    try:
        npc_mgr.clear_npc_memory(npc_name, player_id=player_id, memory_type=memory_type)

        return {
            "message": f"已清空{npc_name}（玩家 {player_id}）的记忆",
            "npc_name": npc_name,
            "player_id": player_id,
            "memory_type": memory_type or "all"
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"清空记忆失败: {str(e)}"
        )

@app.get("/npcs/{npc_name}/affinity")
async def get_npc_affinity(npc_name: str, player_id: str = "player"):
    """获取NPC对玩家的好感度

    Args:
        npc_name: NPC名称
        player_id: 玩家ID (默认为"player")

    Returns:
        好感度信息
    """
    npc_mgr, _ = get_managers()

    # 验证NPC是否存在
    npc_info = npc_mgr.get_npc_info(npc_name)
    if not npc_info:
        raise HTTPException(
            status_code=404,
            detail=f"NPC '{npc_name}' 不存在"
        )

    try:
        affinity_info = npc_mgr.get_npc_affinity(npc_name, player_id)

        return {
            "npc_name": npc_name,
            "player_id": player_id,
            **affinity_info
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取好感度失败: {str(e)}"
        )

@app.get("/affinities")
async def get_all_affinities(player_id: str = "player"):
    """获取所有NPC对玩家的好感度

    Args:
        player_id: 玩家ID (默认为"player")

    Returns:
        所有NPC的好感度信息
    """
    npc_mgr, _ = get_managers()

    try:
        affinities = npc_mgr.get_all_affinities(player_id)

        return {
            "player_id": player_id,
            "affinities": affinities
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取好感度失败: {str(e)}"
        )

@app.put("/npcs/{npc_name}/affinity")
async def set_npc_affinity(npc_name: str, affinity: float, player_id: str = "player"):
    """设置NPC对玩家的好感度 (用于测试)

    Args:
        npc_name: NPC名称
        affinity: 好感度值 (0-100)
        player_id: 玩家ID (默认为"player")

    Returns:
        操作结果
    """
    npc_mgr, _ = get_managers()

    # 验证NPC是否存在
    npc_info = npc_mgr.get_npc_info(npc_name)
    if not npc_info:
        raise HTTPException(
            status_code=404,
            detail=f"NPC '{npc_name}' 不存在"
        )

    # 验证好感度范围
    if affinity < 0 or affinity > 100:
        raise HTTPException(
            status_code=400,
            detail="好感度必须在0-100之间"
        )

    try:
        npc_mgr.set_npc_affinity(npc_name, affinity, player_id)
        affinity_info = npc_mgr.get_npc_affinity(npc_name, player_id)

        return {
            "message": f"已设置{npc_name}对玩家的好感度",
            "npc_name": npc_name,
            "player_id": player_id,
            **affinity_info
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"设置好感度失败: {str(e)}"
        )

# ==================== 主程序入口 ====================

if __name__ == "__main__":
    print("\n🚀 启动赛博小镇后端服务...")
    print(f"📍 监听地址: {settings.API_HOST}:{settings.API_PORT}")
    print(f"📖 访问文档: http://localhost:{settings.API_PORT}/docs\n")
    
    uvicorn.run(
        "main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=True,  # 开发模式自动重载
        log_level="info"
    )
