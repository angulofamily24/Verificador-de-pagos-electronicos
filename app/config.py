from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
    meta_app_secret: str = os.getenv("META_APP_SECRET", "dev-secret")
    whatsapp_verify_token: str = os.getenv("WHATSAPP_VERIFY_TOKEN", "dev-token")
    ingest_token: str = os.getenv("INGEST_TOKEN", "dev-ingest-token")
    tenant_id: str = os.getenv("TENANT_ID", "default")
    match_window_minutes: int = int(os.getenv("MATCH_WINDOW_MINUTES", "30"))


_settings = Settings()


def get_settings() -> Settings:
    return _settings
