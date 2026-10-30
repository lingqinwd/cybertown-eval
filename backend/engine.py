from __future__ import annotations
from typing import Any
from .memory import MemoryBackend
from .world import World
from .dialogue import DialogueModel
class TownEngine:
    def __init__(self): self.world=World(); self.memory=MemoryBackend.create(); self.dialogue=DialogueModel(); self.mode=self.dialogue.active_provider
    def talk(self,npc_id,message)->dict[str,Any]:
        if npc_id not in self.world.npcs: raise ValueError("unknown npc")
        if not self.world.nearby(npc_id): raise ValueError("请先走到 NPC 附近")
        npc=self.world.npcs[npc_id]; recalled=self.memory.search(npc.memories,message); before=npc.affinity
        delta=2 if any(w in message for w in ["谢谢","帮助","完成","你好"]) else 0
        if any(w in message for w in ["讨厌","滚","骗子"]): delta=-2
        npc.affinity=max(-100,min(100,npc.affinity+delta))
        generated=self.dialogue.reply(npc_name=npc.name,npc_role=npc.role,message=message,memories=npc.memories)
        reply=generated.text or (f"{npc.name}记得你之前提到过相关事情。作为{npc.role}，我会先把这件事记下来，再和你一起想办法。" if recalled else f"我是{npc.name}，负责{npc.role}。我听到了你的话：‘{message[:42]}’。你愿意先从今天的小镇任务开始吗？")
        self.memory.add(npc.memories,f"玩家说：{message}；NPC回应：{reply}","player_dialogue",.7 if delta else .4); self.world.log("dialogue",f"{npc.name}：{reply}",npc_id)
        return {"reply":reply,"npc_id":npc_id,"affinity_before":before,"affinity_after":npc.affinity,"recalled_memories":recalled,"provider":generated.provider,"state":self.world.snapshot()}
