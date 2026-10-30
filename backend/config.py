"""配置文件"""

import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

class Settings:
    """应用配置"""
    
    # API配置
    API_TITLE = "赛博小镇 API"
    API_VERSION = "1.0.0"
    API_HOST = "0.0.0.0"
    API_PORT = 8000
    
    # NPC配置
    NPC_UPDATE_INTERVAL = 30  # NPC状态更新间隔(秒)
    
    # LLM配置 (从环境变量读取)
    # HelloAgents 使用 OpenAI 兼容接口，DeepSeek、Qwen 等服务只需要切换
    # provider、model 和 base_url，不需要改 NPC Agent 代码。
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "auto").strip().lower()
    LLM_MODEL_ID: str = os.getenv("LLM_MODEL_ID", "deepseek-chat")
    LLM_API_KEY: Optional[str] = os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
    LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "120"))

    # CORS配置
    CORS_ORIGINS = ["*"]  # 生产环境应限制具体域名

    @classmethod
    def validate(cls):
        """验证配置"""
        if not cls.LLM_API_KEY:
            print("⚠️  警告: 未设置 DeepSeek API 密钥")
            print("   请在 backend/.env 中配置 DEEPSEEK_API_KEY 或 LLM_API_KEY")
            return False

        print(f"✅ LLM配置:")
        print(f"   提供商: {cls.LLM_PROVIDER}")
        print(f"   模型: {cls.LLM_MODEL_ID}")
        print(f"   服务地址: {cls.LLM_BASE_URL}")
        return True

settings = Settings()
