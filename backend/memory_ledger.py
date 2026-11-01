"""可追溯记忆账本（traceable memory ledger）。

为什么单独一层
--------------
底层 `hello_agents` 的 `MemoryManager` 只存「内容 + 类型 + 重要性」，没有来源、可信度，
也不能合并 / 纠正 / 软删除。而这三件事恰好是判断"记忆能不能信"的关键。

本模块是**与底层并行的账本**：`agents.py` 每轮把对话按来源写进来，对外提供
"列举 / 纠正 / 遗忘 / 合并 / 调可信度 / 按可信度过滤"。

三条设计原则
------------
1. **来源决定先验可信度**（`SOURCE_CREDIBILITY`）。玩家说的可能记错，模型生成的已知会编，
   场景注入的未经任何证实 —— 三者不该等价。
2. **遗忘是软删除**。`status` 变成 `forgotten` 而不是物理删除，审计链完整。
3. **可信度必须能影响行为，否则只是标签**。`render_context()` 会按阈值过滤，
   低于阈值的记录**不会进入 prompt** —— 这才是"可追溯"的价值。

已知边界（写清楚，不假装）
--------------------------
* 可信度是**来源先验 + 显式校正**，没有做自然语言层面的事实抽取与自动比对。
  「这条记忆和世界状态矛盾」目前要靠调用方（场景判据 / 人工）判定。
* 每个 (NPC, 玩家) 一个 JSON 文件，规模到万级需要换存储。当前是课程项目量级。
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# 来源 → 先验可信度
SOURCE_CREDIBILITY: Dict[str, float] = {
    "event.world": 0.95,      # 来自权威状态 / 审计事件
    "dialogue.player": 0.60,  # 玩家自述，可能记错也可能撒谎
    "dialogue.npc": 0.50,     # 模型生成，已知会编造
    "injected": 0.20,         # 场景注入 / 外部供给，未经证实
    "manual": 0.60,           # 调用方显式写入
}

STATUS_ACTIVE = "active"
STATUS_CORRECTED = "corrected"
STATUS_FORGOTTEN = "forgotten"
STATUS_MERGED = "merged"

VALID_STATUS = {STATUS_ACTIVE, STATUS_CORRECTED, STATUS_FORGOTTEN, STATUS_MERGED}


@dataclass
class MemoryRecord:
    record_id: str
    npc: str
    player: str
    content: str
    source: str
    importance: float = 0.5
    credibility: float = 0.5
    created_at: str = ""
    status: str = STATUS_ACTIVE
    corrected_from: Optional[str] = None
    merged_into: Optional[str] = None
    notes: str = ""
    seq: int = 0              # 单调序号：同一秒内写入也能稳定排序

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    @property
    def active(self) -> bool:
        return self.status == STATUS_ACTIVE


def _clamp01(value: float, default: float = 0.5) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, v))


class MemoryLedger:
    """单个 (NPC, 玩家) 的记忆账本，落盘为一个 JSON 文件。"""

    def __init__(self, npc: str, player: str, path: Path):
        self.npc = npc
        self.player = player
        self.path = Path(path)
        self._lock = threading.RLock()
        self._records: Dict[str, MemoryRecord] = {}
        self.load()

    # -------------------------------------------------- 持久化
    def load(self) -> None:
        with self._lock:
            self._records = {}
            if not self.path.exists():
                return
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return
            allowed = set(MemoryRecord.__dataclass_fields__)
            for idx, item in enumerate(data.get("records") or [], 1):
                if not isinstance(item, dict) or not item.get("record_id"):
                    continue
                clean = {k: v for k, v in item.items() if k in allowed}
                clean.setdefault("npc", self.npc)
                clean.setdefault("player", self.player)
                clean.setdefault("status", STATUS_ACTIVE)
                clean.setdefault("seq", idx)
                if clean["status"] not in VALID_STATUS:
                    clean["status"] = STATUS_ACTIVE
                try:
                    self._records[clean["record_id"]] = MemoryRecord(**clean)
                except TypeError:
                    continue

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "npc": self.npc,
            "player": self.player,
            "records": [r.to_dict() for r in self._records.values()],
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # -------------------------------------------------- 写入
    def add(
        self,
        content: str,
        source: str = "dialogue.npc",
        importance: float = 0.5,
        credibility: Optional[float] = None,
        notes: str = "",
    ) -> MemoryRecord:
        text = (content or "").strip()
        if not text:
            raise ValueError("记忆内容不能为空")
        prior = SOURCE_CREDIBILITY.get(source, 0.5)
        record = MemoryRecord(
            record_id=str(uuid.uuid4()),
            npc=self.npc,
            player=self.player,
            content=text,
            source=source,
            importance=_clamp01(importance),
            credibility=_clamp01(prior if credibility is None else credibility),
            created_at=datetime.now().isoformat(timespec="seconds"),
            notes=notes,
            seq=max((r.seq for r in self._records.values()), default=0) + 1,
        )
        with self._lock:
            self._records[record.record_id] = record
            self._save()
        return record

    # -------------------------------------------------- 纠正
    def correct(self, record_id: str, new_content: str, reason: str = "") -> MemoryRecord:
        """把一条记忆标记为"已纠正"，并写入一条新的替代记录。"""
        text = (new_content or "").strip()
        if not text:
            raise ValueError("纠正后的内容不能为空")
        with self._lock:
            old = self._records.get(record_id)
            if old is None:
                raise KeyError(f"记忆不存在: {record_id}")
            old.status = STATUS_CORRECTED
            old.notes = (old.notes + f" | 已纠正: {reason}").strip(" |")
            new = MemoryRecord(
                record_id=str(uuid.uuid4()),
                npc=self.npc,
                player=self.player,
                content=text,
                source=old.source,
                importance=old.importance,
                # 纠正后的内容可信度不低于原记录，且不低于手动写入的先验
                credibility=max(old.credibility, SOURCE_CREDIBILITY["manual"]),
                created_at=datetime.now().isoformat(timespec="seconds"),
                corrected_from=old.record_id,
                notes=f"纠正自 {old.record_id}" + (f": {reason}" if reason else ""),
                seq=max((r.seq for r in self._records.values()), default=0) + 1,
            )
            self._records[new.record_id] = new
            self._save()
            return new

    # -------------------------------------------------- 遗忘
    def forget(self, record_id: str, reason: str = "") -> bool:
        with self._lock:
            rec = self._records.get(record_id)
            if rec is None:
                raise KeyError(f"记忆不存在: {record_id}")
            if rec.status == STATUS_FORGOTTEN:
                return False
            rec.status = STATUS_FORGOTTEN
            rec.notes = (rec.notes + f" | 已遗忘: {reason or '未说明'}").strip(" |")
            self._save()
            return True

    # -------------------------------------------------- 合并
    def merge(self, record_ids: List[str], keep_id: str) -> MemoryRecord:
        """把多条记忆合并进 keep_id：其余标记为 merged，保留最高的重要性与可信度。"""
        with self._lock:
            keep = self._records.get(keep_id)
            if keep is None:
                raise KeyError(f"记忆不存在: {keep_id}")
            merged_count = 0
            for rid in record_ids:
                if rid == keep_id:
                    continue
                rec = self._records.get(rid)
                if rec is None or rec.status != STATUS_ACTIVE:
                    continue
                rec.status = STATUS_MERGED
                rec.merged_into = keep_id
                keep.importance = max(keep.importance, rec.importance)
                keep.credibility = max(keep.credibility, rec.credibility)
                merged_count += 1
            keep.notes = (keep.notes + f" | 合并 {merged_count} 条").strip(" |")
            self._save()
            return keep

    # -------------------------------------------------- 可信度校正
    def set_credibility(self, record_id: str, value: float, reason: str = "") -> MemoryRecord:
        with self._lock:
            rec = self._records.get(record_id)
            if rec is None:
                raise KeyError(f"记忆不存在: {record_id}")
            rec.credibility = _clamp01(value, rec.credibility)
            if reason:
                rec.notes = (rec.notes + f" | 可信度校正: {reason}").strip(" |")
            self._save()
            return rec

    def flag_disputed(self, record_id: str, reason: str, drop_to: float = 0.05) -> MemoryRecord:
        """标记为"与世界状态矛盾"，并把可信度压到很低（仍保留记录）。"""
        return self.set_credibility(record_id, drop_to, f"与权威状态矛盾: {reason}")

    # -------------------------------------------------- 查询
    def get(self, record_id: str) -> Optional[MemoryRecord]:
        with self._lock:
            return self._records.get(record_id)

    def active(self, min_credibility: float = 0.0) -> List[MemoryRecord]:
        with self._lock:
            items = [
                r for r in self._records.values()
                if r.active and r.credibility >= min_credibility - 1e-9
            ]
        return sorted(items, key=lambda r: (r.seq, r.created_at, r.record_id))

    def all_records(self, status: Optional[str] = None) -> List[MemoryRecord]:
        with self._lock:
            items = list(self._records.values())
        if status:
            items = [r for r in items if r.status == status]
        return sorted(items, key=lambda r: (r.seq, r.created_at, r.record_id))

    # -------------------------------------------------- 渲染进 prompt
    def render_context(self, limit: int = 5, min_credibility: float = 0.5) -> str:
        """按可信度过滤后渲染成 prompt 片段。

        低于 `min_credibility` 的记录**不会出现** —— 这是本模块唯一真正影响模型行为的地方：
        场景注入的伪造记忆（先验 0.20）在默认阈值 0.5 下直接被挡掉。
        """
        items = self.active(min_credibility=min_credibility)
        if not items:
            return ""
        items = items[-limit:]
        lines = ["【可追溯记忆】"]
        for r in items:
            lines.append(
                f"- [{r.created_at}] ({r.source}, 可信度 {r.credibility:.2f}) {r.content}"
            )
        lines.append("")
        return "\n".join(lines)

    # -------------------------------------------------- 统计
    def stats(self) -> Dict[str, object]:
        with self._lock:
            records = list(self._records.values())
        by_status: Dict[str, int] = {}
        by_source: Dict[str, int] = {}
        for r in records:
            by_status[r.status] = by_status.get(r.status, 0) + 1
            by_source[r.source] = by_source.get(r.source, 0) + 1
        active = [r for r in records if r.active]
        return {
            "npc": self.npc,
            "player": self.player,
            "total": len(records),
            "by_status": by_status,
            "by_source": by_source,
            "active": len(active),
            "avg_credibility": round(
                sum(r.credibility for r in active) / len(active), 3
            ) if active else 0.0,
            "path": str(self.path),
        }


# ---------------------------------------------------------------- 工厂

_DEFAULT_BASE = Path(__file__).resolve().parent / "memory_data"


def ledger_for(npc: str, player: str, base_dir: Optional[Path] = None) -> MemoryLedger:
    """按 (NPC, 玩家) 取账本；路径与 hello_agents 的存储约定一致。"""
    base = Path(base_dir) if base_dir else _DEFAULT_BASE
    path = base / npc / player / "ledger.json"
    return MemoryLedger(npc=npc, player=player, path=path)
