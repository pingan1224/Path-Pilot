"""Application settings, loaded from environment or a local .env file."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Anchored to this file, not the working directory, so `uvicorn --app-dir api`
        # from the repo root finds the same .env as everything run from api/ itself.
        env_file=Path(__file__).resolve().parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Optional during P0 so the API boots before a database exists.
    database_url: str | None = None

    # Comma-separated in the environment, split into a list below.
    cors_origins: str = "http://localhost:5173"

    # One provider for everything since 2026-08-14: chat, embeddings and the intake
    # vision endpoint all run on OPENAI_API_KEY. It was two vendors before that (chat on
    # Moonshot Kimi via its OpenAI-compatible endpoint, everything else on OpenAI);
    # services/llm.py is still the only file that knows which vendor serves the
    # conversation, so switching back is that file plus these settings.
    #
    # Optional: without a key the assistant reports itself unavailable instead of the
    # API failing to boot.
    openai_api_key: str | None = None
    chat_model: str = "gpt-5.4-mini"
    # gpt-5-family models take a reasoning-effort knob; None means don't send the
    # parameter, which keeps a non-reasoning CHAT_MODEL (gpt-4.1 line) working unchanged.
    chat_reasoning_effort: str | None = None
    embedding_model: str = "text-embedding-3-small"

    # Which chunking strategy retrieval reads. Every arm is embedded and stored at once,
    # so a chunking ablation is this one setting plus a re-run of the eval.
    chunk_strategy: str = "heading"

    # "vector" (dense only) or "hybrid" (dense + lexical, fused by RRF).
    retrieval_mode: str = "vector"

    # Arms `app.faults`, which lets a probe break embeddings, the chat model, a tool, or
    # retrieval on purpose to watch the degraded paths run. Off by default and must stay
    # off anywhere real: with it disabled no fault can be armed at all, so the injection
    # points compile down to a settings read.
    fault_injection: bool = False

    # Signs the session cookie. The default exists so local development runs without
    # setup; it is deliberately obvious, and deployment must override it — a predictable
    # signing key means anyone can mint a session for any role.
    session_secret: str = "dev-only-insecure-change-me"
    session_https_only: bool = False

    # Passwords for the seeded demo accounts. Public by design — the whole point is that
    # a reader can sign in as each role — but set from the environment so the deployed
    # instance can rotate them without a code change.
    demo_password: str = "path-pilot-demo-2026"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
