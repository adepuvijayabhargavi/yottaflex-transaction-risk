"""Role-specific database credential and package-boundary checks."""

from pathlib import Path

import pytest

from app.database import (
    DATABASE_URL_ENV_VARS,
    DatabaseRole,
    database_url_for_role,
    evaluation_core_database_url,
    evaluation_database_url,
    generator_database_url,
    migration_database_url,
    risk_engine_config,
    risk_engine_database_url,
)
from app.services import risk_engine


def _set_role_urls(monkeypatch: pytest.MonkeyPatch) -> dict[DatabaseRole, str]:
    urls = {
        role: f"mysql+pymysql://{role}:secret@localhost/{role}" for role in DatabaseRole
    }
    for role, env_var in DATABASE_URL_ENV_VARS.items():
        monkeypatch.setenv(env_var, urls[role])
    return urls


def test_each_role_has_a_distinct_environment_variable():
    env_vars = list(DATABASE_URL_ENV_VARS.values())

    assert len(env_vars) == len(DatabaseRole)
    assert len(set(env_vars)) == len(env_vars)
    assert all(name.startswith("YTF_") for name in env_vars)


def test_roles_read_only_their_own_url(monkeypatch):
    urls = _set_role_urls(monkeypatch)

    for role in DatabaseRole:
        assert database_url_for_role(role) == urls[role]

    assert risk_engine_database_url() == urls[DatabaseRole.RISK]
    assert evaluation_database_url() == urls[DatabaseRole.EVAL]
    assert evaluation_core_database_url() == urls[DatabaseRole.EVAL_CORE]
    assert generator_database_url() == urls[DatabaseRole.GENERATOR]
    assert migration_database_url() == urls[DatabaseRole.MIGRATION]
    assert migration_database_url(evaluation=True) == urls[DatabaseRole.EVAL_MIGRATION]

    assert risk_engine_database_url() != evaluation_database_url()
    assert evaluation_database_url() != evaluation_core_database_url()


def test_risk_engine_config_contains_no_evaluation_credential(monkeypatch):
    urls = _set_role_urls(monkeypatch)

    config = risk_engine_config()

    assert config["SQLALCHEMY_DATABASE_URI"] == urls[DatabaseRole.RISK]
    assert urls[DatabaseRole.EVAL] not in str(config)
    assert urls[DatabaseRole.EVAL_CORE] not in str(config)
    assert urls[DatabaseRole.EVAL_MIGRATION] not in str(config)


def test_missing_required_role_url_raises_clear_error(monkeypatch):
    monkeypatch.delenv("YTF_RISK_DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="YTF_RISK_DATABASE_URL"):
        database_url_for_role(DatabaseRole.RISK)


def test_missing_evaluation_core_url_raises_clear_error(monkeypatch):
    monkeypatch.delenv("YTF_EVAL_CORE_DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="YTF_EVAL_CORE_DATABASE_URL"):
        evaluation_core_database_url()


def test_web_app_does_not_configure_an_evaluation_bind(app):
    assert "eval" not in app.config.get("SQLALCHEMY_BINDS", {})


def test_risk_engine_package_has_no_evaluation_references():
    package_root = Path(risk_engine.__file__).parent
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in package_root.rglob("*.py")
    )

    for forbidden in (
        "app.evaluation",
        "yottaflex_eval",
        "GroundTruth",
        "ground_truth",
    ):
        assert forbidden not in source
