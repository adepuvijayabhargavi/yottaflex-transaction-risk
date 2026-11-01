"""Analyst operations dashboard routes and statistics API."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, redirect, render_template, url_for

from app.extensions import db
from app.models.enums import UserRole
from app.services.dashboard import get_dashboard_stats

from ..auth.security import role_required

dashboard_bp = Blueprint("dashboard", __name__)


def _dashboard_stats():
    """Return dashboard stats scoped by configured model version and metadata."""

    reference_date = current_app.config.get("YTF_DATA_REFERENCE_UTC")
    if reference_date:
        reference_date = reference_date[:10]

    return get_dashboard_stats(
        db.session,
        model_version=current_app.config["YTF_DASHBOARD_MODEL_VERSION"],
        reference_date=reference_date,
        alert_threshold=current_app.config["YTF_ALERT_THRESHOLD"],
    )


@dashboard_bp.route("/")
def root():
    """Redirect root to the operations dashboard."""
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/dashboard")
@role_required(UserRole.ANALYST, UserRole.SUPERVISOR, UserRole.ADMIN)
def index():
    """Render the primary analyst operations dashboard."""
    stats = _dashboard_stats()
    return render_template("dashboard/index.html", stats=stats)


@dashboard_bp.route("/api/v1/dashboard/stats")
@role_required(UserRole.ANALYST, UserRole.SUPERVISOR, UserRole.ADMIN)
def stats_api():
    """Return aggregated dashboard statistics and indicators as JSON."""
    stats = _dashboard_stats()
    return jsonify(stats)
