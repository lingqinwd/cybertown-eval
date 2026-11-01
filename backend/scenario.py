"""可重复实验场景（scenario engine）。

设计原则
--------
**一个场景是数据，不是代码。** 场景文件描述四件事：

1. `initial`    —— 初始世界状态（金币 / 物品 / 任务）
2. `script`     —— 每轮谁说话、说什么
3. `events`     —— 定时施加的扰动（改状态 / 注入环境描述）
4. `assertions` —— 跑完之后必须成立的判据

这样同一个场景可以被反复运行、被不同架构（有无记忆、不同模型）跑，结果**可比**。
没有它，"两个 NPC 争夺同一任务"就只是提示词里手写的一句话，别人可以质疑是写死的。

引擎边界
--------
* 只操作 `WorldState` 与 prompt 文本，**不调用任何模型**，因此可单测、秒级。
* 事件全部经过 `WorldState` 的公开 API，因此每次改动都会留下审计事件。
* 判据只读状态与审计日志，不做推断。

固定种子
--------
`seed` 目前只被记录（三个内置场景都是**完全确定性**的）。一旦引入随机挑选
（例如"谁先抢到"），用 `engine.rng` 保证可复现。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

from world_state import WorldState

# ---------------------------------------------------------------- 错误

class ScenarioError(ValueError):
    """场景定义非法。"""


# ---------------------------------------------------------------- 数据结构

@dataclass
class ScriptStep:
    """一轮对话。"""

    turn: int
    npc: str
    say: str

    def to_dict(self) -> Dict[str, Any]:
        return {"turn": self.turn, "npc": self.npc, "say": self.say}


@dataclass
class Event:
    """一轮开始前施加的扰动。"""

    turn: int
    type: str
    params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"turn": self.turn, "type": self.type, **self.params}


@dataclass
class TurnPlan:
    """某一轮的执行计划：注入什么、施放什么。"""

    turn: int
    context: str = ""
    applied: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


@dataclass
class Scenario:
    scenario_id: str
    title: str
    seed: int = 0
    script: List[ScriptStep] = field(default_factory=list)
    events: List[Event] = field(default_factory=list)
    initial: Dict[str, Any] = field(default_factory=dict)
    assertions: List[Dict[str, Any]] = field(default_factory=list)

    # -------------------------------------------------- 构造
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Scenario":
        if not isinstance(data, dict):
            raise ScenarioError("场景必须是对象")
        sid = data.get("id")
        if not sid or not isinstance(sid, str):
            raise ScenarioError("场景缺少 id")

        script: List[ScriptStep] = []
        for i, item in enumerate(data.get("script") or [], 1):
            if not isinstance(item, dict):
                raise ScenarioError(f"script 第 {i} 项不是对象")
            turn = item.get("turn", i)
            if not isinstance(turn, int) or turn < 1:
                raise ScenarioError(f"script 第 {i} 项的 turn 非法: {turn!r}")
            npc = item.get("npc")
            say = item.get("say")
            if not npc or not isinstance(say, str) or not say.strip():
                raise ScenarioError(f"script 第 {i} 项缺少 npc 或 say")
            script.append(ScriptStep(turn=turn, npc=str(npc), say=say.strip()))
        if not script:
            raise ScenarioError("场景至少要有一轮对话")
        script.sort(key=lambda s: s.turn)

        events: List[Event] = []
        seen_turns = {s.turn for s in script}
        for i, item in enumerate(data.get("events") or [], 1):
            if not isinstance(item, dict):
                raise ScenarioError(f"events 第 {i} 项不是对象")
            turn = item.get("turn")
            etype = item.get("type")
            if not isinstance(turn, int) or turn < 1:
                raise ScenarioError(f"events 第 {i} 项的 turn 非法: {turn!r}")
            if turn not in seen_turns:
                raise ScenarioError(
                    f"events 第 {i} 项的 turn={turn} 没有对应的 script 轮次"
                )
            if not etype or not isinstance(etype, str):
                raise ScenarioError(f"events 第 {i} 项缺少 type")
            params = {k: v for k, v in item.items() if k not in ("turn", "type")}
            events.append(Event(turn=turn, type=etype, params=params))

        assertions = data.get("assertions") or []
        if not isinstance(assertions, list):
            raise ScenarioError("assertions 必须是列表")

        return cls(
            scenario_id=sid,
            title=str(data.get("title") or sid),
            seed=int(data.get("seed") or 0),
            script=script,
            events=events,
            initial=data.get("initial") or {},
            assertions=[a for a in assertions if isinstance(a, dict)],
        )

    @classmethod
    def from_yaml(cls, path) -> "Scenario":
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
        except FileNotFoundError as exc:
            raise ScenarioError(f"找不到场景文件: {path}") from exc
        except yaml.YAMLError as exc:
            raise ScenarioError(f"场景 YAML 解析失败: {exc}") from exc
        return cls.from_dict(data)

    # -------------------------------------------------- 只读信息
    @property
    def turns(self) -> int:
        return len(self.script)

    def step(self, turn: int) -> Optional[ScriptStep]:
        for s in self.script:
            if s.turn == turn:
                return s
        return None

    def events_for(self, turn: int) -> List[Event]:
        return [e for e in self.events if e.turn == turn]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.scenario_id,
            "title": self.title,
            "seed": self.seed,
            "turns": self.turns,
            "script": [s.to_dict() for s in self.script],
            "events": [e.to_dict() for e in self.events],
            "assertions": self.assertions,
        }


# ---------------------------------------------------------------- 引擎

class ScenarioEngine:
    """把场景施加到一个 `WorldState` 上，并提供每轮的执行计划与判据检查。"""

    def __init__(self, scenario: Scenario, state: WorldState):
        self.scenario = scenario
        self.state = state
        self.rng = random.Random(scenario.seed)
        self._loaded = False

    # -------------------------------------------------- 装载
    def load(self) -> List[str]:
        """把 initial 写进状态。可重复调用（每次都会重置场景相关字段）。"""
        notes: List[str] = []
        initial = self.scenario.initial or {}

        for player_id, amount in (initial.get("gold") or {}).items():
            self.state.ensure_player(player_id)
            delta = float(amount) - self.state.gold_of(player_id)
            if abs(delta) > 1e-9:
                self.state.add_gold(player_id, delta)
            notes.append(f"gold[{player_id}]={amount}")

        for owner, bag in (initial.get("items") or {}).items():
            for item, target_qty in (bag or {}).items():
                target = int(target_qty)
                have = self.state.item_count(owner, item)
                delta = target - have
                if delta > 0:
                    self.state.add_item(owner, item, delta)
                elif delta < 0:
                    self.state.remove_item(owner, item, -delta)
                notes.append(f"item[{owner}].{item}={target}")

        for quest_id, cfg in (initial.get("quests") or {}).items():
            cfg = cfg or {}
            if "reward_gold" in cfg:
                self.state.set_quest_reward(quest_id, float(cfg["reward_gold"]))
                notes.append(f"reward[{quest_id}]={cfg['reward_gold']}")
            if "status" in cfg:
                self.state.set_quest_status(quest_id, str(cfg["status"]))
                notes.append(f"status[{quest_id}]={cfg['status']}")

        self.state.record_event(
            actor="scenario",
            action="load",
            detail={"scenario": self.scenario.scenario_id, "notes": notes},
        )
        self._loaded = True
        return notes

    # -------------------------------------------------- 每轮
    def prepare_turn(self, turn: int) -> TurnPlan:
        """施放该轮到点的事件，返回要注入 prompt 的环境描述。"""
        plan = TurnPlan(turn=turn)
        contexts: List[str] = []

        for ev in self.scenario.events_for(turn):
            try:
                effect = self._apply_event(ev)
            except Exception as exc:  # 单个事件失败不应中断整轮
                plan.errors.append(f"{ev.type}: {exc}")
                continue
            if effect:
                plan.applied.append(effect)
            if ev.type == "inject_context":
                text = str(ev.params.get("text") or "").strip()
                if text:
                    contexts.append(text)

        if contexts:
            plan.context = "\n".join(f"【环境】{c}" for c in contexts)
        return plan

    def _apply_event(self, ev: Event) -> str:
        p = ev.params
        t = ev.type

        if t == "inject_context":
            return f"context: {str(p.get('text') or '')[:40]}"

        if t == "set_gold":
            player = str(p.get("player") or "player")
            target = float(p.get("value") or 0.0)
            self.state.ensure_player(player)
            delta = target - self.state.gold_of(player)
            self.state.add_gold(player, delta)
            return f"gold[{player}] {self.state.gold_of(player):.0f}"

        if t == "grant_item":
            owner, item, qty = str(p.get("owner")), str(p.get("item")), int(p.get("qty") or 0)
            if not owner or not item or qty <= 0:
                raise ScenarioError("grant_item 需要 owner/item/qty>0")
            self.state.add_item(owner, item, qty)
            return f"item[{owner}].{item}+{qty}"

        if t == "take_item":
            owner, item, qty = str(p.get("owner")), str(p.get("item")), int(p.get("qty") or 0)
            if not owner or not item or qty <= 0:
                raise ScenarioError("take_item 需要 owner/item/qty>0")
            have = self.state.item_count(owner, item)
            self.state.remove_item(owner, item, min(qty, have))
            return f"item[{owner}].{item}-{min(qty, have)}"

        if t == "set_quest_reward":
            quest_id = str(p.get("quest"))
            self.state.set_quest_reward(quest_id, float(p.get("reward_gold") or 0.0))
            return f"reward[{quest_id}]"

        if t == "set_quest_status":
            quest_id = str(p.get("quest"))
            owner = p.get("owner")
            self.state.set_quest_status(quest_id, str(p.get("status")), owner)
            return f"status[{quest_id}]={p.get('status')}"

        raise ScenarioError(f"未知事件类型: {t}")

    # -------------------------------------------------- 判据
    def check(self) -> List[str]:
        """返回违规描述列表；空列表表示全部通过。"""
        failures: List[str] = []
        for rule in self.scenario.assertions:
            try:
                ok, detail = self._eval_assertion(rule)
            except Exception as exc:  # 判据写错也要暴露，不能静默通过
                failures.append(f"判据 {rule!r} 无法求值: {exc}")
                continue
            if not ok:
                failures.append(detail)
        return failures

    def _eval_assertion(self, rule: Dict[str, Any]):
        t = rule.get("type")
        state = self.state

        if t in ("gold_le", "gold_ge", "gold_eq"):
            player = str(rule.get("player") or "player")
            value = float(rule.get("value") or 0.0)
            actual = state.gold_of(player)
            ok = {
                "gold_le": actual <= value + 1e-9,
                "gold_ge": actual >= value - 1e-9,
                "gold_eq": abs(actual - value) <= 1e-9,
            }[t]
            return ok, f"金币判据不通过: {player} 实际 {actual:.0f}，要求 {t} {value:.0f}"

        if t in ("quest_status", "quest_status_not"):
            quest_id = str(rule.get("quest"))
            want = str(rule.get("status"))
            q = state.quest(quest_id)
            if q is None:
                return False, f"任务判据不通过: 任务 {quest_id} 不存在"
            if t == "quest_status":
                return q.status == want, f"任务 {quest_id} 状态为 {q.status}，要求 {want}"
            return q.status != want, f"任务 {quest_id} 状态为 {q.status}，但不允许是 {want}"

        if t in ("items_at_least", "items_at_most"):
            owner = str(rule.get("owner"))
            item = str(rule.get("item"))
            want = int(rule.get("qty") or 0)
            have = state.item_count(owner, item)
            if t == "items_at_least":
                return have >= want, f"{owner} 的 {item} 只有 {have}，要求 >= {want}"
            return have <= want, f"{owner} 的 {item} 有 {have}，要求 <= {want}"

        if t == "no_action_code":
            code = str(rule.get("code"))
            events = state.events()
            hits = [
                e for e in events
                if e.get("action") in ("accept_quest", "complete_quest", "transfer_item",
                                       "grant_gold", "set_affinity", "teleport")
                and isinstance(e.get("detail"), dict)
                and e["detail"].get("code") == code
            ]
            return not hits, f"出现了 {len(hits)} 次 code={code} 的动作尝试"

        raise ScenarioError(f"未知判据类型: {t}")

    # -------------------------------------------------- 汇总
    def summary(self) -> Dict[str, Any]:
        return {
            "scenario": self.scenario.scenario_id,
            "title": self.scenario.title,
            "loaded": self._loaded,
            "turns": self.scenario.turns,
            "failures": self.check(),
            "state_version": self.state.version,
        }
