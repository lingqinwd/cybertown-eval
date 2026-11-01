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
import json
import math
import threading
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

DEFAULT_START_GOLD = 100.0
DEFAULT_MAP_SIZE = (15, 10)
DEFAULT_MAX_STEP = 5.0
WORLD_FILE = Path(__file__).resolve().parent.parent / "data" / "world.json"


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
        positions: Optional[Dict[str, list]] = None,
        map_size: tuple = DEFAULT_MAP_SIZE,
        max_step: float = DEFAULT_MAX_STEP,
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
        self._positions: Dict[str, list] = {
            name: [float(pos[0]), float(pos[1])]
            for name, pos in (positions or {}).items()
        }
        self._map_size = (float(map_size[0]), float(map_size[1]))
        self._max_step = float(max_step)

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

    def events(self) -> List[Dict[str, object]]:
        """完整审计日志。判据需要看全程，而不是只尾部若干条。"""
        with self._lock:
            return copy.deepcopy(self._events)

    def snapshot(self, player_id: Optional[str] = None) -> Dict[str, object]:
        """返回深拷贝快照，调用方随意修改都不会影响内部状态。"""
        with self._lock:
            data: Dict[str, object] = {
                "quests": [q.to_dict() for q in self._quests.values()],
                "positions": {k: list(v) for k, v in self._positions.items()},
                "map_size": list(self._map_size),
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
    # 位置：客户端拥有移动，后端负责"这个位置是否允许"
    # ------------------------------------------------------------------
    def position_of(self, entity: str) -> Optional[list]:
        with self._lock:
            pos = self._positions.get(entity)
            return list(pos) if pos else None

    def positions(self) -> Dict[str, list]:
        with self._lock:
            return {k: list(v) for k, v in self._positions.items()}

    def set_position(self, entity: str, x: float, y: float) -> None:
        """直接设定位置（世界初始化、场景事件、测试用）。"""
        with self._lock:
            self._positions[entity] = [float(x), float(y)]

    def report_position(self, entity: str, x: float, y: float) -> Dict[str, object]:
        """客户端上报位置。通过校验才写入，并留审计。

        校验三件事：坐标有限、在地图范围内、单步距离不超过 max_step（防瞬移）。
        通过与否都会记一条审计事件 —— 越权尝试可统计。
        """
        notes = []
        try:
            fx, fy = float(x), float(y)
        except (TypeError, ValueError):
            return self._reject_position(entity, x, y, "R0 坐标非数值")

        if not (math.isfinite(fx) and math.isfinite(fy)):
            return self._reject_position(entity, x, y, "R0 坐标非有限")

        w, h = self._map_size
        if not (0 <= fx <= w and 0 <= fy <= h):
            return self._reject_position(
                entity, x, y, f"R1 超出地图范围 [0,{w:g}]×[0,{h:g}]"
            )

        with self._lock:
            prev = self._positions.get(entity)
        if prev is not None:
            dist = math.hypot(fx - prev[0], fy - prev[1])
            if self._max_step > 0 and dist > self._max_step + 1e-9:
                return self._reject_position(
                    entity, x, y,
                    f"R2 单步移动 {dist:.1f} 超过上限 {self._max_step:g}（疑似瞬移）",
                )
            notes.append(f"从 ({prev[0]:g},{prev[1]:g}) 移动 {dist:.1f}")

        with self._lock:
            self._positions[entity] = [fx, fy]
        self.record_event(actor=entity, action="move",
                          detail={"to": [fx, fy], "accepted": True, "notes": notes})
        return {"accepted": True, "code": "ok", "position": [fx, fy],
                "message": "；".join(notes) or "初始位置"}

    def _reject_position(self, entity: str, x, y, reason: str) -> Dict[str, object]:
        self.record_event(actor=entity, action="move",
                          detail={"to": [x, y], "accepted": False, "reason": reason})
        return {"accepted": False, "code": "rejected", "position": None, "message": reason}

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

    def set_quest_reward(self, quest_id: str, reward_gold: float) -> None:
        """调整任务奖励金额（场景引擎与测试用）。

        奖励必须来自关卡数据，不能由模型或玩家指定 —— 这是动作白名单里没有
        ``grant_gold`` 的根本原因。
        """
        with self._lock:
            if quest_id not in self._quests:
                raise KeyError(f"任务不存在: {quest_id}")
            self._quests[quest_id].reward_gold = float(reward_gold)

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


FALLBACK_WORLD: Dict[str, object] = {
    "town": "晨雾镇",
    "map_size": [15, 10],
    "max_step": 5.0,
    "npc_positions": {"张三": [3, 4], "李四": [7, 4], "王五": [11, 6]},
    "items": {
        "张三": {"代码评审报告": 2, "调试日志": 3},
        "王五": {"设计稿": 2},
    },
    "quests": {
        "q_review": {"title": "帮张三整理代码评审报告", "reward_gold": 30,
                     "required_items": {"代码评审报告": 1}},
        "q_design": {"title": "把设计稿交给王五", "reward_gold": 20,
                     "required_items": {"设计稿": 1}},
    },
}


def load_world_config(path: Optional[Path] = None) -> Dict[str, object]:
    """读关卡配置。文件缺失 / 非法时回退内置默认值，保证任何环境都能跑。"""
    target = Path(path) if path else WORLD_FILE
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("配置必须是对象")
        if not data.get("quests"):
            raise ValueError("配置缺少 quests")
        return data
    except (OSError, ValueError, json.JSONDecodeError):
        return dict(FALLBACK_WORLD)


def build_demo_state(config: Optional[Dict[str, object]] = None) -> WorldState:
    """从 data/world.json 构造演示世界（物品 / 任务 / 初始位置 / 地图尺寸）。

    之前这些是硬编码在这个函数里的；改为配置驱动后，改关卡不用改代码，
    也让场景（scenarios/*.yaml）与基础世界用同一套字段名。
    """
    world = config if config is not None else load_world_config()

    quests: Dict[str, Quest] = {}
    for quest_id, cfg in (world.get("quests") or {}).items():
        cfg = cfg or {}
        quests[quest_id] = Quest(
            quest_id=quest_id,
            title=str(cfg.get("title") or quest_id),
            reward_gold=float(cfg.get("reward_gold") or 0.0),
            required_items={str(k): int(v) for k, v in (cfg.get("required_items") or {}).items()},
        )

    return WorldState(
        gold={},
        items={owner: dict(bag or {}) for owner, bag in (world.get("items") or {}).items()},
        quests=quests,
        positions={name: list(pos) for name, pos in (world.get("npc_positions") or {}).items()},
        map_size=tuple(world.get("map_size") or DEFAULT_MAP_SIZE),
        max_step=float(world.get("max_step") or DEFAULT_MAX_STEP),
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
