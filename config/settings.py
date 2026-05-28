"""
DARKFLOW OTC — Settings
Centraliza todas as configurações via pydantic-settings.
"""

from pydantic_settings import BaseSettings
from pathlib import Path
from functools import lru_cache


class Settings(BaseSettings):

    # ── App ───────────────────────────────────────────────────────────────────
    app_name: str = "DARKFLOW OTC AI ENGINE"
    app_env: str = "development"
    app_port: int = 8000
    debug: bool = True

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "darkflow"
    postgres_password: str = ""
    postgres_db: str = "darkflow_otc"
    database_url: str = ""

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_url: str = "redis://localhost:6379/0"

    # ── ChromaDB ──────────────────────────────────────────────────────────────
    chroma_host: str = "localhost"
    chroma_port: int = 8001

    # ── Qdrant ────────────────────────────────────────────────────────────────
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333

    # ── AI / DeepSeek ─────────────────────────────────────────────────────────
    deepseek_api_key: str = ""
    deepseek_model_main: str = "deepseek-chat"
    deepseek_model_reasoner: str = "deepseek-reasoner"

    # ── Telegram ───────────────────────────────────────────────────────────────
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # ── Capture ───────────────────────────────────────────────────────────────
    quotex_url: str = "https://quotex.io"
    quotex_email: str = ""
    quotex_password: str = ""
    capture_headless: bool = False
    capture_timeout: int = 30000

    # ── Paths ─────────────────────────────────────────────────────────────────
    data_dir: Path = Path("./data")
    logs_dir: Path = Path("./logs")
    models_dir: Path = Path("./ai/models")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
