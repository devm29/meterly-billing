from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_ADMIN_KEY = "mtr_admin_dev_only"
DEV_INGEST_KEY = "mtr_ingest_dev_only"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="METERLY_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = False

    database_url: PostgresDsn = PostgresDsn("postgresql+asyncpg://meterly@localhost:5507/meterly")
    database_pool_size: int = Field(default=10, ge=1, le=100)
    redis_url: RedisDsn = RedisDsn("redis://localhost:6407/0")

    cors_origins: list[str] = ["http://localhost:3107"]

    admin_api_key: SecretStr = Field(
        default=SecretStr(DEV_ADMIN_KEY), description="Full access: billing, plans, invoices"
    )
    ingest_api_key: SecretStr = Field(
        default=SecretStr(DEV_INGEST_KEY),
        description="Product-side key: event ingestion and entitlement checks only",
    )

    max_batch_size: int = Field(default=1000, ge=1, le=10_000)
    max_future_skew_seconds: int = Field(default=300, ge=0)
    late_event_threshold_minutes: int = Field(default=60, ge=1)

    close_grace_minutes: int = Field(
        default=60, ge=0, description="How long after a period ends to wait for late events"
    )
    draft_review_hours: int = Field(
        default=72, ge=0, description="How long a draft invoice stays open for re-rating"
    )
    entitlement_cache_ttl_seconds: int = Field(default=15, ge=1, le=3600)

    invoice_number_prefix: str = "MTR"
    seller_name: str = "Meterly Cloud, Inc."
    seller_address: str = "500 Howard Street, San Francisco, CA 94105"

    @model_validator(mode="after")
    def _real_keys_in_production(self) -> Settings:
        if self.env != "production":
            return self
        for name, key in (("admin", self.admin_api_key), ("ingest", self.ingest_api_key)):
            value = key.get_secret_value()
            if value in {DEV_ADMIN_KEY, DEV_INGEST_KEY} or len(value) < 24:
                raise ValueError(f"set a real {name} API key (24+ characters) in production")
        if self.admin_api_key == self.ingest_api_key:
            raise ValueError("admin and ingest API keys must differ")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
