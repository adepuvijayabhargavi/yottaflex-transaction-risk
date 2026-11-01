"""Blueprint registration."""

from flask import Flask

from .alerts.routes import alerts_bp
from .api.routes import api_bp
from .auth.routes import auth_bp
from .cases.routes import cases_bp
from .dashboard.routes import dashboard_bp
from .health.routes import health_bp
from .transactions.routes import transactions_bp


def register_blueprints(app: Flask) -> None:
    """Register application blueprints."""

    app.register_blueprint(health_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(alerts_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(transactions_bp)
