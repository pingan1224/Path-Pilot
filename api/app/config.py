"""Application settings, loaded from environment or a local .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Optional during P0 so the API boots before a database exists.
    database_url: str | None = None

    # Comma-separated in the environment, split into a list below.
    cors_origins: str = "http://localhost:5173"

    # LLM (Moonshot / Kimi, OpenAI-compatible). Optional: without them the assistant
    # reports itself unavailable instead of the API failing to boot.
    moonshot_api_key: str | None = None
    moonshot_base_url: str = "https://api.moonshot.cn/v1"
    chat_model: str = "kimi-k3"

    # Embeddings (OpenAI). Separate provider because Moonshot has no embeddings endpoint.
    openai_api_key: str | None = None
    embedding_model: str = "text-embedding-3-small"

    # Which chunking strategy retrieval reads. Every arm is embedded and stored at once,
    # so a chunking ablation is this one setting plus a re-run of the eval.
    chunk_strategy: str = "heading"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
