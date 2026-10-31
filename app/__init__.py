"""Flask application factory for YottaFlex."""

from __future__ import annotations

import os
import secrets

from flask import Flask

from config import config_by_name

from .blueprints import register_blueprints
from .extensions import db, migrate


def create_app(config_name: str | None = None) -> Flask:
    """Create and configure the Flask application."""

    app = Flask(__name__)

    selected_config = config_name or os.getenv("YTF_ENV", "development")
    if selected_config not in config_by_name:
        valid_names = ", ".join(sorted(config_by_name))
        raise ValueError(
            f"Unknown configuration '{selected_config}'. "
            f"Choose one of: {valid_names}."
        )

    app.config.from_object(config_by_name[selected_config])

    if selected_config == "production":
        if not app.config.get("SECRET_KEY"):
            raise RuntimeError("YTF_SECRET_KEY must be set in production.")
        if not app.config.get("SQLALCHEMY_DATABASE_URI"):
            raise RuntimeError("YTF_APP_DATABASE_URL must be set in production.")

    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = secrets.token_hex(32)
        app.logger.warning(
            "YTF_SECRET_KEY is not set. Using an ephemeral key for this process."
        )

    db.init_app(app)
    migrate.init_app(app, db)

    from . import models

    app.logger.debug(
        "Registered %d core model tables.",
        len(models.Base.metadata.tables),
    )

    register_blueprints(app)

    from .cli import register_cli

    register_cli(app)

    return app
