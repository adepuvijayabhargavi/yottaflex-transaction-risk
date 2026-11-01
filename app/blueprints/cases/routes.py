"""Case queue and analyst case-management routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.extensions import db
from app.models import User
from app.models.enums import (
    CaseDecisionType,
    CaseNoteType,
    CasePriority,
    CaseStatus,
    UserRole,
)
from app.services.cases import (
    ALLOWED_CASE_TRANSITIONS,
    DEFAULT_PAGE_SIZE,
    MANAGER_ROLES,
    REVIEW_ROLES,
    add_case_decision,
    add_case_note,
    assign_case,
    claim_case,
    create_case,
    get_case_detail,
    link_alert_to_case,
    list_cases,
    list_eligible_alerts,
    set_case_priority,
    transition_case,
    unlink_alert_from_case,
)
from app.services.validation import ValidationError

from ..auth.security import role_required

cases_bp = Blueprint("cases", __name__, url_prefix="/cases")
E = TypeVar("E")


def _parse_enum(value: str | None, enum_class: type[E]) -> E | None:
    if not value:
        return None
    try:
        return enum_class(value.strip().upper())  # type: ignore[call-arg]
    except (TypeError, ValueError):
        return None


def _review_users() -> list[User]:
    return list(
        db.session.scalars(
            select(User)
            .where(User.is_active.is_(True), User.role.in_(REVIEW_ROLES))
            .order_by(User.full_name, User.id)
        ).all()
    )


def _is_manager() -> bool:
    return current_user.role in MANAGER_ROLES


def _execute_case_action(
    case_id: int,
    operation: Callable[[], Any],
    success_message: str,
):
    try:
        result = operation()
        if result is None:
            db.session.rollback()
            abort(404)
        db.session.commit()
    except ValidationError as exc:
        db.session.rollback()
        flash(exc.issue.message, "danger")
    except IntegrityError:
        db.session.rollback()
        flash(
            "The case could not be updated because a conflicting change occurred. "
            "Refresh the case and try again.",
            "danger",
        )
    except SQLAlchemyError:
        db.session.rollback()
        raise
    else:
        flash(success_message, "success")
    return redirect(url_for("cases.detail", case_id=case_id))


def _parse_positive_ids(values: list[str]) -> list[int] | None:
    try:
        parsed = [int(value) for value in values]
    except (TypeError, ValueError):
        return None
    if any(value < 1 for value in parsed):
        return None
    return parsed


@cases_bp.get("/")
@role_required(*REVIEW_ROLES)
def index():
    """Render the searchable and filterable case queue."""

    assigned_to = request.args.get("assigned_to", "").strip()
    assigned_to_user_id = None
    unassigned_only = assigned_to == "unassigned"
    if assigned_to and not unassigned_only:
        try:
            assigned_to_user_id = int(assigned_to)
        except ValueError:
            assigned_to_user_id = None
    result = list_cases(
        db.session,
        q=request.args.get("q"),
        status=_parse_enum(request.args.get("status"), CaseStatus),
        priority=_parse_enum(request.args.get("priority"), CasePriority),
        assigned_to_user_id=assigned_to_user_id,
        unassigned_only=unassigned_only,
        visible_to_user_id=(
            current_user.id if current_user.role == UserRole.ANALYST else None
        ),
        page=request.args.get("page", 1),
        per_page=request.args.get("per_page", DEFAULT_PAGE_SIZE),
    )
    return render_template(
        "cases/index.html",
        result=result,
        statuses=[status.value for status in CaseStatus],
        priorities=[priority.value for priority in CasePriority],
        review_users=_review_users() if _is_manager() else [],
        assigned_filter=assigned_to,
        is_manager=_is_manager(),
    )


@cases_bp.route("/new", methods=["GET", "POST"])
@role_required(*REVIEW_ROLES)
def new():
    """Render or submit the create-case form."""

    if request.method == "POST":
        alert_ids = _parse_positive_ids(request.form.getlist("alert_ids"))
        if alert_ids is None:
            flash("Select valid alerts for the case.", "danger")
            return redirect(url_for("cases.new"))
        try:
            case = create_case(
                db.session,
                current_user._get_current_object(),
                title=request.form.get("title", ""),
                description=request.form.get("description"),
                priority=request.form.get("priority", CasePriority.MEDIUM.value),
                alert_ids=alert_ids,
            )
            db.session.commit()
        except ValidationError as exc:
            db.session.rollback()
            flash(exc.issue.message, "danger")
            return redirect(url_for("cases.new"))
        except IntegrityError:
            db.session.rollback()
            flash(
                "A selected alert was linked by another request. "
                "Refresh the form and try again.",
                "danger",
            )
            return redirect(url_for("cases.new"))
        except SQLAlchemyError:
            db.session.rollback()
            raise
        flash("Case created.", "success")
        return redirect(url_for("cases.detail", case_id=case.id))

    query = request.args.get("q", "")
    selected_alert_id = request.args.get("alert_id", "")
    preferred_alert_id = int(selected_alert_id) if selected_alert_id.isdigit() else None
    alerts = list_eligible_alerts(
        db.session,
        q=query,
        alert_id=preferred_alert_id,
    )
    if (
        selected_alert_id
        and preferred_alert_id is not None
        and not any(alert["id"] == preferred_alert_id for alert in alerts)
    ):
        flash(
            "That alert is unavailable for a new case; it may already be linked "
            "or no longer open.",
            "warning",
        )
    return render_template(
        "cases/new.html",
        alerts=alerts,
        selected_alert_id=selected_alert_id,
        query=query,
        priorities=[priority.value for priority in CasePriority],
    )


@cases_bp.get("/<int:case_id>")
@role_required(*REVIEW_ROLES)
def detail(case_id: int):
    """Render one case and its append-only history."""

    case_detail = get_case_detail(db.session, case_id)
    if case_detail is None:
        abort(404)
    case = case_detail["case"]
    role = current_user.role
    is_manager = role in MANAGER_ROLES
    if role == UserRole.ANALYST and case["assigned_to_user_id"] not in (
        None,
        current_user.id,
    ):
        abort(404)
    can_work = is_manager or case["assigned_to_user_id"] == current_user.id
    eligible_alert_query = request.args.get("alert_q", "")
    transitions = sorted(
        status.value for status in ALLOWED_CASE_TRANSITIONS[CaseStatus(case["status"])]
    )
    if not is_manager:
        transitions = [
            status for status in transitions if status not in {"ESCALATED", "CLOSED"}
        ]
    return render_template(
        "cases/detail.html",
        detail=case_detail,
        is_manager=is_manager,
        can_work=can_work,
        can_claim=(
            role == UserRole.ANALYST
            and case["assigned_to_user_id"] is None
            and not case["is_closed"]
        ),
        transitions=transitions,
        priorities=[priority.value for priority in CasePriority],
        note_types=[note_type.value for note_type in CaseNoteType],
        decisions=[decision.value for decision in CaseDecisionType],
        eligible_alerts=(
            list_eligible_alerts(db.session, q=eligible_alert_query)
            if can_work and not case["is_closed"]
            else []
        ),
        eligible_alert_query=eligible_alert_query,
        review_users=_review_users() if is_manager else [],
    )


@cases_bp.post("/<int:case_id>/claim")
@role_required(*REVIEW_ROLES)
def claim(case_id: int):
    """Allow an analyst to claim an unassigned case."""

    return _execute_case_action(
        case_id,
        lambda: claim_case(
            db.session,
            case_id,
            current_user._get_current_object(),
        ),
        "Case claimed.",
    )


@cases_bp.post("/<int:case_id>/assignment")
@role_required(*REVIEW_ROLES)
def assignment(case_id: int):
    """Assign or unassign a case as a supervisor or admin."""

    raw_assignee_id = request.form.get("assignee_id", "").strip()
    if raw_assignee_id:
        try:
            assignee_id = int(raw_assignee_id)
        except ValueError:
            flash("Choose an active reviewer or unassign the case.", "danger")
            return redirect(url_for("cases.detail", case_id=case_id))
    else:
        assignee_id = None
    return _execute_case_action(
        case_id,
        lambda: assign_case(
            db.session,
            case_id,
            current_user._get_current_object(),
            assignee_id,
        ),
        "Case assignment updated.",
    )


@cases_bp.post("/<int:case_id>/priority")
@role_required(*REVIEW_ROLES)
def priority(case_id: int):
    """Change case priority as a supervisor or admin."""

    value = request.form.get("priority", "")
    return _execute_case_action(
        case_id,
        lambda: set_case_priority(
            db.session,
            case_id,
            current_user._get_current_object(),
            value,
        ),
        "Case priority updated.",
    )


@cases_bp.post("/<int:case_id>/status")
@role_required(*REVIEW_ROLES)
def status(case_id: int):
    """Transition case status with an audit reason where required."""

    return _execute_case_action(
        case_id,
        lambda: transition_case(
            db.session,
            case_id,
            current_user._get_current_object(),
            request.form.get("status", ""),
            request.form.get("reason", ""),
        ),
        "Case status updated.",
    )


@cases_bp.post("/<int:case_id>/alerts")
@role_required(*REVIEW_ROLES)
def link_alert(case_id: int):
    """Link one eligible alert to a case."""

    try:
        alert_id = int(request.form.get("alert_id", ""))
    except (TypeError, ValueError):
        flash("Choose an eligible alert.", "danger")
        return redirect(url_for("cases.detail", case_id=case_id))
    return _execute_case_action(
        case_id,
        lambda: link_alert_to_case(
            db.session,
            case_id,
            alert_id,
            current_user._get_current_object(),
        ),
        "Alert linked to case.",
    )


@cases_bp.post("/<int:case_id>/alerts/<int:link_id>/unlink")
@role_required(*REVIEW_ROLES)
def unlink_alert(case_id: int, link_id: int):
    """Soft-unlink an alert with a required reason."""

    return _execute_case_action(
        case_id,
        lambda: unlink_alert_from_case(
            db.session,
            case_id,
            link_id,
            current_user._get_current_object(),
            request.form.get("reason", ""),
        ),
        "Alert unlinked from case.",
    )


@cases_bp.post("/<int:case_id>/notes")
@role_required(*REVIEW_ROLES)
def note(case_id: int):
    """Append a case note."""

    return _execute_case_action(
        case_id,
        lambda: add_case_note(
            db.session,
            case_id,
            current_user._get_current_object(),
            body=request.form.get("body", ""),
            note_type=request.form.get("note_type", CaseNoteType.INVESTIGATION.value),
        ),
        "Case note added.",
    )


@cases_bp.post("/<int:case_id>/decisions")
@role_required(*REVIEW_ROLES)
def decision(case_id: int):
    """Append a case decision with rationale."""

    try:
        alert_id = int(request.form.get("alert_id", ""))
    except (TypeError, ValueError):
        flash("Choose an active linked alert.", "danger")
        return redirect(url_for("cases.detail", case_id=case_id))
    return _execute_case_action(
        case_id,
        lambda: add_case_decision(
            db.session,
            case_id,
            current_user._get_current_object(),
            alert_id=alert_id,
            decision=request.form.get("decision", ""),
            rationale=request.form.get("rationale", ""),
        ),
        "Case decision recorded.",
    )
