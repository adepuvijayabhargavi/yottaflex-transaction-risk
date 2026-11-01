"""Authentication, password security, session, and role-based access tests."""

from __future__ import annotations

import pytest
from click.testing import CliRunner
from flask import jsonify

from app import create_app
from app.blueprints.auth.security import is_safe_redirect_url, role_required
from app.cli import auth_cli
from app.extensions import db
from app.models import AuditEvent, Base, User
from app.models.enums import UserRole


@pytest.fixture()
def auth_app():
    """Create a Flask test application with initialized database tables."""
    test_app = create_app("testing")
    with test_app.app_context():
        Base.metadata.create_all(db.engine)
        yield test_app
        db.session.rollback()
        Base.metadata.drop_all(db.engine)


@pytest.fixture()
def auth_client(auth_app):
    """Test client for auth tests."""
    return auth_app.test_client()


def _create_user(
    username: str = "analyst1",
    email: str = "analyst1@yottaflex.bank",
    password: str = "SecurePass123!",
    role: UserRole = UserRole.ANALYST,
    is_active: bool = True,
) -> User:
    user = User(
        username=username,
        email=email,
        full_name="Operations Analyst",
        role=role,
        is_active=is_active,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def test_user_password_hashing():
    """Verify password hashing with scrypt and non-plain storage."""
    user = User(
        username="hashing_test",
        email="hashing@test.bank",
        full_name="Hashing Test",
        role=UserRole.ANALYST,
    )
    user.set_password("MySecretPass99#")

    assert user.password_hash != "MySecretPass99#"
    assert user.check_password("MySecretPass99#") is True
    assert user.check_password("WrongPassword") is False
    assert user.get_id() is not None


def test_login_page_renders_form(auth_client):
    """GET /login returns 200 and renders the login form."""
    response = auth_client.get("/login")
    assert response.status_code == 200
    assert b"YottaFlex Risk Operations" in response.data
    assert b"Sign In to Operations Console" in response.data


def test_login_successful_flow(auth_app, auth_client):
    """POST /login with valid credentials logs the user in and redirects to dashboard."""
    with auth_app.app_context():
        _create_user(username="jane_analyst", password="ValidPassword123!")

    response = auth_client.post(
        "/login",
        data={
            "username": "jane_analyst",
            "password": "ValidPassword123!",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")


def test_login_with_email(auth_app, auth_client):
    """POST /login allows signing in using email address."""
    with auth_app.app_context():
        _create_user(
            username="analyst_email",
            email="analyst.email@yottaflex.bank",
            password="ValidPassword123!",
        )

    response = auth_client.post(
        "/login",
        data={
            "username": "analyst.email@yottaflex.bank",
            "password": "ValidPassword123!",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")


def test_login_invalid_password(auth_app, auth_client):
    """POST /login with incorrect password fails with 401."""
    with auth_app.app_context():
        _create_user(username="user_wrong_pw", password="CorrectPassword123!")

    response = auth_client.post(
        "/login",
        data={
            "username": "user_wrong_pw",
            "password": "WrongPassword!",
        },
    )
    assert response.status_code == 401
    assert b"Invalid username or password" in response.data


def test_login_inactive_user_rejected(auth_app, auth_client):
    """POST /login with an inactive user account fails with 401."""
    with auth_app.app_context():
        _create_user(
            username="inactive_analyst",
            password="Password123!",
            is_active=False,
        )

    response = auth_client.post(
        "/login",
        data={
            "username": "inactive_analyst",
            "password": "Password123!",
        },
    )
    assert response.status_code == 401
    assert b"Invalid username or password" in response.data


def test_logout_flow(auth_app, auth_client):
    """POST /logout clears the user session and redirects to login."""
    with auth_app.app_context():
        _create_user(username="logout_user", password="Password123!")

    auth_client.post(
        "/login",
        data={"username": "logout_user", "password": "Password123!"},
    )

    response = auth_client.post("/logout", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")

    dashboard_response = auth_client.get("/dashboard", follow_redirects=False)
    assert dashboard_response.status_code == 302
    assert "/login" in dashboard_response.headers["Location"]


def test_logout_rejects_get(auth_client):
    """GET /logout is not allowed; sign-out must be a CSRF-protected POST."""
    response = auth_client.get("/logout", follow_redirects=False)
    assert response.status_code == 405


def test_login_rate_limit_blocks_after_repeated_failures(auth_app, auth_client):
    """Repeated bad passwords lock the client out, including for valid credentials."""
    with auth_app.app_context():
        _create_user(username="rate_limited", password="Password123!")

    for _ in range(auth_app.config["YTF_LOGIN_MAX_ATTEMPTS"]):
        response = auth_client.post(
            "/login",
            data={"username": "rate_limited", "password": "WrongPassword!"},
        )
        assert response.status_code == 401

    blocked = auth_client.post(
        "/login",
        data={"username": "rate_limited", "password": "Password123!"},
    )
    assert blocked.status_code == 429
    assert b"Too many failed sign-in attempts" in blocked.data


def test_auth_audit_events_do_not_store_secrets(auth_app, auth_client):
    """Successful, failed, and logout actions append non-secret audit events."""
    with auth_app.app_context():
        _create_user(username="audit_user", password="Password123!")

    auth_client.post(
        "/login",
        data={"username": "audit_user", "password": "WrongPassword!"},
    )
    auth_client.post(
        "/login",
        data={"username": "audit_user", "password": "Password123!"},
    )
    auth_client.post("/logout")

    with auth_app.app_context():
        events = db.session.scalars(db.select(AuditEvent).order_by(AuditEvent.id)).all()
        event_types = [event.event_type for event in events]

        assert "AUTH_LOGIN_FAILED" in event_types
        assert "AUTH_LOGIN_SUCCESS" in event_types
        assert "AUTH_LOGOUT" in event_types

        for event in events:
            serialized = f"{event.summary} {event.details or {}}".lower()
            assert "password123" not in serialized
            assert "wrongpassword" not in serialized


def test_safe_redirect_prevents_open_redirect(auth_app, auth_client):
    """Open redirect attacks via ?next=https://attacker.com are blocked."""
    with auth_app.app_context():
        _create_user(username="redirect_test", password="Password123!")

    # Test direct helper
    with auth_app.test_request_context("/login?next=https://evil.com"):
        assert is_safe_redirect_url("https://evil.com") is False
        assert is_safe_redirect_url("/dashboard") is True
        assert is_safe_redirect_url("http://localhost/dashboard") is True
        assert is_safe_redirect_url("//evil.com") is False
        assert is_safe_redirect_url("/\\evil.com") is False
        assert is_safe_redirect_url("/%5Cevil.com") is False
        assert is_safe_redirect_url("javascript:alert(1)") is False
        assert is_safe_redirect_url("dashboard") is False
        assert is_safe_redirect_url("") is False
        assert is_safe_redirect_url(None) is False

    # Test login submission with external redirect
    response = auth_client.post(
        "/login?next=https://evil.com",
        data={"username": "redirect_test", "password": "Password123!"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert not response.headers["Location"].startswith("https://evil.com")
    assert response.headers["Location"].endswith("/dashboard")


def test_role_required_decorator(auth_app, auth_client):
    """Test RBAC decorator restricting access based on UserRole."""

    # Register test routes for role checking before any request
    @auth_app.route("/test-analyst-only")
    @role_required(UserRole.ANALYST)
    def analyst_only():
        return jsonify({"access": "granted"})

    @auth_app.route("/test-supervisor-only")
    @role_required(UserRole.SUPERVISOR, UserRole.ADMIN)
    def supervisor_only():
        return jsonify({"access": "granted"})

    @auth_app.route("/api/v1/test-protected")
    @role_required(UserRole.ANALYST)
    def api_protected():
        return jsonify({"access": "granted"})

    # 1. Unauthenticated request to web view redirects to login
    response = auth_client.get("/test-analyst-only")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]

    # 2. Unauthenticated request to API path returns 401 JSON
    api_resp = auth_client.get("/api/v1/test-protected")
    assert api_resp.status_code == 401
    assert api_resp.get_json()["error"] == "unauthorized"

    # 3. Log in as ANALYST
    with auth_app.app_context():
        _create_user(
            username="analyst_actor",
            password="Password123!",
            role=UserRole.ANALYST,
        )
    auth_client.post(
        "/login",
        data={"username": "analyst_actor", "password": "Password123!"},
    )

    # Allowed access
    resp = auth_client.get("/test-analyst-only")
    assert resp.status_code == 200

    # Denied access to supervisor route: redirects with flash
    resp = auth_client.get("/test-supervisor-only", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dashboard")


def test_cli_create_user(auth_app):
    """Test the Flask CLI command auth create-user."""
    runner = CliRunner()

    with auth_app.app_context():
        result = runner.invoke(
            auth_cli,
            [
                "create-user",
                "--username",
                "cli_analyst",
                "--email",
                "cli.analyst@yottaflex.bank",
                "--full-name",
                "CLI Analyst",
                "--role",
                "ANALYST",
                "--password",
                "LongSecurePass2026!",
            ],
        )
        assert result.exit_code == 0
        assert "created successfully" in result.output

        user = db.session.scalar(db.select(User).where(User.username == "cli_analyst"))
        assert user is not None
        assert user.role == UserRole.ANALYST
        assert user.check_password("LongSecurePass2026!") is True


def test_cli_create_user_duplicate_rejected(auth_app):
    """Test that auth create-user rejects duplicate usernames."""
    runner = CliRunner()

    with auth_app.app_context():
        _create_user(
            username="existing_cli_user",
            email="existing@yottaflex.bank",
            password="Password123!",
        )

        result = runner.invoke(
            auth_cli,
            [
                "create-user",
                "--username",
                "existing_cli_user",
                "--email",
                "new_email@yottaflex.bank",
                "--full-name",
                "Duplicate Test",
                "--role",
                "ANALYST",
                "--password",
                "Password1234!",
            ],
        )
        assert result.exit_code != 0
        assert "already exists" in result.output
