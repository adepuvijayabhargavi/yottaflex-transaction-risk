"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from typing import ClassVar

from dotenv import load_dotenv

from app.database import DatabaseRole, database_url_for_role

load_dotenv()


def _env_int(name: str, default: int) -> int:
    """Read an integer environment variable with a clear error message."""

    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default

    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc


class BaseConfig:
    """Settings shared by all environments."""

    SECRET_KEY = os.getenv("YTF_SECRET_KEY")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS: ClassVar[dict[str, bool]] = {"pool_pre_ping": True}
    JSON_SORT_KEYS = False

    YTF_SEED = _env_int("YTF_SEED", 20261022)
    YTF_ALERT_THRESHOLD = _env_int("YTF_ALERT_THRESHOLD", 40)
    YTF_DATA_REFERENCE_UTC = os.getenv(
        "YTF_DATA_REFERENCE_UTC",
        "2026-10-30T00:00:00+00:00",
    )


class DevelopmentConfig(BaseConfig):
    """Local development settings.

    A safe in-memory SQLite fallback lets local checks run before MySQL
    credentials are configured. Set YTF_APP_DATABASE_URL in .env to use the
    real MySQL core schema.
    """

    DEBUG = True
    SQLALCHEMY_DATABASE_URI = (
        database_url_for_role(DatabaseRole.APP, required=False) or "sqlite:///:memory:"
    )


class TestingConfig(BaseConfig):
    """Automated test settings."""

    TESTING = True
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.getenv("YTF_TEST_DATABASE_URL") or "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False


class ProductionConfig(BaseConfig):
    """Production settings.

    YTF_APP_DATABASE_URL and YTF_SECRET_KEY are required at startup.
    """

    DEBUG = False
    SQLALCHEMY_DATABASE_URI = database_url_for_role(
        DatabaseRole.APP,
        required=False,
    )


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
