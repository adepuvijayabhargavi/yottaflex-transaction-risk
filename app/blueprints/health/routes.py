"""Basic application health checks."""

from flask import Blueprint, jsonify

health_bp = Blueprint("health", __name__)


@health_bp.get("/health")
@health_bp.get("/api/v1/health")
def health_check():
    """Return a simple status response without touching the database."""

    return (
        jsonify(
            {
                "status": "ok",
                "service": "yottaflex-transaction-risk",
                "phase": 1,
            }
        ),
        200,
    )
