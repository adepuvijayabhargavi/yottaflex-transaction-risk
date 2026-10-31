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


def register_cli(app: Flask) -> None:
    """Register application CLI commands."""

    app.cli.add_command(pilot_cli)
