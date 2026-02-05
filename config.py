# config.py - 使用 pydantic-settings 管理环境配置

from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置，从环境变量加载。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # MongoDB：URI 必填；若 URI 中已带数据库路径（如 .../openclaw_llm_bridge?authSource=admin），可省略 MONGODB_DB
    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DB: str = ""  # 为空时从 MONGODB_URI 的 path 解析，解析不到则用默认值

    # 管理端安全
    ADMIN_TOKEN: str = ""

    # LiteLLM / Azure 后端
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gpt-5-nano"
    LLM_ENDPOINT: str = "https://monster.cognitiveservices.azure.com"
    LLM_API_VERSION: str = "2024-12-01-preview"

    # 可选：tiktoken 编码，与模型对齐
    TIKTOKEN_ENCODING: str = "cl100k_base"


def get_settings() -> Settings:
    return Settings()


def get_mongodb_database() -> str:
    """实际使用的数据库名：优先 MONGODB_DB；为空则从 MONGODB_URI 的 path 解析。"""
    s = get_settings()
    if s.MONGODB_DB and s.MONGODB_DB.strip():
        return s.MONGODB_DB.strip()
    parsed = urlparse(s.MONGODB_URI)
    path = (parsed.path or "").strip("/")
    if path:
        return path.split("/")[0]
    return "openclaw_llm_bridge"
