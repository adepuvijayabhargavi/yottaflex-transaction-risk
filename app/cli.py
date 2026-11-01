"""Flask CLI commands for deterministic pilot dataset operations."""

from __future__ import annotations

import json
from typing import Any

import click
from flask import Flask

from app.services.data_generator.runner import (
    generate_pilot_dataset,
    reset_pilot_dataset,
    verify_pilot_dataset,
)


def _echo(payload: dict[str, Any]) -> None:
    click.echo(json.dumps(payload, indent=2, default=str))


@click.group("pilot")
def pilot_cli() -> None:
    """Generate, reset, and verify the deterministic pilot dataset."""


@pilot_cli.command("generate")
@click.option("--profile", "profile_name", default="pilot", show_default=True)
@click.option("--seed", type=int, default=None)
@click.option("--run-reference", default=None)
def generate_command(
    profile_name: str,
    seed: int | None,
    run_reference: str | None,
) -> None:
    """Generate one pilot dataset and its isolated ground truth."""

    try:
        result = generate_pilot_dataset(
            profile_name=profile_name,
            seed=seed,
            run_reference=run_reference,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    _echo(
        {
            "run_reference": result.run.run_reference,
            "profile": result.run.profile_name,
            "seed": result.run.seed,
            "status": result.run.status.value,
            "counts": result.counts,
            "pattern_counts": result.pattern_counts,
            "checksums": result.checksums,
        }
    )


@pilot_cli.command("reset")
@click.option("--profile", "profile_name", default="pilot", show_default=True)
@click.option("--seed", type=int, default=None)
@click.option("--run-reference", default=None)
@click.option("--dry-run", is_flag=True, help="Preview the rows that would be deleted.")
@click.option("--confirm", is_flag=True, help="Delete the generated run data.")
def reset_command(
    profile_name: str,
    seed: int | None,
    run_reference: str | None,
    dry_run: bool,
    confirm: bool,
) -> None:
    """Reset one generated pilot dataset without touching risk rules."""

    if dry_run == confirm:
        raise click.UsageError("Provide exactly one of --dry-run or --confirm.")

    try:
        result = reset_pilot_dataset(
            profile_name=profile_name,
            seed=seed,
            run_reference=run_reference,
            dry_run=dry_run,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    _echo(
        {
            "run_reference": result.run_reference,
            "dry_run": result.dry_run,
            "counts": result.counts,
        }
    )


@pilot_cli.command("verify")
@click.option("--profile", "profile_name", default="pilot", show_default=True)
@click.option("--seed", type=int, default=None)
@click.option("--run-reference", default=None)
def verify_command(
    profile_name: str,
    seed: int | None,
    run_reference: str | None,
) -> None:
    """Verify counts, labels, balances, transfers, isolation, and checksums."""

    result = verify_pilot_dataset(
        profile_name=profile_name,
        seed=seed,
        run_reference=run_reference,
    )
    _echo(
        {
            "run_reference": result.run_reference,
            "ok": result.ok,
            "counts": result.counts,
            "expected_counts": result.expected_counts,
            "pattern_counts": result.pattern_counts,
            "checksums": result.checksums,
            "errors": list(result.errors),
        }
    )
    if not result.ok:
        raise click.exceptions.Exit(1)


@pilot_cli.command("export")
@click.option("--profile", "profile_name", default="pilot", show_default=True)
@click.option("--seed", type=int, default=None)
@click.option("--run-reference", default=None)
@click.option(
    "--format",
    "export_format",
    type=click.Choice(("all", "csv", "json", "sql"), case_sensitive=False),
    default="all",
    show_default=True,
)
def export_command(
    profile_name: str,
    seed: int | None,
    run_reference: str | None,
    export_format: str,
) -> None:
    """Verify and export one completed dataset run locally."""

    from app.services.data_generator.runner import export_pilot_dataset
    from app.services.export import DatasetExportError

    try:
        result = export_pilot_dataset(
            profile_name=profile_name,
            seed=seed,
            run_reference=run_reference,
            formats=export_format.lower(),
        )
    except (DatasetExportError, FileNotFoundError, TypeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    _echo(result.to_dict())


@click.group("risk")
def risk_cli() -> None:
    """Evaluate transactions, score risk, and generate alerts."""


@risk_cli.command("evaluate")
@click.option(
    "--model-version",
    default="v1.0.0",
    show_default=True,
    help="Risk model version string.",
)
@click.option(
    "--threshold",
    type=int,
    default=None,
    help="Alert score threshold override (defaults to YTF_ALERT_THRESHOLD=40).",
)
@click.option(
    "--batch-size",
    type=int,
    default=100,
    show_default=True,
    help="Processing batch size.",
)
def evaluate_command(
    model_version: str,
    threshold: int | None,
    batch_size: int,
) -> None:
    """Evaluate transactions, produce explainable findings, and generate alerts."""
    from flask import current_app

    from app.services.risk_engine import run_risk_evaluation

    default_threshold = current_app.config.get("YTF_ALERT_THRESHOLD", 40)
    summary = run_risk_evaluation(
        model_version=model_version,
        threshold=threshold,
        batch_size=batch_size,
        default_threshold=default_threshold,
    )
    _echo(summary.to_dict())


@risk_cli.command("status")
@click.option("--model-version", default="v1.0.0", show_default=True)
def status_command(model_version: str) -> None:
    """Inspect assessment, finding, and alert counts for a model version."""
    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import Session

    from app.database import DatabaseRole, database_url_for_role
    from app.models import Alert, RiskAssessment, RiskFinding

    url = database_url_for_role(DatabaseRole.APP)
    assert url is not None
    engine = create_engine(url, pool_pre_ping=True)
    with Session(engine) as session:
        assessments_count = (
            session.scalar(
                select(func.count(RiskAssessment.id)).where(
                    RiskAssessment.model_version == model_version
                )
            )
            or 0
        )
        findings_count = (
            session.scalar(
                select(func.count(RiskFinding.id))
                .join(
                    RiskAssessment,
                    RiskFinding.assessment_id == RiskAssessment.id,
                )
                .where(RiskAssessment.model_version == model_version)
            )
            or 0
        )
        alerts_count = (
            session.scalar(
                select(func.count(Alert.id))
                .join(
                    RiskAssessment,
                    Alert.assessment_id == RiskAssessment.id,
                )
                .where(RiskAssessment.model_version == model_version)
            )
            or 0
        )

        levels = dict(
            session.execute(
                select(RiskAssessment.risk_level, func.count(RiskAssessment.id))
                .where(RiskAssessment.model_version == model_version)
                .group_by(RiskAssessment.risk_level)
            ).all()
        )
        priorities = dict(
            session.execute(
                select(Alert.priority, func.count(Alert.id))
                .join(
                    RiskAssessment,
                    Alert.assessment_id == RiskAssessment.id,
                )
                .where(RiskAssessment.model_version == model_version)
                .group_by(Alert.priority)
            ).all()
        )
    engine.dispose()
    _echo(
        {
            "model_version": model_version,
            "assessments": assessments_count,
            "findings": findings_count,
            "alerts": alerts_count,
            "risk_levels": {
                k.value if hasattr(k, "value") else str(k): v for k, v in levels.items()
            },
            "alert_priorities": {
                k.value if hasattr(k, "value") else str(k): v
                for k, v in priorities.items()
            },
        }
    )


@risk_cli.command("evaluate-metrics")
@click.option("--model-version", default="v1.0.0", show_default=True)
def metrics_command(model_version: str) -> None:
    """Compute precision, recall, and F1 score against isolated ground truth."""
    from app.evaluation.metrics import compute_evaluation_metrics

    metrics = compute_evaluation_metrics(model_version=model_version)
    _echo(metrics.to_dict())


def register_cli(app: Flask) -> None:
    """Register application CLI commands."""

    app.cli.add_command(pilot_cli)
    app.cli.add_command(risk_cli)
    app.cli.add_command(auth_cli)


@click.group("auth")
def auth_cli() -> None:
    """Manage user accounts, roles, and credentials."""


@auth_cli.command("create-user")
@click.option(
    "--username",
    prompt="Username",
    help="Unique username for the analyst or supervisor.",
)
@click.option(
    "--email",
    prompt="Email address",
    help="Unique user email address for notifications.",
)
@click.option(
    "--full-name",
    prompt="Full name",
    help="User full display name.",
)
@click.option(
    "--role",
    type=click.Choice(["ANALYST", "SUPERVISOR", "ADMIN"], case_sensitive=False),
    default="ANALYST",
    prompt="Role (ANALYST, SUPERVISOR, ADMIN)",
    show_default=True,
    help="User authorization role.",
)
@click.option(
    "--password",
    prompt="Password",
    hide_input=True,
    confirmation_prompt=True,
    help="User account password.",
)
@click.option(
    "--active/--inactive",
    default=True,
    help="Whether the account is active immediately.",
)
def create_user_command(
    username: str,
    email: str,
    full_name: str,
    role: str,
    password: str,
    active: bool,
) -> None:
    """Create a user account interactively or via command-line options."""
    from sqlalchemy import or_, select

    from app.extensions import db
    from app.models import User
    from app.models.enums import UserRole
    from app.services.validation.parties import validate_user

    username_clean = username.strip()
    email_clean = email.strip().lower()
    full_name_clean = full_name.strip()
    role_enum = UserRole(role.upper())

    if not password or len(password) < 8:
        raise click.ClickException("Password must be at least 8 characters long.")

    existing = db.session.scalar(
        select(User).where(
            or_(
                User.username == username_clean,
                User.email == email_clean,
            )
        )
    )
    if existing is not None:
        if existing.username == username_clean:
            raise click.ClickException(f"Username '{username_clean}' already exists.")
        raise click.ClickException(f"Email '{email_clean}' already exists.")

    user = User(
        username=username_clean,
        email=email_clean,
        full_name=full_name_clean,
        role=role_enum,
        is_active=active,
    )
    user.set_password(password)

    validate_user(db.session, user, record_event=False)

    db.session.add(user)
    db.session.commit()

    click.echo(
        f"User '{user.username}' ({user.role.value}) created successfully with ID {user.id}."
    )


@auth_cli.command("list-users")
def list_users_command() -> None:
    """List existing users and their roles without exposing credentials."""
    from sqlalchemy import select

    from app.extensions import db
    from app.models import User

    users = db.session.scalars(select(User).order_by(User.id)).all()
    if not users:
        click.echo("No users found.")
        return

    payload = [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "full_name": u.full_name,
            "role": u.role.value if hasattr(u.role, "value") else str(u.role),
            "is_active": u.is_active,
            "last_login_at": (u.last_login_at.isoformat() if u.last_login_at else None),
        }
        for u in users
    ]
    _echo({"users": payload, "total": len(payload)})
