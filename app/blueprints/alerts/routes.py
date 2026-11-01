"""Alert queue, detail, and review workflow routes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any, TypeVar

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models import Alert, User
from app.models.enums import AlertPriority, AlertStatus, RiskLevel, UserRole
from app.services.alerts import (
    REVIEW_ROLES,
    acknowledge_alert,
    assign_alert,
    close_alert,
    dismiss_alert,
    get_alert_detail,
    list_alerts,
)
from app.services.cases import get_active_case_for_alert
from app.services.validation import ValidationError

from ..auth.security import role_required

alerts_bp = Blueprint("alerts", __name__, url_prefix="/alerts")

E = TypeVar("E")


def _parse_enum(value: str | None, enum_class: type[E]) -> E | None:
    if not value:
        return None
    try:
        return enum_class(value.strip().upper())  # type: ignore[call-arg]
    except (TypeError, ValueError):
        return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except (TypeError, ValueError):
        return None


def _page_url(result: dict[str, Any], page_number: int) -> str:
    filters = result["filters"]
    params: dict[str, Any] = {}
    if filters.q:
        params["q"] = filters.q
    if filters.priority:
        params["priority"] = filters.priority.value
    if filters.status:
        params["status"] = filters.status.value
    if filters.risk_level:
        params["risk_level"] = filters.risk_level.value
    if filters.date_from:
        params["date_from"] = filters.date_from.isoformat()
    if filters.date_to:
        params["date_to"] = filters.date_to.isoformat()
    if page_number > 1:
        params["page"] = page_number
    return url_for("alerts.index", **params)


def _page_numbers(current: int, pages: int, radius: int = 2) -> range:
    start = max(1, current - radius)
    end = min(pages, current + radius)
    return range(start, end + 1)


def _review_users() -> list[User]:
    return list(
        db.session.scalars(
            select(User)
            .where(User.is_active.is_(True), User.role.in_(REVIEW_ROLES))
            .order_by(User.full_name, User.id)
        ).all()
    )


def _execute_alert_action(
    alert_id: int,
    operation: Callable[[], Alert | None],
    success_message: str,
):
    try:
        alert = operation()
        if alert is None:
            abort(404)
        db.session.commit()
    except ValidationError as exc:
        db.session.rollback()
        flash(exc.issue.message, "danger")
    except SQLAlchemyError:
        db.session.rollback()
        raise
    else:
        flash(success_message, "success")
    return redirect(url_for("alerts.detail", alert_id=alert_id))


@alerts_bp.route("")
@alerts_bp.route("/")
@role_required(UserRole.ANALYST, UserRole.SUPERVISOR, UserRole.ADMIN)
def index():
    """Render the searchable and filterable alert queue."""

    result = list_alerts(
        db.session,
        q=request.args.get("q"),
        priority=_parse_enum(request.args.get("priority"), AlertPriority),
        status=_parse_enum(request.args.get("status"), AlertStatus),
        risk_level=_parse_enum(request.args.get("risk_level"), RiskLevel),
        date_from=_parse_date(request.args.get("date_from")),
        date_to=_parse_date(request.args.get("date_to")),
        page=request.args.get("page", 1),
    )
    pagination = result["pagination"]
    pagination["prev_url"] = (
        _page_url(result, pagination["prev_page"]) if pagination["prev_page"] else None
    )
    pagination["next_url"] = (
        _page_url(result, pagination["next_page"]) if pagination["next_page"] else None
    )
    pagination["links"] = [
        {
            "number": number,
            "url": _page_url(result, number),
            "current": number == pagination["page"],
        }
        for number in _page_numbers(pagination["page"], pagination["pages"])
    ]

    return render_template(
        "alerts/index.html",
        **result,
        priorities=[priority.value for priority in AlertPriority],
        statuses=[status.value for status in AlertStatus],
        risk_levels=[risk_level.value for risk_level in RiskLevel],
    )


@alerts_bp.route("/<int:alert_id>")
@role_required(UserRole.ANALYST, UserRole.SUPERVISOR, UserRole.ADMIN)
def detail(alert_id: int):
    """Render one alert with its assessment context and review actions."""

    alert = get_alert_detail(db.session, alert_id)
    if alert is None:
        abort(404)
    return render_template(
        "alerts/detail.html",
        alert=alert,
        assignees=_review_users(),
        active_case=get_active_case_for_alert(db.session, alert_id),
    )


@alerts_bp.post("/<int:alert_id>/assign")
@role_required(UserRole.ANALYST, UserRole.SUPERVISOR, UserRole.ADMIN)
def assign(alert_id: int):
    """Assign or unassign an alert to an active review user."""

    if db.session.get(Alert, alert_id) is None:
        abort(404)

    raw_assignee_id = request.form.get("assignee_id", "").strip()
    if raw_assignee_id:
        try:
            assignee_id = int(raw_assignee_id)
        except ValueError:
            flash("Choose a valid active reviewer.", "danger")
            return redirect(url_for("alerts.detail", alert_id=alert_id))
    else:
        assignee_id = None

    return _execute_alert_action(
        alert_id,
        lambda: assign_alert(
            db.session,
            alert_id,
            current_user._get_current_object(),
            assignee_id,
        ),
        "Alert assignment updated.",
    )


@alerts_bp.post("/<int:alert_id>/acknowledge")
@role_required(UserRole.ANALYST, UserRole.SUPERVISOR, UserRole.ADMIN)
def acknowledge(alert_id: int):
    """Acknowledge an open alert."""

    return _execute_alert_action(
        alert_id,
        lambda: acknowledge_alert(
            db.session,
            alert_id,
            current_user._get_current_object(),
        ),
        "Alert acknowledged.",
    )


@alerts_bp.post("/<int:alert_id>/close")
@role_required(UserRole.ANALYST, UserRole.SUPERVISOR, UserRole.ADMIN)
def close(alert_id: int):
    """Close an alert with a required reason."""

    return _execute_alert_action(
        alert_id,
        lambda: close_alert(
            db.session,
            alert_id,
            current_user._get_current_object(),
            request.form.get("reason", ""),
        ),
        "Alert closed.",
    )


@alerts_bp.post("/<int:alert_id>/dismiss")
@role_required(UserRole.ANALYST, UserRole.SUPERVISOR, UserRole.ADMIN)
def dismiss(alert_id: int):
    """Dismiss an alert with a required reason."""

    return _execute_alert_action(
        alert_id,
        lambda: dismiss_alert(
            db.session,
            alert_id,
            current_user._get_current_object(),
            request.form.get("reason", ""),
        ),
        "Alert dismissed.",
    )
