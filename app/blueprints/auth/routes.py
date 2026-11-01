"""Authentication routes for analysts, supervisors, and administrators."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy import or_, select

from app.extensions import db
from app.models import AuditEvent, User
from app.models.base import utc_now
from app.services.validation import validate_audit_event

from .forms import LoginForm
from .limiter import get_login_limiter
from .security import is_safe_redirect_url

auth_bp = Blueprint("auth", __name__)

LOGIN_SUCCESS_EVENT = "AUTH_LOGIN_SUCCESS"
LOGIN_FAILED_EVENT = "AUTH_LOGIN_FAILED"
LOGOUT_EVENT = "AUTH_LOGOUT"

LOGIN_RATE_LIMIT_MESSAGE = (
    "Too many failed sign-in attempts. Please wait before trying again."
)


def _record_auth_event(
    event_type: str,
    summary: str,
    *,
    user: User | None = None,
    details: dict[str, object] | None = None,
) -> AuditEvent:
    """Create and validate an append-only authentication audit event."""

    event = AuditEvent(
        event_type=event_type,
        entity_type="user",
        entity_id=user.id if user is not None else None,
        actor_user_id=user.id if user is not None else None,
        summary=summary,
        details=details,
        occurred_at=utc_now(),
    )
    validate_audit_event(db.session, event)
    db.session.add(event)
    return event


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Sign in with username or email and password."""

    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    form = LoginForm()
    limiter = get_login_limiter()
    client_key = request.remote_addr or "unknown"

    if request.method == "POST" and limiter.is_locked(client_key):
        _record_auth_event(
            LOGIN_FAILED_EVENT,
            "Failed sign-in attempt",
            details={"reason": "rate_limited"},
        )
        db.session.commit()
        flash(LOGIN_RATE_LIMIT_MESSAGE, "danger")
        return render_template("auth/login.html", form=form), 429

    if form.validate_on_submit():
        identifier = form.username.data.strip()
        password = form.password.data

        user = db.session.scalar(
            select(User).where(
                or_(
                    User.username == identifier,
                    User.email == identifier.lower(),
                )
            )
        )

        if user is not None and user.is_active and user.check_password(password):
            limiter.reset(client_key)
            login_user(user, remember=form.remember_me.data)
            user.last_login_at = utc_now()
            _record_auth_event(
                LOGIN_SUCCESS_EVENT,
                "Successful sign-in",
                user=user,
                details={"remember_me": bool(form.remember_me.data)},
            )
            db.session.commit()

            flash(f"Welcome back, {user.full_name}!", "success")

            next_page = request.args.get("next")
            if not is_safe_redirect_url(next_page) or next_page == url_for(
                "auth.login"
            ):
                next_page = url_for("dashboard.index")

            return redirect(next_page)

        limiter.record_failure(client_key)
        _record_auth_event(
            LOGIN_FAILED_EVENT,
            "Failed sign-in attempt",
            user=user,
            details={"reason": "invalid_credentials"},
        )
        db.session.commit()

        flash("Invalid username or password.", "danger")
        return render_template("auth/login.html", form=form), 401

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Sign out the current user after recording an audit event."""

    if current_user.is_authenticated:
        user = current_user._get_current_object()
        _record_auth_event(LOGOUT_EVENT, "User signed out", user=user)
        db.session.commit()
        logout_user()
        flash("You have been signed out successfully.", "info")

    return redirect(url_for("auth.login"))
