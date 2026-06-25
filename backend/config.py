from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    wcl_client_id: str
    wcl_client_secret: str
    # Legacy v1 key for fallback
    api_key: str = ""
    # Guild config
    guild_id: int = 821862  # Lower City Discotek on Dreamscythe
    # Azure OpenAI (Phase 3)
    azure_openai_endpoint: str = ""
    azure_openai_key: str = ""
    azure_openai_deployment: str = "gpt-4o"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
