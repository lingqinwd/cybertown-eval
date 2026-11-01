"""权威世界状态（authoritative world state）。

设计约束
--------
1. **只有后端能改状态。** 语言模型无法直接写这里，只能通过 ``actions.py`` 的白名单
   动作间接影响 —— 动作要过前置校验，不通过就不生效。
2. **全部确定性。** 没有 LLM、没有随机数、没有网络，因此可以单测、可以重放。
3. **快照是副本。** ``snapshot()`` 返回深拷贝，调用方改它不会污染内部状态。

与好感度的关系
--------------
好感度的裁决在 ``rules.py``（模型提议 → 规则裁决）；本模块负责其它世界状态
（金币 / 物品 / 任务）。两者遵循同一条原则：**模型只能提议，后端做决定**。

已知边界
--------
* 状态只存在于进程内存，重启即回到初始值（课程项目够用；持久化留待后续）。
* 位置（坐标）由 Godot 客户端拥有，本模块不接管，避免双写冲突。
"""

from __future__ import annotations

import copy
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

DEFAULT_START_GOLD = 100.0

QUEST_AVAILABLE = "available"
QUEST_ACTIVE = "active"
QUEST_COMPLETED = "completed"
QUEST_FAILED = "failed"


@dataclass
class Quest:
    """一个任务定义。奖励金额由任务决定，不由模型决定。"""

    quest_id: str
    title: str
    status: str = QUEST_AVAILABLE
    reward_gold: float = 0.0
    required_items: Dict[str, int] = field(default_factory=dict)
    owner: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "quest_id": self.quest_id,
            "title": self.title,
            "status": self.status,
            "reward_gold": self.reward_gold,
            "required_items": dict(self.required_items),
            "owner": self.owner,
        }


class WorldState:
    """金币 / 物品 / 任务的权威容器。"""

    def __init__(
        self,
        gold: Optional[Dict[str, float]] = None,
        items: Optional[Dict[str, Dict[str, int]]] = None,
        quests: Optional[Dict[str, Quest]] = None,
        start_gold: float = DEFAULT_START_GOLD,
    ) -> None:
        self._lock = threading.RLock()
        self._gold: Dict[str, float] = dict(gold or {})
        self._items: Dict[str, Dict[str, int]] = {
            owner: dict(bag) for owner, bag in (items or {}).items()
        }
        self._quests: Dict[str, Quest] = dict(quests or {})
        self._events: List[Dict[str, object]] = []
        self._version = 0
        self._start_gold = start_gold

    # ------------------------------------------------------------------
    # 只读访问
    # ------------------------------------------------------------------
    def ensure_player(self, player_id: str) -> None:
        """首次出现的玩家给一份初始金币。"""
        with self._lock:
            if player_id not in self._gold:
                self._gold[player_id] = self._start_gold

    def gold_of(self, player_id: str) -> float:
        with self._lock:
            return round(self._gold.get(player_id, 0.0), 2)

    def items_of(self, player_id: str) -> Dict[str, int]:
        with self._lock:
            return dict(self._items.get(player_id, {}))

    def item_count(self, owner: str, item: str) -> int:
        with self._lock:
            return int(self._items.get(owner, {}).get(item, 0))

    def quest(self, quest_id: str) -> Optional[Quest]:
        with self._lock:
            q = self._quests.get(quest_id)
            return copy.deepcopy(q) if q else None

    def list_quests(self) -> List[Dict[str, object]]:
        with self._lock:
            return [q.to_dict() for q in self._quests.values()]

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def recent_events(self, limit: int = 10) -> List[Dict[str, object]]:
        with self._lock:
            return copy.deepcopy(self._events[-limit:])

    def snapshot(self, player_id: Optional[str] = None) -> Dict[str, object]:
        """返回深拷贝快照，调用方随意修改都不会影响内部状态。"""
        with self._lock:
            data: Dict[str, object] = {
                "quests": [q.to_dict() for q in self._quests.values()],
                "version": self._version,
            }
            if player_id is not None:
                self.ensure_player(player_id)
                data["player_id"] = player_id
                data["gold"] = self.gold_of(player_id)
                data["items"] = self.items_of(player_id)
            else:
                data["gold"] = {k: round(v, 2) for k, v in self._gold.items()}
                data["items"] = {k: dict(v) for k, v in self._items.items()}
            return copy.deepcopy(data)

    # ------------------------------------------------------------------
    # 变更接口：只允许 actions.py 调用
    # ------------------------------------------------------------------
    def add_gold(self, player_id: str, amount: float) -> None:
        with self._lock:
            self.ensure_player(player_id)
            self._gold[player_id] = round(self._gold[player_id] + float(amount), 2)

    def add_item(self, owner: str, item: str, qty: int) -> None:
        with self._lock:
            bag = self._items.setdefault(owner, {})
            bag[item] = int(bag.get(item, 0)) + int(qty)

    def remove_item(self, owner: str, item: str, qty: int) -> None:
        with self._lock:
            bag = self._items.setdefault(owner, {})
            left = int(bag.get(item, 0)) - int(qty)
            if left > 0:
                bag[item] = left
            else:
                bag.pop(item, None)

    def set_quest_status(self, quest_id: str, status: str, owner: Optional[str] = None) -> None:
        with self._lock:
            q = self._quests[quest_id]
            q.status = status
            if owner is not None:
                q.owner = owner

    def record_event(self, actor: str, action: str, detail: Dict[str, object]) -> None:
        """审计轨迹：谁、做了什么、结果如何。"""
        with self._lock:
            self._version += 1
            self._events.append(
                {
                    "seq": self._version,
                    "at": datetime.now().isoformat(timespec="seconds"),
                    "actor": actor,
                    "action": action,
                    "detail": copy.deepcopy(detail),
                }
            )


_DEFAULT: Optional[WorldState] = None
_DEFAULT_LOCK = threading.Lock()


def build_demo_state() -> WorldState:
    """构造一份可复现的演示世界：两个任务、两个 NPC 持有物品。"""
    return WorldState(
        gold={},
        items={
            "张三": {"代码评审报告": 2, "调试日志": 3},
            "王五": {"设计稿": 2},
        },
        quests={
            "q_review": Quest(
                quest_id="q_review",
                title="帮张三整理代码评审报告",
                reward_gold=30.0,
                required_items={"代码评审报告": 1},
            ),
            "q_design": Quest(
                quest_id="q_design",
                title="把设计稿交给王五",
                reward_gold=20.0,
                required_items={"设计稿": 1},
            ),
        },
    )


def get_world_state() -> WorldState:
    """进程级单例。"""
    global _DEFAULT
    if _DEFAULT is None:
        with _DEFAULT_LOCK:
            if _DEFAULT is None:
                _DEFAULT = build_demo_state()
    return _DEFAULT


def reset_world_state() -> WorldState:
    """测试与演示用：重建单例。"""
    global _DEFAULT
    with _DEFAULT_LOCK:
        _DEFAULT = build_demo_state()
    return _DEFAULT
