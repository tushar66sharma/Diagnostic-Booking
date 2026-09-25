from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from environment variables (or a local .env file)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://eve:eve_password@localhost:5433/eve_bookings"

    jwt_secret: str = "dev-only-jwt-secret-change-me-in-production-0123456789"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    bcrypt_rounds: int = 12  # tests lower this to keep the suite fast

    webhook_secret: str = "dev-only-webhook-secret-change-me"

    # Probability that the mock payment provider approves a charge when the
    # client does not ask for a specific outcome.
    payment_success_rate: float = 0.8

    log_level: str = "INFO"
    rate_limit_enabled: bool = True
    login_rate_limit: str = "5/minute"

    @field_validator("database_url")
    @classmethod
    def use_psycopg3_driver(cls, v: str) -> str:
        # Hosts such as Render hand out postgres:// or postgresql:// URLs; SQLAlchemy needs the
        # driver spelled out to use psycopg 3 (the only driver installed).
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v.removeprefix(prefix)
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
