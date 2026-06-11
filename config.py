from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8")

    BOT_PROVIDER: str = "mock"
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-opus-4-8"
    VEXA_URL: str = "http://localhost:8056"
    VEXA_API_KEY: str = ""
    VEXA_BOT_EMAIL: str = "bot@centralagent.ai"
    DATABASE_URL: str = "sqlite:///./meetings.db"

    GMAIL_ENABLED: bool = False
    GMAIL_CREDENTIALS_FILE: str = "credentials.json"
    GMAIL_TOKEN_FILE: str = "token.json"
    GMAIL_POLL_INTERVAL: int = 5
    GMAIL_QUERY: str = "meet.google.com newer_than:1d"
    GMAIL_MAX_CONCURRENT_BOTS: int = 10


@lru_cache()
def get_settings() -> Settings:
    return Settings()
