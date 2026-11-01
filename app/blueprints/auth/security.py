"""Role-based access control and security utility functions."""

from __future__ import annotations

from functools import wraps
from urllib.parse import urlsplit

from flask import flash, jsonify, redirect, request, url_for
from flask_login import current_user

from app.models.enums import UserRole


def is_safe_redirect_url(target: str | None) -> bool:
    """Return True only for same-host absolute URLs or local absolute paths.

    Rejects protocol-relative URLs, external hosts, backslashes, malformed
    schemes, control characters, and relative paths that browsers could
    normalize into an external destination.
    """

    if not isinstance(target, str):
        return False

    candidate = target.strip()
    if not candidate:
        return False

    if "\\" in candidate or "%5c" in candidate.lower():
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in candidate):
        return False

    test_url = urlsplit(candidate)

    if test_url.scheme:
        if test_url.scheme.lower() not in ("http", "https"):
            return False
        if not test_url.netloc:
            return False
    else:
        if candidate.startswith("//"):
            return False
        if not candidate.startswith("/"):
            return False

    ref_url = urlsplit(request.host_url)
    if test_url.netloc:
        return test_url.netloc.lower() == ref_url.netloc.lower()

    return True


def role_required(*roles: UserRole | str):
    """Decorator requiring the authenticated user to possess an authorized role."""

    def decorator(fn):
        @wraps(fn)
        def decorated_view(*args, **kwargs):
            if not current_user.is_authenticated:
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

            allowed_role_values = {
                r.value if isinstance(r, UserRole) else str(r) for r in roles
            }
            user_role = (
                current_user.role.value
                if hasattr(current_user.role, "value")
                else str(current_user.role)
            )

            if user_role not in allowed_role_values:
                if request.path.startswith("/api/") or request.is_json:
                    return (
                        jsonify(
                            {
                                "error": "forbidden",
                                "message": "Insufficient permissions for this resource",
                            }
                        ),
                        403,
                    )
                flash(
                    "Access denied: You do not have permission to view this resource.",
                    "danger",
                )
                return redirect(url_for("dashboard.index"))

            return fn(*args, **kwargs)

        return decorated_view

    return decorator
