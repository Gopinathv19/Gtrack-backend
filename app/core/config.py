"""Application configuration loaded from environment variables."""
import json
from functools import lru_cache
from typing import List, Union

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
    # NOTE: typed as Union[str, List[str]] so pydantic-settings does NOT try to
    # JSON-decode the raw env value before our validator runs. This lets users
    # provide either a JSON array (`["https://a.com","https://b.com"]`) OR a
    # simple comma-separated string (`https://a.com,https://b.com`) OR `*`.
    BACKEND_CORS_ORIGINS: Union[str, List[str]] = ["http://localhost:3000"]

    # Refresh token cookie
    REFRESH_COOKIE_NAME: str = "refresh_token"
    REFRESH_COOKIE_PATH: str = "/api/v1/auth"
    REFRESH_COOKIE_SECURE: bool = False  # set True in production (HTTPS)
    REFRESH_COOKIE_SAMESITE: str = "lax"  # "lax" | "strict" | "none"
    REFRESH_COOKIE_DOMAIN: str | None = None

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v):
        # Already a list -> keep as is
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            # JSON array form: ["https://a.com","https://b.com"]
            if v.startswith("["):
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return [str(i).strip() for i in parsed if str(i).strip()]
                except json.JSONDecodeError:
                    pass
            # Comma-separated form or single origin (e.g. "*", "https://a.com,https://b.com")
            return [i.strip() for i in v.split(",") if i.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
