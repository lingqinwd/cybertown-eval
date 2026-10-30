from __future__ import annotations
import os,time
from dataclasses import dataclass
from typing import Any
@dataclass
class MemoryBackend:
    model_name:str; device:str; encoder:Any=None
    @classmethod
    def create(cls):
        name=os.getenv("CYBERTOWN_EMBEDDING_MODEL","BAAI/bge-small-zh-v1.5"); requested=os.getenv("CYBERTOWN_DEVICE","auto"); device=requested; encoder=None
        try:
            from sentence_transformers import SentenceTransformer
            if requested=="auto":
                import torch; device="cuda" if torch.cuda.is_available() else "cpu"
            encoder=SentenceTransformer(name,device=device)
        except Exception:
            device="fallback"
        return cls(name,device,encoder)
    def add(self,memories,text,source,importance=.5):
        vector=self.encoder.encode(text,normalize_embeddings=True).tolist() if self.encoder else None
        memories.append({"text":text,"source":source,"importance":importance,"created_at":time.time(),"embedding":vector})
    def search(self,memories,query,limit=4):
        if not memories:return []
        if not self.encoder:return sorted(memories,key=lambda m:(m.get("importance",0),m.get("created_at",0)),reverse=True)[:limit]
        import numpy as np
        q=self.encoder.encode(query,normalize_embeddings=True); scored=[]
        for m in memories:
            v=m.get("embedding"); scored.append((float(np.dot(q,np.array(v))) if v else 0.0,m))
        return [m for _,m in sorted(scored,key=lambda x:x[0],reverse=True)[:limit]]
