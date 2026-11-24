from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../../.env", ".env"), extra="ignore")

    database_url: str = "postgresql+asyncpg://caredeploy:caredeploy@localhost:5432/caredeploy"
    cors_origins: str = "http://localhost:3100"

    # Scheduling (M2)
    authorization_ttl_minutes: int = 15
    proposal_ttl_minutes: int = 5
    operation_lease_seconds: int = 30
    idempotency_wait_seconds: float = 3.0
    verification_max_attempts: int = 5
    verification_lockout_minutes: int = 10

    # Voice (M3). Nothing here has a usable default for credentials: with them unset, session
    # creation answers 503 `voice_not_configured` instead of pretending.
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    voice_worker_secret: str = ""
    voice_agent_name: str = "caredeploy-voice"
    voice_token_ttl_seconds: int = 600

    @property
    def voice_missing(self) -> list[str]:
        pairs = {
            "LIVEKIT_URL": self.livekit_url,
            "LIVEKIT_API_KEY": self.livekit_api_key,
            "LIVEKIT_API_SECRET": self.livekit_api_secret,
            "VOICE_WORKER_SECRET": self.voice_worker_secret,
        }
        return [k for k, v in pairs.items() if not v]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sync_database_url(self) -> str:
        """Driver URL for Alembic (sync psycopg)."""
        return self.database_url.replace("+asyncpg", "+psycopg")


@lru_cache
def get_settings() -> Settings:
    return Settings()
