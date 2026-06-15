from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    APP_NAME: str = "3 ANH EM"
    SECRET_KEY: str = "change-this-to-a-secure-random-secret-in-production"

    DATABASE_URL: str = "sqlite+aiosqlite:////app/data/app.db"

    LLM_BASE_URL: str = "https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1"
    LLM_API_KEY: str = ""
    DEFAULT_MODEL: str = "qwen2.5-72b-instruct"

    FOOTBALL_API_KEY: str = ""

    AGENT_BOT_LOGIN: str = "3anhem-bot"
    AGENT_COMMIT_PREFIX: str = "[auto-docs]"

    REPOS_PATH: str = "/app/data/repos"

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
