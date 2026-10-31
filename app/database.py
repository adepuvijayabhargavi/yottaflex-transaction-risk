"""Role-specific database URL helpers.

Each process should receive only the database credential it needs. The risk
engine must use :func:`risk_engine_database_url` and must never be given an
evaluation connection. Evaluation uses two separate read-only roles:
:func:`evaluation_database_url` for ground truth and
:func:`evaluation_core_database_url` for core risk results.
"""

from __future__ import annotations

import os
from enum import StrEnum

LEGACY_APP_DATABASE_URL_ENV_VAR = "YTF_DATABASE_URL"


class DatabaseRole(StrEnum):
    """Database roles with separate credentials."""

    APP = "app"
    RISK = "risk"
    EVAL = "eval"
    EVAL_CORE = "eval_core"
    GENERATOR = "generator"
    MIGRATION = "migration"
    EVAL_MIGRATION = "eval_migration"


DATABASE_URL_ENV_VARS: dict[DatabaseRole, str] = {
    DatabaseRole.APP: "YTF_APP_DATABASE_URL",
    DatabaseRole.RISK: "YTF_RISK_DATABASE_URL",
    DatabaseRole.EVAL: "YTF_EVAL_DATABASE_URL",
    DatabaseRole.EVAL_CORE: "YTF_EVAL_CORE_DATABASE_URL",
    DatabaseRole.GENERATOR: "YTF_GENERATOR_DATABASE_URL",
    DatabaseRole.MIGRATION: "YTF_MIGRATION_DATABASE_URL",
    DatabaseRole.EVAL_MIGRATION: "YTF_EVAL_MIGRATION_DATABASE_URL",
}


def _read_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return None
    return value.strip()


def database_url_for_role(
    role: DatabaseRole | str,
    *,
    required: bool = True,
) -> str | None:
    """Read the database URL for one role from its dedicated environment variable."""

    normalized_role = DatabaseRole(role)
    env_var = DATABASE_URL_ENV_VARS[normalized_role]
    value = _read_env(env_var)

    if normalized_role is DatabaseRole.APP and value is None:
        value = _read_env(LEGACY_APP_DATABASE_URL_ENV_VAR)

    if value is None and required:
        raise RuntimeError(f"{env_var} must be set to a role-specific database URL.")
    return value


def risk_engine_database_url() -> str:
    """Return only the risk-engine database URL."""

    url = database_url_for_role(DatabaseRole.RISK)
    assert url is not None
    return url


def evaluation_database_url() -> str:
    """Return only the evaluation ground-truth database URL."""

    url = database_url_for_role(DatabaseRole.EVAL)
    assert url is not None
    return url


def evaluation_core_database_url() -> str:
    """Return only the evaluation core-results database URL."""

    url = database_url_for_role(DatabaseRole.EVAL_CORE)
    assert url is not None
    return url


def generator_database_url() -> str:
    """Return only the synthetic-data generator database URL."""

    url = database_url_for_role(DatabaseRole.GENERATOR)
    assert url is not None
    return url


def migration_database_url(*, evaluation: bool = False) -> str:
    """Return the migration URL for the core or evaluation schema."""

    role = DatabaseRole.EVAL_MIGRATION if evaluation else DatabaseRole.MIGRATION
    url = database_url_for_role(role)
    assert url is not None
    return url


def risk_engine_config() -> dict[str, object]:
    """Build a SQLAlchemy configuration containing no evaluation credential."""

    return {
        "SQLALCHEMY_DATABASE_URI": risk_engine_database_url(),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SQLALCHEMY_ENGINE_OPTIONS": {"pool_pre_ping": True},
    }
