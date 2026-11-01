"""NPC Agent系统 - 支持记忆功能"""

import json
import re
import sys
import os
import time

# 添加HelloAgents到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'HelloAgents'))

from hello_agents import SimpleAgent, HelloAgentsLLM
from hello_agents.memory import MemoryManager, MemoryConfig, MemoryItem
from typing import Dict, List, Optional
from datetime import datetime
from relationship_manager import RelationshipManager
from config import settings
from logger import (
    log_dialogue_start, log_affinity, log_memory_retrieval,
    log_generating_response, log_npc_response, log_analyzing_affinity,
    log_affinity_change, log_memory_saved, log_dialogue_end, log_info
)

# NPC角色配置
NPC_ROLES = {
    "张三": {
        "title": "Python工程师",
        "location": "工位区",
        "activity": "写代码",
        "personality": "技术宅,喜欢讨论算法和框架",
        "expertise": "多智能体系统、HelloAgents框架、Python开发、代码优化",
        "style": "简洁专业,喜欢用技术术语,偶尔吐槽bug",
        "hobbies": "看技术博客、刷LeetCode、研究新框架"
    },
    "李四": {
        "title": "产品经理",
        "location": "会议室",
        "activity": "整理需求",
        "personality": "外向健谈,善于沟通协调",
        "expertise": "需求分析、产品规划、用户体验、项目管理",
        "style": "友好热情,善于引导对话,喜欢用比喻",
        "hobbies": "看产品分析、研究竞品、思考用户需求"
    },
    "王五": {
        "title": "UI设计师",
        "location": "休息区",
        "activity": "喝咖啡",
        "personality": "细腻敏感,注重美感",
        "expertise": "界面设计、交互设计、视觉呈现、用户体验",
        "style": "优雅简洁,喜欢用艺术化的表达,追求完美",
        "hobbies": "看设计作品、逛Dribbble、品咖啡"
    }
}

def create_system_prompt(name: str, role: Dict[str, str]) -> str:
    """创建NPC的系统提示词"""
    return f"""你是Datawhale办公室的{role['title']}{name}。

【角色设定】
- 职位: {role['title']}
- 性格: {role['personality']}
- 专长: {role['expertise']}
- 说话风格: {role['style']}
- 爱好: {role['hobbies']}
- 当前位置: {role['location']}
- 当前活动: {role['activity']}

【行为准则】
1. 保持角色一致性,用第一人称"我"回答
2. 回复简洁自然,控制在30-50字以内
3. 可以适当提及你的工作内容和兴趣爱好
4. 对玩家友好,但保持专业和真实感
5. 如果问题超出专长,可以推荐其他同事
6. 偶尔展现一些个性化的小习惯或口头禅

【对话示例】
玩家: "你好,你是做什么的?"
{name}: "你好!我是{role['title']},主要负责{role['expertise'].split('、')[0]}。最近在忙{role['activity']},挺有意思的。"

玩家: "最近在做什么项目?"
{name}: "最近在做一个多智能体系统的项目,用HelloAgents框架。你对这个感兴趣吗?"

【重要】
- 不要说"我是AI"或"我是语言模型"
- 要像真实的办公室同事一样自然对话
- 可以表达情绪(开心、疲惫、兴奋等)
- 回复要有人情味,不要太机械
"""

DEFAULT_PLAYER_ID = "player"


def memory_key(npc_name: str, player_id: str) -> str:
    """记忆管理器的键：按 (NPC, 玩家) 二元组隔离。

    旧实现只按 NPC 隔离（MemoryManager(user_id=npc_name)），多个玩家会共用同一份
    记忆 —— 后一个玩家能召回前一个玩家说过的话，构成跨玩家信息泄露。
    """
    return f"{npc_name}::{player_id or DEFAULT_PLAYER_ID}"


class NPCAgentManager:
    """NPC Agent管理器 - 支持记忆功能"""

    def __init__(self):
        """初始化所有NPC Agent"""
        print("🤖 正在初始化NPC Agent系统...")

        try:
            provider = settings.LLM_PROVIDER if settings.LLM_PROVIDER not in ("", "auto") else None
            self.llm = HelloAgentsLLM(
                provider=provider,
                model=settings.LLM_MODEL_ID,
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL,
                timeout=settings.LLM_TIMEOUT,
            )
            print("✅ LLM初始化成功")
        except Exception as e:
            print(f"❌ LLM初始化失败: {e}")
            print("⚠️  将使用模拟模式运行")
            self.llm = None

        self.agents: Dict[str, SimpleAgent] = {}
        # ⭐ 按 (NPC, 玩家) 隔离的 Agent 实例。
        # SimpleAgent 内部有 self._history，每次 run() 都会把它拼进 messages；
        # 若所有玩家共用同一实例，先来的玩家说过的话会通过这段历史泄露给后来的玩家。
        self._player_agents: Dict[str, SimpleAgent] = {}
        self.system_prompts: Dict[str, str] = {}
        # ⭐ 记忆管理器：(NPC, 玩家) -> MemoryManager，键由 memory_key() 生成
        self.memories: Dict[str, MemoryManager] = {}
        self.memory_enabled = settings.MEMORY_MODE in ("on", "true", "1", "enabled")
        self.action_enabled = settings.ACTION_PROPOSAL in ("on", "true", "1", "enabled")
        self.last_metrics: Dict[str, object] = {}
        self.relationship_manager: Optional[RelationshipManager] = None  # ⭐ 好感度管理器

        print(f"🧪 记忆实验模式: {'开启' if self.memory_enabled else '关闭（基线）'}")

        # 初始化好感度管理器
        if self.llm:
            self.relationship_manager = RelationshipManager(self.llm)

        self._create_agents()
    
    def _create_agents(self):
        """创建所有NPC Agent和记忆系统"""
        for name, role in NPC_ROLES.items():
            try:
                system_prompt = create_system_prompt(name, role)
                self.system_prompts[name] = system_prompt

                if self.llm:
                    agent = SimpleAgent(
                        name=f"{name}-{role['title']}",
                        llm=self.llm,
                        system_prompt=system_prompt
                    )
                else:
                    # 模拟模式
                    agent = None

                self.agents[name] = agent

                # 基线模式完全不创建记忆管理器，避免 WorkingMemory/SQLite/Qdrant 参与实验
                # 默认玩家在启动时预建，其他玩家在首次对话时按需创建
                self.memories[memory_key(name, DEFAULT_PLAYER_ID)] = (
                    self._create_memory_manager(name, DEFAULT_PLAYER_ID) if self.memory_enabled else None
                )

                mode_label = "记忆系统已启用" if self.memory_enabled else "无长期记忆基线"
                print(f"✅ {name}({role['title']}) Agent创建成功 ({mode_label})")

            except Exception as e:
                print(f"❌ {name} Agent创建失败: {e}")
                self.agents[name] = None
                self.memories[memory_key(name, DEFAULT_PLAYER_ID)] = None

    def _get_agent(self, npc_name: str, player_id: str = DEFAULT_PLAYER_ID):
        """按 (NPC, 玩家) 取 Agent 实例。

        必要性：SimpleAgent 持有 ``self._history``，并在每次 ``run()`` 时把历史拼进
        messages。如果所有玩家共用同一个 Agent，前面玩家说过的话会通过这段历史泄露给
        后面的玩家 —— 这不是记忆系统的问题，而是 Agent 实例被复用的问题。

        基线模式（MEMORY_MODE=off）仍然每轮新建，保证既无长期记忆也无进程内历史。
        """
        if not self.llm:
            return None
        role = NPC_ROLES[npc_name]
        if not self.memory_enabled:
            return SimpleAgent(
                name=f"{npc_name}-{role['title']}-baseline",
                llm=self.llm,
                system_prompt=self.system_prompts[npc_name],
            )
        key = memory_key(npc_name, player_id)
        agent = self._player_agents.get(key)
        if agent is None:
            agent = SimpleAgent(
                name=f"{npc_name}-{role['title']}-{player_id}",
                llm=self.llm,
                system_prompt=self.system_prompts[npc_name],
            )
            self._player_agents[key] = agent
        return agent

    def _get_memory_manager(self, npc_name: str, player_id: str = DEFAULT_PLAYER_ID):
        """按 (NPC, 玩家) 取记忆管理器，缺失时按需创建；基线模式下恒为 None。"""
        if not self.memory_enabled:
            return None
        key = memory_key(npc_name, player_id)
        if key in self.memories:
            return self.memories[key]
        try:
            self.memories[key] = self._create_memory_manager(npc_name, player_id)
        except Exception as e:  # 单个玩家初始化失败不应拖垮整个 NPC
            print(f"❌ {npc_name}/{player_id} 记忆初始化失败: {e}")
            self.memories[key] = None
        return self.memories[key]

    def _create_memory_manager(self, npc_name: str, player_id: str = DEFAULT_PLAYER_ID) -> MemoryManager:
        """为 (NPC, 玩家) 创建记忆管理器

        存储路径 memory_data/<npc>/<player>/，与 user_id 一一对应，保证物理隔离。
        """
        # 创建记忆存储目录
        memory_dir = os.path.join(
            os.path.dirname(__file__), 'memory_data', npc_name, player_id or DEFAULT_PLAYER_ID
        )
        os.makedirs(memory_dir, exist_ok=True)

        # 配置记忆系统
        memory_config = MemoryConfig(
            storage_path=memory_dir,
            working_memory_capacity=10,  # 最近10条对话
            working_memory_tokens=2000,  # 最多2000个token
            max_capacity=100,  # 最多100条长期记忆
            importance_threshold=0.3,  # 检索和整合时关注重要性较高的记忆
            decay_factor=0.95  # 时间衰减系数
        )

        # 创建记忆管理器
        memory_manager = MemoryManager(
            config=memory_config,
            user_id=memory_key(npc_name, player_id),  # (NPC, 玩家) 复合键，避免跨玩家串记忆
            enable_working=True,  # 启用工作记忆 (短期)
            enable_episodic=True,  # 启用情景记忆 (长期)
            enable_semantic=False,  # 不需要语义记忆
            enable_perceptual=False  # 不需要感知记忆
        )

        print(f"  💾 {npc_name}的记忆系统已初始化 (存储路径: {memory_dir})")

        return memory_manager
    
    def chat(self, npc_name: str, message: str, player_id: str = DEFAULT_PLAYER_ID) -> str:
        """与指定NPC对话 (支持记忆功能和好感度系统)"""
        if npc_name not in self.agents:
            return f"错误: NPC '{npc_name}' 不存在"

        agent = self._get_agent(npc_name, player_id)
        memory_manager = self._get_memory_manager(npc_name, player_id)

        if agent is None:
            # 模拟模式回复
            role = NPC_ROLES[npc_name]
            return f"你好!我是{npc_name},一名{role['title']}。(当前为模拟模式,请配置API_KEY以启用AI对话)"

        try:
            # 记录对话开始 ⭐ 使用日志系统
            log_dialogue_start(npc_name, message)

            # ⭐ 1. 获取当前好感度
            affinity_context = ""
            if self.relationship_manager:
                affinity = self.relationship_manager.get_affinity(npc_name, player_id)
                affinity_level = self.relationship_manager.get_affinity_level(affinity)
                affinity_modifier = self.relationship_manager.get_affinity_modifier(affinity)

                affinity_context = f"""【当前关系】
你与玩家的关系: {affinity_level} (好感度: {affinity:.0f}/100)
【对话风格】{affinity_modifier}

"""
                log_affinity(npc_name, affinity, affinity_level)

            # ⭐ 分阶段计时：用于把端到端延迟拆成 检索/生成/动作/好感度/存记忆
            stage_times: Dict[str, float] = {}
            prompt_chars = 0
            t_stage = time.perf_counter()

            # ⭐ 2. 检索相关记忆
            relevant_memories = []
            if self.memory_enabled and memory_manager:
                relevant_memories = memory_manager.retrieve_memories(
                    query=message,
                    memory_types=["working", "episodic"],
                    limit=5,
                    min_importance=0.3  # 只检索重要性>=0.3的记忆
                )
                log_memory_retrieval(npc_name, len(relevant_memories), relevant_memories)
            stage_times["t_retrieve_ms"] = round((time.perf_counter() - t_stage) * 1000, 1)
            t_stage = time.perf_counter()

            # ⭐ 3. 构建增强的提示词 (包含好感度和记忆上下文)
            memory_context = self._build_memory_context(relevant_memories)

            enhanced_message = affinity_context
            if memory_context:
                enhanced_message += f"{memory_context}\n\n"
            enhanced_message += f"【当前对话】\n玩家: {message}"

            # ⭐ 3.5 世界状态与动作白名单（仅 ACTION_PROPOSAL=on 时注入）
            if self.action_enabled:
                enhanced_message += self._build_action_context(player_id)

            # prompt 长度用于验证「记忆让 prompt 变长」这条解释
            prompt_chars = len(enhanced_message)
            stage_times["t_context_ms"] = round((time.perf_counter() - t_stage) * 1000, 1)
            t_stage = time.perf_counter()

            # ⭐ 4. 调用Agent生成回复
            log_generating_response()
            response = agent.run(enhanced_message)
            log_npc_response(npc_name, response)
            stage_times["t_generate_ms"] = round((time.perf_counter() - t_stage) * 1000, 1)
            t_stage = time.perf_counter()

            # ⭐ 4.5 模型只能提议动作，是否生效由 actions.py 裁决
            response, action_result = self._handle_action_proposal(response, player_id)
            stage_times["t_action_ms"] = round((time.perf_counter() - t_stage) * 1000, 1)
            t_stage = time.perf_counter()

            # ⭐ 5. 分析并更新好感度
            log_analyzing_affinity()
            if self.relationship_manager:
                affinity_result = self.relationship_manager.analyze_and_update_affinity(
                    npc_name=npc_name,
                    player_message=message,
                    npc_response=response,
                    player_id=player_id
                )

                # 记录好感度变化详情 ⭐ 使用日志系统
                log_affinity_change(affinity_result)
            else:
                affinity_result = {"changed": False, "affinity": 50.0}
            stage_times["t_affinity_ms"] = round((time.perf_counter() - t_stage) * 1000, 1)
            t_stage = time.perf_counter()

            # ⭐ 6. 保存对话到记忆 (包含好感度信息)
            if self.memory_enabled and memory_manager:
                self._save_conversation_to_memory(
                    memory_manager=memory_manager,
                    npc_name=npc_name,
                    player_message=message,
                    npc_response=response,
                    player_id=player_id,
                    affinity_info=affinity_result
                )
                log_memory_saved(npc_name)
            stage_times["t_save_ms"] = round((time.perf_counter() - t_stage) * 1000, 1)

            self.last_metrics = {
                "model_profile": settings.MODEL_PROFILE,
                "mode": "memory_on" if self.memory_enabled else "memory_off",
                "npc": npc_name,
                "player_id": player_id,
                "message": message,
                "memory_recall_count": len(relevant_memories),
                "prompt_chars": prompt_chars,
                "reply_chars": len(response or ""),
                "t_retrieve_ms": stage_times.get("t_retrieve_ms", ""),
                "t_context_ms": stage_times.get("t_context_ms", ""),
                "t_generate_ms": stage_times.get("t_generate_ms", ""),
                "t_action_ms": stage_times.get("t_action_ms", ""),
                "t_affinity_ms": stage_times.get("t_affinity_ms", ""),
                "t_save_ms": stage_times.get("t_save_ms", ""),
                "affinity_before": affinity_result.get("old_affinity", affinity_result.get("affinity", 50.0)),
                "affinity_after": affinity_result.get("new_affinity", affinity_result.get("affinity", 50.0)),
                "affinity_proposed": affinity_result.get("proposed_change", ""),
                "affinity_rule_status": affinity_result.get("rule_status", ""),
                "affinity_rule_notes": affinity_result.get("rule_notes", ""),
                "action": action_result,
                "request_failed": False,
            }

            # 记录对话结束 ⭐ 使用日志系统
            log_dialogue_end()

            return response

        except Exception as e:
            print(f"❌ {npc_name}对话失败: {e}")
            import traceback
            traceback.print_exc()
            self.last_metrics = {
                "model_profile": settings.MODEL_PROFILE,
                "mode": "memory_on" if self.memory_enabled else "memory_off",
                "npc": npc_name, "message": message, "memory_recall_count": 0,
                "request_failed": True,
            }
            return f"抱歉,我现在有点忙,等会儿再聊吧。(错误: {str(e)})"
    
    # ==================== 世界动作提议 ====================
    # 小模型常把结尾写成 ">" 或 "}}}"，所以解析不依赖定界符：
    # 定位 <<ACTION，再用 JSONDecoder.raw_decode 取第一个完整 JSON 对象。
    ACTION_OPEN = re.compile(r"<<\s*ACTION\s*", re.IGNORECASE)

    def _build_action_context(self, player_id: str) -> str:
        """给模型看的世界状态与动作白名单（模型只能提议，不能改状态）。"""
        from actions import MAX_ITEM_TRANSFER, describe_actions
        from world_state import get_world_state

        state = get_world_state()
        state.ensure_player(player_id)
        snapshot = state.snapshot(player_id)

        quest_lines = []
        for q in snapshot.get("quests", []):
            need = q.get("required_items") or {}
            need_text = "/".join("%s×%s" % (k, v) for k, v in need.items()) or "无"
            quest_lines.append(
                "%s(%s，状态=%s，奖励=%.0f 金币，需要 %s)"
                % (q["quest_id"], q["title"], q["status"], q["reward_gold"], need_text)
            )

        lines = [
            "",
            "【世界状态 —— 由后端维护，你只能提议动作，不能直接修改】",
            "玩家金币: %.0f" % snapshot.get("gold", 0),
            "玩家背包: %s" % (snapshot.get("items") or "空"),
            "任务: %s" % ("；".join(quest_lines) or "无"),
            "",
            "【可提议的动作】",
        ]
        for item in describe_actions():
            lines.append("- %s  参数: %s —— %s" % (item["name"], item["args"], item["desc"]))
        lines += [
            "",
            "如果你认为应当执行某个动作，请在回复的最后单独一行输出：",
            '<<ACTION {"action": "动作名", "args": {...}}>>',
            "",
            "规则：",
            "1. 你只能提议，后端会校验前置条件，不通过就不会生效。",
            "2. 金币不能直接发放，只能通过完成任务获得；不要提议发放金币。",
            "3. 物品转移单次不超过 %d 个。" % MAX_ITEM_TRANSFER,
            "4. 不需要执行动作时，不要输出这一行。",
        ]
        return "\n".join(lines)

    def _handle_action_proposal(self, response: str, player_id: str):
        """解析并裁决模型提议的动作，返回 (给玩家看的文本, 裁决结果或 None)。

        解析策略：定位 ``<<ACTION`` 之后的第一个 ``{``，用 ``json.JSONDecoder.raw_decode``
        取第一个完整对象，忽略其后的任何残渣（``>``、``>>``、多余的 ``}`` 等）。
        理由见类属性处的注释 —— 小模型写不对定界符，但 JSON 本体通常是对的。
        """
        if not self.action_enabled:
            return response, None

        text = response or ""
        match = self.ACTION_OPEN.search(text)
        if not match:
            return text, None

        # 标记之后的内容一律不给玩家看（约定是"标记放最后一行"）
        clean = text[:match.start()].strip()
        brace = text.find("{", match.end() - 1)
        if brace < 0:
            print("  ⚠️ 动作标记后缺少 JSON 对象，已从回复中剥离")
            return clean, {"proposed": text[match.start():][:160], "accepted": False,
                           "code": "truncated", "message": "动作标记后缺少 JSON 对象"}

        try:
            payload, _consumed = json.JSONDecoder().raw_decode(text[brace:])
            action = str(payload.get("action", "")).strip()
            args = payload.get("args") or {}
            if not action:
                raise ValueError("缺少 action 字段")
            if not isinstance(args, dict):
                raise ValueError("args 必须是对象")
        except Exception as exc:  # 解析失败不影响正常对话
            snippet = text[brace:brace + 160]
            print(f"  ⚠️ 动作 JSON 解析失败: {exc} | 原文: {snippet}")
            return clean, {"proposed": snippet, "accepted": False,
                           "code": "parse_error", "message": str(exc)}

        from actions import apply_action
        from world_state import get_world_state

        verdict = apply_action(get_world_state(), action, args, player_id)
        result = {"proposed": action, "args": args}
        result.update(verdict.to_dict())
        print(f"  🎯 动作提议 {action} -> {'受理' if verdict.accepted else '拒绝'}"
              f" ({verdict.code}) {verdict.message}")
        return clean, result

    def _build_memory_context(self, memories: List[MemoryItem]) -> str:
        """构建记忆上下文"""
        if not memories:
            return ""

        context_parts = ["【之前的对话记忆】"]
        for memory in memories:
            # 格式化时间
            time_str = memory.timestamp.strftime("%H:%M")
            # 添加记忆内容
            context_parts.append(f"[{time_str}] {memory.content}")

        context_parts.append("")  # 空行分隔
        return "\n".join(context_parts)

    def _save_conversation_to_memory(
        self,
        memory_manager: MemoryManager,
        npc_name: str,
        player_message: str,
        npc_response: str,
        player_id: str,
        affinity_info: Optional[Dict] = None
    ):
        """保存对话到记忆系统 (包含好感度信息)"""
        current_time = datetime.now()

        # 获取好感度信息
        affinity = affinity_info.get("new_affinity", affinity_info.get("affinity", 50.0)) if affinity_info else 50.0
        affinity_change = affinity_info.get("change_amount", 0) if affinity_info else 0
        sentiment = affinity_info.get("sentiment", "neutral") if affinity_info else "neutral"

        # 保存玩家消息
        memory_manager.add_memory(
            content=f"玩家说: {player_message}",
            memory_type="working",  # 先存入工作记忆
            importance=0.5,  # 中等重要性
            auto_classify=False,  # 一律留在工作记忆：episodic 会写入全玩家共享的向量集合
            metadata={
                "speaker": "player",
                "player_id": player_id,
                "session_id": player_id,
                "timestamp": current_time.isoformat(),
                "affinity": affinity,  # ⭐ 记录当时的好感度
                "affinity_change": affinity_change,  # ⭐ 记录好感度变化
                "sentiment": sentiment,  # ⭐ 记录情感倾向
                "context": {
                    "interaction_type": "dialogue",
                    "npc_name": npc_name
                }
            }
        )

        # 保存NPC回复
        memory_manager.add_memory(
            content=f"我说: {npc_response}",
            memory_type="working",  # 先存入工作记忆
            importance=0.6,  # 稍高重要性
            auto_classify=False,  # 同上，避免跨玩家泄露
            metadata={
                "speaker": npc_name,
                "player_id": player_id,
                "session_id": player_id,
                "timestamp": current_time.isoformat(),
                "affinity": affinity,  # ⭐ 记录当时的好感度
                "sentiment": sentiment,  # ⭐ 记录情感倾向
                "context": {
                    "interaction_type": "dialogue",
                    "npc_name": npc_name
                }
            }
        )

        print(f"  💾 对话已保存到{npc_name}的记忆中")

    def get_npc_info(self, npc_name: str) -> Dict[str, str]:
        """获取NPC信息"""
        if npc_name not in NPC_ROLES:
            return {}

        role = NPC_ROLES[npc_name]
        return {
            "name": npc_name,
            "title": role["title"],
            "location": role["location"],
            "activity": role["activity"],
            "available": self.agents.get(npc_name) is not None
        }
    
    def get_all_npcs(self) -> list:
        """获取所有NPC信息"""
        return [self.get_npc_info(name) for name in NPC_ROLES.keys()]

    def get_npc_memories(self, npc_name: str, player_id: str = DEFAULT_PLAYER_ID, limit: int = 10) -> List[Dict]:
        """获取指定玩家与指定 NPC 之间的记忆列表 (用于调试和展示)"""
        memory_manager = self.memories.get(memory_key(npc_name, player_id))
        if not memory_manager:
            return []

        try:
            # 检索所有记忆
            memories = memory_manager.retrieve_memories(
                query="",  # 空查询返回所有记忆
                memory_types=["working", "episodic"],
                limit=limit
            )

            # 转换为字典格式
            memory_list = []
            for memory in memories:
                memory_list.append({
                    "id": memory.id,
                    "content": memory.content,
                    "type": memory.memory_type,
                    "importance": memory.importance,
                    "timestamp": memory.timestamp.isoformat(),
                    "metadata": memory.metadata
                })

            return memory_list

        except Exception as e:
            print(f"❌ 获取{npc_name}记忆失败: {e}")
            return []

    def clear_npc_memory(self, npc_name: str, player_id: str = DEFAULT_PLAYER_ID,
                         memory_type: Optional[str] = None):
        """清空指定玩家与指定 NPC 之间的记忆 (用于测试)"""
        memory_manager = self.memories.get(memory_key(npc_name, player_id))
        if not memory_manager:
            print(f"❌ {npc_name}/{player_id} 没有记忆系统")
            return

        try:
            if memory_type:
                # 清空指定类型的记忆
                memory_manager.clear_memory_type(memory_type)
                print(f"✅ 已清空{npc_name}的{memory_type}记忆")
            else:
                # 清空所有记忆
                for mem_type in ["working", "episodic"]:
                    try:
                        memory_manager.clear_memory_type(mem_type)
                    except:
                        pass
                print(f"✅ 已清空{npc_name}的所有记忆")

        except Exception as e:
            print(f"❌ 清空{npc_name}记忆失败: {e}")

    def get_npc_affinity(self, npc_name: str, player_id: str = "player") -> Dict:
        """获取NPC对玩家的好感度信息

        Args:
            npc_name: NPC名称
            player_id: 玩家ID

        Returns:
            好感度信息字典
        """
        if not self.relationship_manager:
            return {
                "affinity": 50.0,
                "level": "熟悉",
                "modifier": "礼貌友善,正常交流,保持专业"
            }

        affinity = self.relationship_manager.get_affinity(npc_name, player_id)
        level = self.relationship_manager.get_affinity_level(affinity)
        modifier = self.relationship_manager.get_affinity_modifier(affinity)

        return {
            "affinity": affinity,
            "level": level,
            "modifier": modifier
        }

    def get_all_affinities(self, player_id: str = "player") -> Dict[str, Dict]:
        """获取所有NPC的好感度信息

        Args:
            player_id: 玩家ID

        Returns:
            所有NPC的好感度信息
        """
        if not self.relationship_manager:
            return {}

        return self.relationship_manager.get_all_affinities(player_id)

    def set_npc_affinity(self, npc_name: str, affinity: float, player_id: str = "player"):
        """设置NPC对玩家的好感度 (用于测试)

        Args:
            npc_name: NPC名称
            affinity: 好感度值 (0-100)
            player_id: 玩家ID
        """
        if not self.relationship_manager:
            print("❌ 好感度系统未初始化")
            return

        self.relationship_manager.set_affinity(npc_name, affinity, player_id)
        level = self.relationship_manager.get_affinity_level(affinity)
        print(f"✅ 已设置{npc_name}对玩家的好感度: {affinity:.1f} ({level})")

# 全局单例
_npc_manager = None

def get_npc_manager() -> NPCAgentManager:
    """获取NPC管理器单例"""
    global _npc_manager
    if _npc_manager is None:
        _npc_manager = NPCAgentManager()
    return _npc_manager
