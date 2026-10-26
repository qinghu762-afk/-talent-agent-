from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    mysql_url: str = "mysql+asyncmy://talent:talent@mysql/talent"
    postgres_url: str = "postgresql+asyncpg://talent:talent@postgres/talent_analytics"
    redis_url: str = "redis://redis:6379/0"
    data_dir: Path = Path("data")
    jwt_secret: str = ""
    admin_password: str = ""
    internal_service_key: str = ""
    ai_service_url: str = "http://ai:8000"
    analytics_service_url: str = "http://analytics:8000"
    parser_url: str = "http://parser:8000"
    dify_public_url: str = "http://localhost:18081"
    chat_model: str = "qwen3:4b"
    embedding_model: str = "bge-m3"
    cookie_secure: bool = False
    allowed_origins: str = "http://localhost:18080,http://127.0.0.1:18080"
    max_file_bytes: int = 20 * 1024 * 1024
    max_batch_files: int = 200
    worker_lease_seconds: int = 900

    @property
    def testing(self):
        return self.mysql_url.startswith("sqlite") and self.postgres_url.startswith("sqlite")


@lru_cache
def settings():
    return Settings()
