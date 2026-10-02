from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProvider = Literal["anthropic", "openai", "ollama"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:5173"]

    database_url: str = "postgresql+asyncpg://rivet:rivet@localhost:5432/rivet"
    redis_url: str = "redis://localhost:6379/0"
    kafka_bootstrap_servers: str = "localhost:9092"
    # Env var deliberately isn't MILVUS_URI: pymilvus's own settings.py calls load_dotenv() on
    # import and reads that exact name itself (as a server address, not a Lite file path) —
    # letting our .env set MILVUS_URI collides with it and breaks pymilvus's own connection
    # singleton before our code ever runs. RIVET_MILVUS_URI avoids the collision.
    milvus_uri: str = Field(
        default="./data/milvus.db", validation_alias="RIVET_MILVUS_URI"
    )  # local Milvus Lite file; or http://host:19530 for a server
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "rivet-dev-password"

    llm_provider: LLMProvider = "anthropic"  # picks the answerer's model backend; parser/router stays Anthropic-only
    llm_model: str = "claude-sonnet-5"
    anthropic_api_key: str = ""  # set to switch the parser/router and answerer from stub to real
    openai_api_key: str = ""  # required when llm_provider=openai
    ollama_host: str = "http://localhost:11434"  # local server, no key needed, when llm_provider=ollama

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
