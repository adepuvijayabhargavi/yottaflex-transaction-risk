"""Integration tests for verified, reproducible dataset export bundles."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DatasetRun
from app.models.enums import DatasetRunStatus
from app.services.data_generator import generate_dataset, load_profile
from app.services.export import DatasetExportError, export_dataset_run
from app.services.reproducibility import compute_run_checksums


def _generate(schema_engine, profile, run_reference: str):
    with Session(schema_engine, expire_on_commit=False) as session:
        result = generate_dataset(
            profile,
            session,
            session,
            run_reference=run_reference,
        )
        session.commit()
        return result


def test_export_bundle_is_reproducible_verified_and_ground_truth_is_separate(
    schema_engine,
    tmp_path: Path,
    monkeypatch,
):
    profile = load_profile("pilot")
    run_reference = "EXPORT-1"
    generated = _generate(schema_engine, profile, run_reference)

    with Session(schema_engine) as session:
        first = export_dataset_run(
            session,
            session,
            profile,
            run_reference=run_reference,
            output_root=tmp_path,
        )
        first_manifest = (tmp_path / first.manifest_path).read_bytes()
        manifest_payload = json.loads(first_manifest)
        json_core_path = tmp_path / "json" / f"{run_reference}.json"
        json_gt_path = tmp_path / "json" / f"{run_reference}.ground_truth.json"
        core_payload = json.loads(json_core_path.read_text(encoding="utf-8"))
        gt_payload = json.loads(json_gt_path.read_text(encoding="utf-8"))

        assert core_payload["metadata"]["dataset_checksums"]["overall"] == (
            generated.checksums["overall"]
        )
        assert "ground_truth" not in core_payload["tables"]
        assert len(gt_payload["ground_truth"]) == 2000
        assert len(core_payload["tables"]["transactions"]) == 2000

        csv_gt_path = tmp_path / "csv" / run_reference / "ground_truth.csv"
        with csv_gt_path.open(encoding="utf-8", newline="") as handle:
            ground_truth_rows = list(csv.DictReader(handle))
        assert len(ground_truth_rows) == 2000
        assert ground_truth_rows[0]["dataset_run_reference"] == run_reference

        core_sql = (tmp_path / "sql" / f"{run_reference}.sql").read_text(
            encoding="utf-8"
        )
        gt_sql = (tmp_path / "sql" / f"{run_reference}.ground_truth.sql").read_text(
            encoding="utf-8"
        )
        assert "`yottaflex`.`transactions`" in core_sql
        assert "ground_truth" not in core_sql
        assert "`yottaflex_eval`.`ground_truth`" in gt_sql
        assert "YTF_" not in core_sql + gt_sql

        for file in manifest_payload["files"]:
            contents = (tmp_path / file["path"]).read_bytes()
            assert hashlib.sha256(contents).hexdigest() == file["sha256"]
            assert len(contents) == file["size_bytes"]
        assert any(
            file["path"].endswith("ground_truth.csv")
            for file in manifest_payload["files"]
        )

        first_files = {
            file["path"]: (tmp_path / file["path"]).read_bytes() for file in first.files
        }
        first_files[first.manifest_path] = first_manifest

        original_scalars = Session.scalars

        class ReversedScalarResult:
            def __init__(self, result):
                self._result = result

            def all(self):
                return list(reversed(self._result.all()))

        def reversed_scalars(query_session, *args, **kwargs):
            return ReversedScalarResult(
                original_scalars(query_session, *args, **kwargs)
            )

        monkeypatch.setattr(Session, "scalars", reversed_scalars)
        reordered_checksums = compute_run_checksums(
            session,
            session,
            run_reference=run_reference,
        )
        second = export_dataset_run(
            session,
            session,
            profile,
            run_reference=run_reference,
            output_root=tmp_path,
        )

        assert reordered_checksums == {
            "tables": generated.checksums["tables"],
            "overall": generated.checksums["overall"],
        }
        assert second.files == first.files
        second_files = {
            file["path"]: (tmp_path / file["path"]).read_bytes()
            for file in second.files
        }
        second_files[second.manifest_path] = (
            tmp_path / second.manifest_path
        ).read_bytes()
        assert second_files == first_files


@pytest.mark.parametrize(
    ("run_reference", "expected_message"),
    [
        ("../outside", "Invalid dataset run reference"),
        ("MISSING-1", "does not exist"),
    ],
)
def test_export_rejects_invalid_or_missing_run(
    schema_engine,
    tmp_path: Path,
    run_reference: str,
    expected_message: str,
):
    profile = load_profile("pilot")
    with Session(schema_engine) as session, pytest.raises(
        DatasetExportError, match=expected_message
    ):
        export_dataset_run(
            session,
            session,
            profile,
            run_reference=run_reference,
            output_root=tmp_path,
        )
    assert not list(tmp_path.rglob("*"))


def test_export_rejects_incomplete_or_tampered_run(schema_engine, tmp_path: Path):
    profile = load_profile("pilot")
    run_reference = "EXPORT-INVALID"
    _generate(schema_engine, profile, run_reference)

    with Session(schema_engine) as session:
        run = session.scalar(
            select(DatasetRun).where(DatasetRun.run_reference == run_reference)
        )
        assert run is not None
        run.status = DatasetRunStatus.RUNNING
        session.commit()
        with pytest.raises(DatasetExportError, match="not complete"):
            export_dataset_run(
                session,
                session,
                profile,
                run_reference=run_reference,
                output_root=tmp_path,
            )
        run.status = DatasetRunStatus.COMPLETED
        run.checksums = {**run.checksums, "overall": "0" * 64}
        session.commit()
        with pytest.raises(DatasetExportError, match="failed verification"):
            export_dataset_run(
                session,
                session,
                profile,
                run_reference=run_reference,
                output_root=tmp_path,
            )
    assert not list(tmp_path.rglob("*"))
