from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass
class DialogueResult:
    text: str
    provider: str


class DialogueModel:
    """Optional OpenAI-compatible dialogue provider with a safe local fallback.

    DeepSeek is selected when DEEPSEEK_API_KEY is present. A local model can be
    exposed through any OpenAI-compatible endpoint using CYBERTOWN_LOCAL_LLM_BASE_URL.
    """

    def __init__(self) -> None:
        self.provider = os.getenv("CYBERTOWN_LLM_PROVIDER", "auto").lower()
        self.deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
        self.local_url = os.getenv("CYBERTOWN_LOCAL_LLM_BASE_URL", "")
        self.local_key = os.getenv("CYBERTOWN_LOCAL_LLM_API_KEY", "local")
        self.model = os.getenv("CYBERTOWN_LLM_MODEL", "deepseek-chat")
        self._client: Any = None
        self.active_provider = "fallback"
        self._configure()

    def _configure(self) -> None:
        base_url = None
        api_key = ""
        if self.provider in {"deepseek", "auto"} and self.deepseek_key:
            base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
            api_key = self.deepseek_key
            self.model = os.getenv("DEEPSEEK_MODEL", self.model)
            self.active_provider = "deepseek"
        elif self.provider in {"local", "auto"} and self.local_url:
            base_url = self.local_url
            api_key = self.local_key
            self.model = os.getenv("CYBERTOWN_LOCAL_LLM_MODEL", "local-model")
            self.active_provider = "local"
        if not base_url:
            return
        try:
            from openai import OpenAI

            self._client = OpenAI(api_key=api_key, base_url=base_url)
        except Exception:
            self._client = None
            self.active_provider = "fallback"

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def reply(self, *, npc_name: str, npc_role: str, message: str, memories: list[dict[str, Any]]) -> DialogueResult:
        if not self._client:
            return DialogueResult("", "fallback")
        memory_text = "\n".join(f"- {item.get('text', '')}" for item in memories[-4:]) or "暂无历史记忆"
        system = (
            "你是赛博小镇中的 NPC。请用自然、简短、友好的中文回答玩家。"
            "保持角色设定，不要声称拥有现实世界能力。只输出给玩家看的回复文本。\n"
            f"角色：{npc_name}，职业：{npc_role}\n最近记忆：\n{memory_text}"
        )
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": message}],
                temperature=0.7,
                max_tokens=180,
                timeout=30,
            )
            text = (response.choices[0].message.content or "").strip()
            if text:
                return DialogueResult(text, self.active_provider)
        except Exception:
            pass
        return DialogueResult("", "fallback")
