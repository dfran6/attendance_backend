from typing import List, Optional

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_ENV: str = "development"  # development | test | staging | production

    DATABASE_URL: str
    REDIS_URL: Optional[str] = None
    # Kept for backwards compatibility with the original redis helpers.
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    QR_CHALLENGE_TTL_SECONDS: int = 20

    CORS_ORIGINS: str = "http://localhost:3000"
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"
    COOKIE_DOMAIN: Optional[str] = None

    # Format check only — it does not prove the code belongs to a serving corps member.
    STATE_CODE_PATTERN: str = r"^[A-Z]{2}/\d{2}[A-C]/\d{4,5}$"

    DOMAIN: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("DATABASE_URL")
    @classmethod
    def _database_url_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("DATABASE_URL is empty. Set it in .env (see .env.example).")
        return value

    @field_validator("COOKIE_SAMESITE")
    @classmethod
    def _samesite(cls, value: str) -> str:
        value = value.lower()
        if value not in {"lax", "strict", "none"}:
            raise ValueError("COOKIE_SAMESITE must be lax, strict or none")
        return value

    @model_validator(mode="after")
    def _production_guards(self) -> "Settings":
        if self.is_production:
            if len(self.JWT_SECRET) < 32:
                raise ValueError("JWT_SECRET must be at least 32 characters in production")
            if not self.COOKIE_SECURE:
                raise ValueError("COOKIE_SECURE must be true in production")
            if not self.REDIS_URL:
                raise ValueError("REDIS_URL is required in production (rate limiting across workers)")
        if self.COOKIE_SAMESITE == "none" and not self.COOKIE_SECURE:
            raise ValueError("COOKIE_SAMESITE=none requires COOKIE_SECURE=true")
        return self

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


Config = Settings()
