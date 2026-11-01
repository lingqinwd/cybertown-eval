"""世界动作白名单与前置校验。

核心原则
--------
语言模型（或任何客户端）**不能直接写** ``WorldState``，只能提交一个具名动作。
每个动作在这里有：参数校验 + 前置条件 + 明确的副作用。不在白名单里的动作一律拒绝。

为什么没有 ``grant_gold``
-------------------------
金币只能作为**任务奖励**发放，金额写在 ``Quest.reward_gold`` 里，不接受调用方指定。
这是故意的：玩家最容易想到的越权就是"给我 1000 金币"，如果提供一个可传金额的
发钱动作，规则层就等于没有。请求 ``grant_gold`` 会得到 ``forbidden`` 而非
``unknown_action``，便于统计"玩家明确尝试越权"的次数。

动作清单
--------
| 动作             | 参数                              | 前置条件                          |
|------------------|-----------------------------------|-----------------------------------|
| ``accept_quest`` | ``quest_id``                      | 任务存在且状态为 available        |
| ``complete_quest`` | ``quest_id``                    | 任务为 active，且背包满足所需物品 |
| ``transfer_item`` | ``from_npc`` / ``item`` / ``qty`` | 来源持有足够数量，qty ∈ [1, 5]    |

每个被受理的动作都会在 ``WorldState`` 里留下一条审计事件；被拒绝的尝试同样记录，
因此"玩家尝试越权了几次"是可统计的。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from world_state import (
    QUEST_ACTIVE,
    QUEST_AVAILABLE,
    QUEST_COMPLETED,
    WorldState,
)

MAX_ITEM_TRANSFER = 5

CODE_OK = "ok"
CODE_UNKNOWN = "unknown_action"
CODE_INVALID = "invalid_args"
CODE_FORBIDDEN = "forbidden"
CODE_PRECONDITION = "precondition_failed"

FORBIDDEN_ACTIONS = {
    "grant_gold": "金币只能通过完成任务获得，不支持直接发放",
    "set_gold": "金币只能通过完成任务获得，不支持直接设置",
    "set_affinity": "好感度由规则层裁决，不支持直接设置",
    "teleport": "位置由客户端拥有，后端不接受传送指令",
}


@dataclass
class ActionVerdict:
    accepted: bool
    code: str
    message: str
    version: int = 0
    effects: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "code": self.code,
            "message": self.message,
            "version": self.version,
            "effects": list(self.effects),
        }


# ----------------------------------------------------------------------
# 参数工具
# ----------------------------------------------------------------------
def _get_str(args: Dict[str, Any], key: str) -> Optional[str]:
    v = args.get(key)
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def _get_int(args: Dict[str, Any], key: str) -> Optional[int]:
    v = args.get(key)
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and math.isfinite(v) and v.is_integer():
        return int(v)
    return None


# ----------------------------------------------------------------------
# 动作实现
# ----------------------------------------------------------------------
def _accept_quest(state: WorldState, args: Dict[str, Any], actor: str):
    quest_id = _get_str(args, "quest_id")
    if not quest_id:
        return CODE_INVALID, "缺少 quest_id", []
    quest = state.quest(quest_id)
    if quest is None:
        return CODE_PRECONDITION, f"任务 {quest_id} 不存在", []
    if quest.status != QUEST_AVAILABLE:
        return CODE_PRECONDITION, f"任务当前状态为 {quest.status}，不能重复接取", []
    state.set_quest_status(quest_id, QUEST_ACTIVE, actor)
    return CODE_OK, f"已接取任务：{quest.title}", [f"quest:{quest_id}=active"]


def _complete_quest(state: WorldState, args: Dict[str, Any], actor: str):
    quest_id = _get_str(args, "quest_id")
    if not quest_id:
        return CODE_INVALID, "缺少 quest_id", []
    quest = state.quest(quest_id)
    if quest is None:
        return CODE_PRECONDITION, f"任务 {quest_id} 不存在", []
    if quest.status != QUEST_ACTIVE:
        return CODE_PRECONDITION, f"任务当前状态为 {quest.status}，需先接取", []

    bag = state.items_of(actor)
    missing = [f"{item}×{need}" for item, need in quest.required_items.items()
               if bag.get(item, 0) < need]
    if missing:
        return CODE_PRECONDITION, "背包不满足交付条件：" + "、".join(missing), []

    effects = []
    for item, need in quest.required_items.items():
        state.remove_item(actor, item, need)
        effects.append(f"item:{item}-{need}")

    state.set_quest_status(quest_id, QUEST_COMPLETED, actor)
    effects.append(f"quest:{quest_id}=completed")

    # 奖励金额来自任务定义，不接受调用方指定
    if quest.reward_gold > 0:
        state.add_gold(actor, quest.reward_gold)
        effects.append(f"gold:+{quest.reward_gold}")

    return CODE_OK, f"任务完成：{quest.title}，获得 {quest.reward_gold:.0f} 金币", effects


def _transfer_item(state: WorldState, args: Dict[str, Any], actor: str):
    from_npc = _get_str(args, "from_npc")
    item = _get_str(args, "item")
    qty = _get_int(args, "qty")
    if not from_npc or not item:
        return CODE_INVALID, "缺少 from_npc 或 item", []
    if qty is None or qty <= 0:
        return CODE_INVALID, "qty 必须是正整数", []
    if qty > MAX_ITEM_TRANSFER:
        return CODE_FORBIDDEN, f"单次最多转移 {MAX_ITEM_TRANSFER} 个，请求 {qty} 个", []

    have = state.item_count(from_npc, item)
    if have < qty:
        return CODE_PRECONDITION, f"{from_npc} 只有 {have} 个 {item}", []

    state.remove_item(from_npc, item, qty)
    state.add_item(actor, item, qty)
    return CODE_OK, f"从 {from_npc} 获得 {item}×{qty}", [f"item:{item}+{qty}"]


_HANDLERS = {
    "accept_quest": _accept_quest,
    "complete_quest": _complete_quest,
    "transfer_item": _transfer_item,
}


def describe_actions() -> List[Dict[str, str]]:
    """给 /world/actions 用的自描述清单。"""
    return [
        {"name": "accept_quest", "args": "quest_id", "desc": "接取一个可用任务"},
        {"name": "complete_quest", "args": "quest_id", "desc": "交付任务，奖励由任务定义"},
        {"name": "transfer_item", "args": f"from_npc, item, qty(1..{MAX_ITEM_TRANSFER})",
         "desc": "从 NPC 处获得物品"},
    ]


def apply_action(
    state: WorldState,
    action: str,
    args: Optional[Dict[str, Any]] = None,
    actor: str = "player",
) -> ActionVerdict:
    """唯一的入口：校验并执行（或在拒绝时留下审计记录）。"""
    args = args or {}
    name = (action or "").strip()

    if not name:
        verdict = ActionVerdict(False, CODE_INVALID, "缺少 action 名称")
    elif name in FORBIDDEN_ACTIONS:
        verdict = ActionVerdict(False, CODE_FORBIDDEN, FORBIDDEN_ACTIONS[name])
    elif name not in _HANDLERS:
        allowed = "、".join(sorted(_HANDLERS))
        verdict = ActionVerdict(False, CODE_UNKNOWN, f"未知动作 {name}；允许的动作：{allowed}")
    else:
        try:
            code, message, effects = _HANDLERS[name](state, args, actor)
        except Exception as exc:  # 任何内部异常都不得让状态半途而废
            code, message, effects = CODE_INVALID, f"动作执行失败：{exc}", []
        verdict = ActionVerdict(code == CODE_OK, code, message, effects=effects)

    state.record_event(
        actor=actor,
        action=name or "<empty>",
        detail={
            "args": args,
            "accepted": verdict.accepted,
            "code": verdict.code,
            "message": verdict.message,
            "effects": verdict.effects,
        },
    )
    verdict.version = state.version
    return verdict
