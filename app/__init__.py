"""Flask application factory for YottaFlex."""

from __future__ import annotations

import os
import secrets

from flask import Flask

from config import config_by_name

from .blueprints import register_blueprints
from .extensions import csrf, db, login_manager, migrate


def create_app(config_name: str | None = None) -> Flask:
    """Create and configure the Flask application."""

    app = Flask(__name__)

    selected_config = config_name or os.getenv("YTF_ENV", "development")
    if selected_config not in config_by_name:
        valid_names = ", ".join(sorted(config_by_name))
        raise ValueError(
            f"Unknown configuration '{selected_config}'. Choose one of: {valid_names}."
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
    login_manager.init_app(app)
    csrf.init_app(app)

    from .blueprints.auth.limiter import LoginRateLimiter

    app.extensions["login_limiter"] = LoginRateLimiter()

    if str(app.config.get("SQLALCHEMY_DATABASE_URI", "")).startswith("sqlite"):
        from sqlalchemy import event

        with app.app_context():

            @event.listens_for(db.engine, "connect")
            def _configure_sqlite(dbapi_connection, _connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("ATTACH DATABASE ':memory:' AS yottaflex")
                cursor.close()

    @login_manager.user_loader
    def load_user(user_id: str):
        from .models import User

        try:
            return db.session.get(User, int(user_id))
        except (ValueError, TypeError):
            return None

    @login_manager.unauthorized_handler
    def unauthorized():
        from flask import flash, jsonify, redirect, request, url_for

        if request.path.startswith("/api/") or request.is_json:
            return (
                jsonify(
                    {
                        "error": "unauthorized",
                        "message": "Authentication required",
                    }
                ),
                401,
            )
        flash("Please sign in to access this page.", "warning")
        return redirect(url_for("auth.login", next=request.url))

    from . import models

    app.logger.debug(
        "Registered %d core model tables.",
        len(models.Base.metadata.tables),
    )

    register_blueprints(app)

    from .cli import register_cli

    register_cli(app)

    return app
