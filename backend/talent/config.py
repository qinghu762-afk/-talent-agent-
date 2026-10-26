import ipaddress
import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://talent:talent@postgres/talent"
    redis_url: str = "redis://redis:6379/0"
    milvus_url: str = "http://milvus:19530"
    ollama_url: str = "http://host.docker.internal:11434"
    mineru_url: str = "http://mineru:8001"
    chat_model: str = "qwen3:4b"
    embedding_model: str = "bge-m3"
    embedding_dimension: int = 1024
    model_timeout: int = 240
    data_dir: Path = Path("data")
    jwt_secret: str = ""
    admin_username: str = "admin"
    admin_password: str = ""
    session_hours: int = 8
    max_file_bytes: int = 20 * 1024 * 1024
    max_batch_files: int = 200
    max_batch_bytes: int = 200 * 1024 * 1024

    @model_validator(mode="after")
    def private_endpoints(self):
        for value in (self.ollama_url, self.mineru_url, self.milvus_url):
            host = urlparse(value).hostname or ""
            try:
                private = ipaddress.ip_address(host).is_private
            except ValueError:
                private = bool(host) and ("." not in host or host.endswith((".local", ".internal")))
            if not private:
                raise ValueError("模型与解析服务地址必须为本机或内网地址")
        return self


@lru_cache
def settings():
    # Disable tracing even if a parent environment enabled it.
    for key in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"):
        os.environ[key] = "false"
    return Settings()

