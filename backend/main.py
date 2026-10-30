from __future__ import annotations
from pathlib import Path
from fastapi import FastAPI,HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from .engine import TownEngine
ROOT=Path(__file__).resolve().parents[1]; app=FastAPI(title="CyberTown-Eval"); engine=TownEngine(); app.mount("/static",StaticFiles(directory=ROOT/"frontend"),name="static")
GODOT_WEB=ROOT/"godot_web"
if GODOT_WEB.exists(): app.mount("/godot",StaticFiles(directory=GODOT_WEB,html=True),name="godot")
class MoveRequest(BaseModel): dx:int=Field(ge=-1,le=1); dy:int=Field(ge=-1,le=1)
class TalkRequest(BaseModel): npc_id:str; message:str=Field(min_length=1,max_length=500)
@app.get("/")
def index(): return FileResponse(ROOT/"frontend"/"index.html")
@app.get("/api/state")
def state(): return {"state":engine.world.snapshot(),"memory_backend":{"model":engine.memory.model_name,"device":engine.memory.device},"mode":engine.mode,"llm_provider":engine.dialogue.active_provider,"llm_model":engine.dialogue.model}
@app.post("/api/move")
def move(req:MoveRequest): return {"state":engine.world.move(req.dx,req.dy)}
@app.post("/api/talk")
def talk(req:TalkRequest):
    try:return engine.talk(req.npc_id,req.message)
    except ValueError as exc:raise HTTPException(status_code=400,detail=str(exc)) from exc
@app.post("/api/reset")
def reset():
    global engine; engine=TownEngine(); return state()
if __name__=="__main__":
    import uvicorn; uvicorn.run("backend.main:app",host="0.0.0.0",port=8000,reload=False)
