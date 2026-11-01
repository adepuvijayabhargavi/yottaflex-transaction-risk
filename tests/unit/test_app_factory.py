"""Application factory and configuration tests."""

from __future__ import annotations

import pytest
from flask import Flask

from app import create_app
from config import config_by_name


class _ProductionLikeConfig:
    """Minimal production-like config for factory validation tests."""

    DEBUG = False
    SECRET_KEY = None
    SQLALCHEMY_DATABASE_URI = None
    SQLALCHEMY_TRACK_MODIFICATIONS = False


def test_known_configuration_names_are_available():
    assert {"development", "testing", "production"} == set(config_by_name)


def test_create_app_uses_testing_configuration():
    app = create_app("testing")

    assert isinstance(app, Flask)
    assert app.config["TESTING"] is True
    assert app.config["DEBUG"] is False
    assert app.config["WTF_CSRF_ENABLED"] is False
    assert app.config["SECRET_KEY"]
    assert app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] is False
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.config["REMEMBER_COOKIE_HTTPONLY"] is True
    assert app.config["YTF_DASHBOARD_MODEL_VERSION"] == "v1.0.1"
    assert app.config["YTF_LOGIN_MAX_ATTEMPTS"] == 5


def test_production_config_enables_secure_cookies():
    production_config = config_by_name["production"]

    assert production_config.SESSION_COOKIE_SECURE is True
    assert production_config.REMEMBER_COOKIE_SECURE is True
    assert production_config.SESSION_COOKIE_HTTPONLY is True
    assert production_config.REMEMBER_COOKIE_HTTPONLY is True


def test_create_app_registers_health_blueprint():
    app = create_app("testing")

    assert "health" in app.blueprints


def test_create_app_has_no_evaluation_bind():
    app = create_app("testing")

    assert "eval" not in app.config.get("SQLALCHEMY_BINDS", {})
    assert "eval_core" not in app.config.get("SQLALCHEMY_BINDS", {})


def test_create_app_rejects_unknown_configuration():
    with pytest.raises(ValueError, match="Unknown configuration"):
        create_app("does-not-exist")


def test_create_app_requires_secret_key_in_production(monkeypatch):
    monkeypatch.setitem(config_by_name, "production", _ProductionLikeConfig)

    with pytest.raises(RuntimeError, match="YTF_SECRET_KEY"):
        create_app("production")


def test_create_app_requires_app_database_url_in_production(monkeypatch):
    class _ConfiguredProduction(_ProductionLikeConfig):
        SECRET_KEY = "test-secret"

    monkeypatch.setitem(config_by_name, "production", _ConfiguredProduction)

    with pytest.raises(RuntimeError, match="YTF_APP_DATABASE_URL"):
        create_app("production")
