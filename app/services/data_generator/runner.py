"""Database-backed orchestration for pilot dataset commands."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.database import evaluation_core_database_url, generator_database_url
from app.services.export import DatasetExportResult, export_dataset_run

from .generator import GenerationResult, generate_dataset
from .profiles import DatasetProfile, load_profile
from .reset import ResetResult, reset_dataset_run
from .verification import VerificationResult, verify_dataset_run


def _engine() -> Engine:
    return create_engine(generator_database_url(), pool_pre_ping=True)


def _resolve_profile(
    profile_name: str,
    seed: int | None,
) -> DatasetProfile:
    return load_profile(profile_name, seed=seed)


def _resolve_run_reference(
    profile: DatasetProfile,
    run_reference: str | None,
) -> str:
    return run_reference or profile.default_run_reference


def generate_pilot_dataset(
    *,
    profile_name: str = "pilot",
    seed: int | None = None,
    run_reference: str | None = None,
) -> GenerationResult:
    """Generate and commit one deterministic pilot dataset."""

    profile = _resolve_profile(profile_name, seed)
    reference = _resolve_run_reference(profile, run_reference)
    engine = _engine()
    try:
        with Session(engine, expire_on_commit=False) as session, session.begin():
            return generate_dataset(
                profile,
                session,
                session,
                run_reference=reference,
            )
    finally:
        engine.dispose()


def reset_pilot_dataset(
    *,
    profile_name: str = "pilot",
    seed: int | None = None,
    run_reference: str | None = None,
    dry_run: bool,
) -> ResetResult:
    """Remove or preview removal of one generated pilot dataset."""

    profile = _resolve_profile(profile_name, seed)
    reference = _resolve_run_reference(profile, run_reference)
    engine = _engine()
    try:
        with Session(engine) as session:
            result = reset_dataset_run(
                session,
                run_reference=reference,
                dry_run=dry_run,
            )
            if not dry_run:
                session.commit()
            return result
    finally:
        engine.dispose()


def verify_pilot_dataset(
    *,
    profile_name: str = "pilot",
    seed: int | None = None,
    run_reference: str | None = None,
) -> VerificationResult:
    """Verify one generated pilot dataset and its ground truth."""

    profile = _resolve_profile(profile_name, seed)
    reference = _resolve_run_reference(profile, run_reference)
    engine = _engine()
    read_engine = create_engine(evaluation_core_database_url(), pool_pre_ping=True)
    try:
        with Session(engine) as session, Session(read_engine) as result_session:
            return verify_dataset_run(
                session,
                session,
                profile,
                run_reference=reference,
                result_session=result_session,
            )
    finally:
        engine.dispose()
        read_engine.dispose()


def export_pilot_dataset(
    *,
    profile_name: str = "pilot",
    seed: int | None = None,
    run_reference: str | None = None,
    formats: str = "all",
) -> DatasetExportResult:
    """Verify and export one completed run using read-only source sessions."""

    profile = _resolve_profile(profile_name, seed)
    reference = _resolve_run_reference(profile, run_reference)
    engine = _engine()
    read_engine = create_engine(evaluation_core_database_url(), pool_pre_ping=True)
    try:
        with Session(engine) as session, Session(read_engine) as result_session:
            return export_dataset_run(
                session,
                session,
                profile,
                run_reference=reference,
                formats=formats,
                result_session=result_session,
            )
    finally:
        engine.dispose()
        read_engine.dispose()
