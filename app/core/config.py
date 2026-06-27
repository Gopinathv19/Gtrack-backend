"""Application configuration loaded from environment variables."""
from functools import lru_cache
from typing import List

from pydantic import Field, AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # App
    APP_NAME: str = "Gtrack"
    APP_ENV: str = "development"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+psycopg2://postgres:postgres@localhost:5432/gtrack"
    )
    ASYNC_DATABASE_URL: str | None = None

    # Supabase
    SUPABASE_URL: str | None = None
    SUPABASE_ANON_KEY: str | None = None
    SUPABASE_SERVICE_ROLE_KEY: str | None = None
    SUPABASE_JWT_SECRET: str | None = None

    # JWT
    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    JWT_ISSUER: str = "gtrack"
    JWT_AUDIENCE: str = "gtrack-api"

    # Invites
    INVITE_EXPIRE_HOURS: int = 72
    INVITE_BASE_URL: str = "http://localhost:3000/accept-invite"

    # Rate limiting
    RATE_LIMIT_PER_MINUTE: int = 100

    # CORS
    BACKEND_CORS_ORIGINS: List[str] = ["http://localhost:3000"]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v):
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",") if i.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
