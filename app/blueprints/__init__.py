"""Blueprint registration."""

from flask import Flask

from .health.routes import health_bp


def register_blueprints(app: Flask) -> None:
    """Register application blueprints."""

    app.register_blueprint(health_bp)
