from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
@dataclass
class NPC:
    npc_id:str; name:str; role:str; x:int; y:int; color:str; affinity:int=0
    memories:list[dict[str,Any]]=field(default_factory=list)
    tasks:list[dict[str,Any]]=field(default_factory=list)
@dataclass
class Player:
    x:int=3; y:int=5; energy:int=100
class World:
    width=15; height=10
    def __init__(self):
        self.player=Player(); self.npcs={
            "lina":NPC("lina","林娜","图书管理员",5,3,"#7c5cff",tasks=[{"id":"book","title":"寻找遗失的书","done":False}]),
            "kai":NPC("kai","凯","修理工",10,6,"#00a8a8",tasks=[{"id":"part","title":"收集一个零件","done":False}]),
            "mira":NPC("mira","米拉","社区医生",3,8,"#f06b9a",tasks=[{"id":"care","title":"询问社区状况","done":False}]),
            "noah":NPC("noah","诺亚","咖啡店主",12,2,"#f59e0b",tasks=[{"id":"coffee","title":"分享今天的见闻","done":False}])}
        self.events=[]; self.tick=0; self.log("world_started","赛博小镇已启动")
    def log(self,event_type,text,npc_id=None):
        self.tick+=1; self.events.insert(0,{"tick":self.tick,"type":event_type,"text":text,"npc_id":npc_id,"time":datetime.now(timezone.utc).isoformat()}); self.events=self.events[:80]
    def nearby(self,npc_id,distance=2):
        n=self.npcs[npc_id]; return abs(self.player.x-n.x)+abs(self.player.y-n.y)<=distance
    def move(self,dx,dy):
        self.player.x=max(0,min(self.width-1,self.player.x+dx)); self.player.y=max(0,min(self.height-1,self.player.y+dy)); self.log("move",f"玩家移动到 ({self.player.x}, {self.player.y})"); return self.snapshot()
    def snapshot(self):
        return {"width":self.width,"height":self.height,"tick":self.tick,"player":self.player.__dict__,"npcs":[n.__dict__ for n in self.npcs.values()],"events":self.events[:20]}
