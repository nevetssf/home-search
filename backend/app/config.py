"""Application settings — all configuration is environment-driven.

Kept deliberately flat and free of hardcoded paths/hosts so the app lifts to a
VPS (or Postgres, or S3 media) by changing env vars only — see PLAN.md §11.
"""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ── Database ──────────────────────────────────────────────────────────
    database_url: str = "sqlite:///./home_search.db"

    # ── Auth ──────────────────────────────────────────────────────────────
    jwt_secret_key: str = "change-me-to-a-long-random-string"
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 60 * 24 * 7  # one week

    # ── Media storage abstraction ─────────────────────────────────────────
    storage_backend: str = "local"  # local | s3
    media_root: str = "./media"
    s3_endpoint_url: str = ""
    s3_bucket: str = ""
    s3_region: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""

    # ── Zillow (RapidAPI) ─────────────────────────────────────────────────
    rapidapi_key: str = ""
    rapidapi_zillow_host: str = "zillow-com1.p.rapidapi.com"

    # ── Realtor.com (HomeHarvest, no API key) ─────────────────────────────
    realtor_enabled: bool = True
    realtor_default_radius: float = 0.0  # miles; 0 = no radius expansion

    # ── Google Maps Platform ──────────────────────────────────────────────
    google_maps_api_key: str = ""

    # ── Scheduled status refresh ──────────────────────────────────────────
    status_refresh_enabled: bool = True
    status_refresh_day_of_week: str = "mon"
    status_refresh_hour: int = 4

    # ── CORS ──────────────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
