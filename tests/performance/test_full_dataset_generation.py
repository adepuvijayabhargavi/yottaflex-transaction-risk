"""Opt-in full-profile generation and reproducibility test."""

from __future__ import annotations

import os
import time
import tracemalloc

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.evaluation import GroundTruth
from app.models import Alert
from app.services.data_generator import (
    generate_dataset,
    load_profile,
    reset_dataset_run,
    verify_dataset_run,
)

RUN_FULL_DATASET_TEST = os.environ.get("YTF_RUN_FULL_DATASET_TEST") == "1"


@pytest.mark.skipif(
    not RUN_FULL_DATASET_TEST,
    reason="Set YTF_RUN_FULL_DATASET_TEST=1 to run the full-scale SQLite test.",
)
def test_full_profile_generation_is_reproducible(schema_engine):
    profile = load_profile("full")
    run_reference = profile.default_run_reference
    test_started = time.perf_counter()
    tracemalloc.start()

    generation_started = time.perf_counter()
    with Session(schema_engine, expire_on_commit=False) as session:
        first = generate_dataset(
            profile,
            session,
            session,
            run_reference=run_reference,
        )
        session.commit()
    first_generation_seconds = time.perf_counter() - generation_started

    assert first.counts["transactions"] == 100_000
    assert first.counts["ground_truth"] == 100_000
    assert first.counts["ground_truth_positive"] == 1_000
    assert first.pattern_counts == {
        "HIGH_TRANSACTION_VELOCITY": 200,
        "NEW_DEVICE_ACTIVITY": 150,
        "CIRCULAR_FUND_TRANSFER": 150,
        "DORMANT_ACCOUNT_REACTIVATION": 150,
        "HIGH_VALUE_TRANSACTION": 200,
        "REPEATED_TRANSACTIONS": 150,
    }
    assert first.counts["alerts"] == 0

    with Session(schema_engine) as session:
        assert session.scalar(select(func.count()).select_from(Alert)) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(GroundTruth)
                .where(GroundTruth.is_fraud.is_(True))
            )
            == 1_000
        )
        reset_dataset_run(
            session,
            run_reference=run_reference,
            dry_run=False,
        )
        session.commit()

    generation_started = time.perf_counter()
    with Session(schema_engine, expire_on_commit=False) as session:
        second = generate_dataset(
            profile,
            session,
            session,
            run_reference=run_reference,
        )
        session.commit()
    second_generation_seconds = time.perf_counter() - generation_started

    assert second.checksums["tables"] == first.checksums["tables"]
    assert second.checksums["overall"] == first.checksums["overall"]

    verification_started = time.perf_counter()
    with Session(schema_engine) as session:
        verification = verify_dataset_run(
            session,
            session,
            profile,
            run_reference=run_reference,
        )
    assert verification.ok, verification.errors
    verification_seconds = time.perf_counter() - verification_started
    _current_bytes, peak_traced_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(
        "Full-profile SQLite metrics: "
        f"first_generation={first_generation_seconds:.2f}s, "
        f"second_generation={second_generation_seconds:.2f}s, "
        f"verification={verification_seconds:.2f}s, "
        f"total={time.perf_counter() - test_started:.2f}s, "
        f"peak_traced_python_memory={peak_traced_bytes / (1024 * 1024):.2f} MiB"
    )
