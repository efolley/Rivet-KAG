from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:5173"]

    database_url: str = "postgresql+asyncpg://rivet:rivet@localhost:5432/rivet"
    redis_url: str = "redis://localhost:6379/0"
    kafka_bootstrap_servers: str = "localhost:9092"
    milvus_uri: str = "./data/milvus.db"  # local Milvus Lite file; or http://host:19530 for a server
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "rivet-dev-password"

    llm_model: str = "claude-sonnet-5"
    anthropic_api_key: str = ""  # set to switch the parser/router and answerer from stub to real

    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    jwt_secret: str = Field(default="change-me", repr=False)
    jwt_ttl_minutes: int = 60
    response_cache_ttl_seconds: int = 300  # how long an identical question reuses a cached /api/chat answer

    use_stubs: bool = True  # False switches to real Milvus/Neo4j retrieval; independent of ANTHROPIC_API_KEY


@lru_cache
def get_settings() -> Settings:
    return Settings()
