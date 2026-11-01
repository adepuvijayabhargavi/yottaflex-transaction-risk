"""Deterministic, local-only CSV, JSON, and SQL dataset exports."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DatasetRun
from app.models.enums import DatasetRunStatus
from app.services.data_generator.generator import GENERATOR_VERSION
from app.services.data_generator.profiles import DatasetProfile
from app.services.data_generator.verification import verify_dataset_run
from app.services.reproducibility.checksums import (
    canonical_json,
    canonical_value,
    collect_run_rows,
)

EXPORT_ROOT = Path(__file__).resolve().parents[3] / "exports"
_RUN_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")
_SUPPORTED_FORMATS = frozenset({"csv", "json", "sql"})
_TABLE_COLUMNS = {
    "customers": (
        "customer_reference",
        "first_name",
        "last_name",
        "email",
        "phone",
        "country_code",
        "risk_segment",
        "onboarding_date",
        "is_active",
    ),
    "accounts": (
        "account_number",
        "customer_reference",
        "account_type",
        "currency",
        "status",
        "balance",
        "overdraft_limit",
        "opened_at",
        "closed_at",
    ),
    "account_status_history": (
        "account_number",
        "previous_status",
        "new_status",
        "reason",
        "changed_at",
    ),
    "merchants": (
        "merchant_reference",
        "name",
        "category",
        "country_code",
        "risk_level",
        "is_active",
    ),
    "devices": (
        "device_fingerprint",
        "customer_reference",
        "device_type",
        "first_seen_at",
        "last_seen_at",
        "is_trusted",
    ),
    "transfer_groups": (
        "transfer_reference",
        "initiated_by_customer_reference",
        "status",
        "expected_total",
        "actual_total",
        "currency",
        "reconciled_at",
    ),
    "transactions": (
        "transaction_reference",
        "transfer_reference",
        "debit_account_number",
        "credit_account_number",
        "merchant_reference",
        "device_fingerprint",
        "transaction_type",
        "status",
        "amount",
        "currency",
        "occurred_at",
        "description",
        "debit_account_status_snapshot",
        "credit_account_status_snapshot",
    ),
    "risk_rules": (
        "code",
        "version",
        "name",
        "description",
        "category",
        "severity",
        "score_weight",
        "configuration",
        "is_active",
        "effective_from",
        "effective_to",
    ),
    "ground_truth": (
        "ground_truth_reference",
        "dataset_run_reference",
        "transaction_reference",
        "is_fraud",
        "primary_pattern",
        "pattern_codes",
        "label_source",
        "generation_metadata",
    ),
}
_CORE_TABLES = tuple(name for name in _TABLE_COLUMNS if name != "ground_truth")
_SQL_SPECS: dict[str, tuple[str, tuple[tuple[str, str], ...]]] = {
    "customers": (
        "yottaflex",
        tuple((column, column) for column in _TABLE_COLUMNS["customers"]),
    ),
    "accounts": (
        "yottaflex",
        (
            ("account_number", "account_number"),
            ("customer_id", "customer_reference"),
            ("account_type", "account_type"),
            ("currency", "currency"),
            ("status", "status"),
            ("balance", "balance"),
            ("overdraft_limit", "overdraft_limit"),
            ("opened_at", "opened_at"),
            ("closed_at", "closed_at"),
        ),
    ),
    "account_status_history": (
        "yottaflex",
        (
            ("account_id", "account_number"),
            ("previous_status", "previous_status"),
            ("new_status", "new_status"),
            ("reason", "reason"),
            ("changed_at", "changed_at"),
        ),
    ),
    "merchants": (
        "yottaflex",
        tuple((column, column) for column in _TABLE_COLUMNS["merchants"]),
    ),
    "devices": (
        "yottaflex",
        (
            ("device_fingerprint", "device_fingerprint"),
            ("customer_id", "customer_reference"),
            ("device_type", "device_type"),
            ("first_seen_at", "first_seen_at"),
            ("last_seen_at", "last_seen_at"),
            ("is_trusted", "is_trusted"),
        ),
    ),
    "transfer_groups": (
        "yottaflex",
        (
            ("transfer_reference", "transfer_reference"),
            ("initiated_by_customer_id", "initiated_by_customer_reference"),
            ("status", "status"),
            ("expected_total", "expected_total"),
            ("actual_total", "actual_total"),
            ("currency", "currency"),
            ("reconciled_at", "reconciled_at"),
        ),
    ),
    "transactions": (
        "yottaflex",
        (
            ("transaction_reference", "transaction_reference"),
            ("transfer_group_id", "transfer_reference"),
            ("debit_account_id", "debit_account_number"),
            ("credit_account_id", "credit_account_number"),
            ("merchant_id", "merchant_reference"),
            ("device_id", "device_fingerprint"),
            ("transaction_type", "transaction_type"),
            ("status", "status"),
            ("amount", "amount"),
            ("currency", "currency"),
            ("occurred_at", "occurred_at"),
            ("description", "description"),
            ("debit_account_status_snapshot", "debit_account_status_snapshot"),
            ("credit_account_status_snapshot", "credit_account_status_snapshot"),
        ),
    ),
    "risk_rules": (
        "yottaflex",
        tuple((column, column) for column in _TABLE_COLUMNS["risk_rules"]),
    ),
    "ground_truth": (
        "yottaflex_eval",
        tuple((column, column) for column in _TABLE_COLUMNS["ground_truth"]),
    ),
}
_SQL_RELATIONSHIPS = {
    ("accounts", "customer_id"): ("customers", "customer_reference"),
    ("account_status_history", "account_id"): (
        "accounts",
        "account_number",
    ),
    ("devices", "customer_id"): ("customers", "customer_reference"),
    ("transfer_groups", "initiated_by_customer_id"): (
        "customers",
        "customer_reference",
    ),
    ("transactions", "transfer_group_id"): (
        "transfer_groups",
        "transfer_reference",
    ),
    ("transactions", "debit_account_id"): ("accounts", "account_number"),
    ("transactions", "credit_account_id"): ("accounts", "account_number"),
    ("transactions", "merchant_id"): ("merchants", "merchant_reference"),
    ("transactions", "device_id"): ("devices", "device_fingerprint"),
}
_SQL_NUMERIC_COLUMNS = {
    "version",
    "score_weight",
    "balance",
    "overdraft_limit",
    "expected_total",
    "actual_total",
    "amount",
}
_SQL_JSON_COLUMNS = {"configuration", "pattern_codes", "generation_metadata"}
_SQL_BOOLEAN_COLUMNS = {"is_active", "is_trusted", "is_fraud"}
_SQL_IDENTIFIER = re.compile(r"^[a-z_]+$")
_SQL_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")


class DatasetExportError(ValueError):
    """Raised when a dataset cannot be exported safely and completely."""


@dataclass(frozen=True, slots=True)
class DatasetExportResult:
    """Paths and checksums for one completed export bundle."""

    run_reference: str
    formats: tuple[str, ...]
    manifest_path: str
    files: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_reference": self.run_reference,
            "formats": list(self.formats),
            "manifest": self.manifest_path,
            "files": list(self.files),
        }


def _normalize_formats(formats: str | tuple[str, ...] | list[str]) -> tuple[str, ...]:
    selected = (formats,) if isinstance(formats, str) else tuple(formats)
    if selected == ("all",):
        return ("csv", "json", "sql")
    if not selected or len(set(selected)) != len(selected):
        raise DatasetExportError("Select one or more distinct export formats.")
    if any(item not in _SUPPORTED_FORMATS for item in selected):
        raise DatasetExportError("Formats must be csv, json, sql, or all.")
    return tuple(item for item in ("csv", "json", "sql") if item in selected)


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            canonical_value(value),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def _csv_bytes(table_name: str, rows: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=_TABLE_COLUMNS[table_name],
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                column: (
                    ""
                    if row.get(column) is None
                    else (
                        canonical_json(row[column])
                        if isinstance(row[column], (dict, list, tuple))
                        else canonical_value(row[column])
                    )
                )
                for column in _TABLE_COLUMNS[table_name]
            }
        )
    return buffer.getvalue().encode("utf-8")


def _sql_text(value: str) -> str:
    encoded = value.encode("utf-8").hex()
    return f"CONVERT(X'{encoded}' USING utf8mb4)"


def _sql_literal(value: Any, column: str) -> str:
    value = canonical_value(value)
    if value is None:
        return "NULL"
    if column in _SQL_BOOLEAN_COLUMNS:
        if not isinstance(value, bool):
            raise DatasetExportError(f"Invalid boolean value for {column}.")
        return "1" if value else "0"
    if column in _SQL_NUMERIC_COLUMNS:
        text = str(value)
        if not _SQL_NUMBER.fullmatch(text):
            raise DatasetExportError(f"Invalid numeric value for {column}.")
        return text
    if column in _SQL_JSON_COLUMNS:
        return _sql_text(canonical_json(value))
    if isinstance(value, str):
        if column.endswith("_at") and "T" in value:
            value = value.replace("T", " ", 1)
        return _sql_text(value)
    raise DatasetExportError(f"Unsupported SQL value for {column}.")


def _sql_value(table: str, row: dict[str, Any], column: str, source: str) -> str:
    relation = _SQL_RELATIONSHIPS.get((table, column))
    if relation is None:
        return _sql_literal(row.get(source), source)
    referenced_table, referenced_column = relation
    reference = row.get(source)
    if reference is None:
        return "NULL"
    if not _SQL_IDENTIFIER.fullmatch(referenced_table) or not _SQL_IDENTIFIER.fullmatch(
        referenced_column
    ):
        raise DatasetExportError("Invalid fixed SQL relationship identifier.")
    return (
        f"(SELECT `id` FROM `yottaflex`.`{referenced_table}` "
        f"WHERE `{referenced_column}` = {_sql_text(str(reference))})"
    )


def _sql_bytes(
    table_names: tuple[str, ...], rows: dict[str, list[dict[str, Any]]]
) -> bytes:
    statements = [
        "-- Generated dataset export. Review and import manually into an isolated schema.",
        "START TRANSACTION;",
    ]
    for table in table_names:
        if table not in _SQL_SPECS:
            raise DatasetExportError("The SQL export contains an unsupported table.")
        schema, columns = _SQL_SPECS[table]
        if not _SQL_IDENTIFIER.fullmatch(schema) or not _SQL_IDENTIFIER.fullmatch(
            table
        ):
            raise DatasetExportError("Invalid fixed SQL table identifier.")
        column_names = [name for name, _ in columns]
        if any(not _SQL_IDENTIFIER.fullmatch(name) for name in column_names):
            raise DatasetExportError("Invalid fixed SQL column identifier.")
        quoted_columns = ", ".join(f"`{name}`" for name in column_names)
        for row in rows[table]:
            values = ", ".join(
                _sql_value(table, row, column, source) for column, source in columns
            )
            statements.append(
                f"INSERT INTO `{schema}`.`{table}` ({quoted_columns}) "
                f"VALUES ({values});"
            )
    statements.append("COMMIT;")
    return ("\n".join(statements) + "\n").encode("utf-8")


def _build_files(
    *,
    run_reference: str,
    formats: tuple[str, ...],
    rows: dict[str, list[dict[str, Any]]],
    metadata: dict[str, Any],
) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    if "csv" in formats:
        for table_name, table_rows in rows.items():
            files[f"csv/{run_reference}/{table_name}.csv"] = _csv_bytes(
                table_name,
                table_rows,
            )
    if "json" in formats:
        core_rows = {name: rows[name] for name in _CORE_TABLES}
        files[f"json/{run_reference}.json"] = _json_bytes(
            {"metadata": metadata, "tables": core_rows}
        )
        files[f"json/{run_reference}.ground_truth.json"] = _json_bytes(
            {
                "run_reference": run_reference,
                "ground_truth": rows["ground_truth"],
            }
        )
    if "sql" in formats:
        core_rows = {name: rows[name] for name in _CORE_TABLES}
        files[f"sql/{run_reference}.sql"] = _sql_bytes(_CORE_TABLES, core_rows)
        files[f"sql/{run_reference}.ground_truth.sql"] = _sql_bytes(
            ("ground_truth",),
            {"ground_truth": rows["ground_truth"]},
        )
    return files


def _write_bundle(root: Path, files: dict[str, bytes]) -> None:
    pending: list[tuple[Path, Path]] = []
    try:
        for relative_path, contents in files.items():
            destination = root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".export-",
                dir=destination.parent,
            )
            temporary = Path(temporary_name)
            pending.append((temporary, destination))
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(contents)
                handle.flush()
                os.fsync(handle.fileno())
        for temporary, destination in pending:
            os.replace(temporary, destination)
    finally:
        for temporary, _ in pending:
            temporary.unlink(missing_ok=True)


def export_dataset_run(
    core_session: Session,
    eval_session: Session,
    profile: DatasetProfile,
    *,
    run_reference: str,
    output_root: Path = EXPORT_ROOT,
    formats: str | tuple[str, ...] | list[str] = "all",
    result_session: Session | None = None,
) -> DatasetExportResult:
    """Verify and export one completed run without modifying its source data."""

    if not _RUN_REFERENCE_PATTERN.fullmatch(run_reference):
        raise DatasetExportError("Invalid dataset run reference.")
    selected_formats = _normalize_formats(formats)
    run = core_session.scalar(
        select(DatasetRun).where(DatasetRun.run_reference == run_reference)
    )
    if run is None:
        raise DatasetExportError(f"Dataset run {run_reference!r} does not exist.")
    if run.status != DatasetRunStatus.COMPLETED:
        raise DatasetExportError(f"Dataset run {run_reference!r} is not complete.")

    verification = verify_dataset_run(
        core_session,
        eval_session,
        profile,
        run_reference=run_reference,
        result_session=result_session,
    )
    if not verification.ok:
        errors = "; ".join(verification.errors)
        raise DatasetExportError(
            f"Dataset run {run_reference!r} failed verification: {errors}"
        )

    collected = collect_run_rows(
        core_session,
        eval_session,
        run_reference=run_reference,
    )
    rows = {name: table_rows for name, (table_rows, _) in collected.items()}
    metadata = {
        "run_reference": run.run_reference,
        "profile": run.profile_name,
        "seed": run.seed,
        "reference_datetime_utc": canonical_value(run.reference_datetime_utc),
        "generator_version": GENERATOR_VERSION,
        "record_counts": canonical_value(run.record_counts),
        "dataset_checksums": canonical_value(run.checksums),
        "formats": list(selected_formats),
    }
    files = _build_files(
        run_reference=run_reference,
        formats=selected_formats,
        rows=rows,
        metadata=metadata,
    )
    file_manifest = [
        {
            "path": relative_path.replace("\\", "/"),
            "sha256": hashlib.sha256(contents).hexdigest(),
            "size_bytes": len(contents),
            "record_count": (
                len(rows[relative_path.removeprefix(f"csv/{run_reference}/")[:-4]])
                if relative_path.startswith(f"csv/{run_reference}/")
                else None
            ),
        }
        for relative_path, contents in sorted(files.items())
    ]
    manifest = {
        "format_version": 1,
        **metadata,
        "files": file_manifest,
    }
    manifest_relative_path = f"manifests/{run_reference}.json"
    files[manifest_relative_path] = _json_bytes(manifest)
    _write_bundle(Path(output_root), files)
    return DatasetExportResult(
        run_reference=run_reference,
        formats=selected_formats,
        manifest_path=manifest_relative_path,
        files=tuple(file_manifest),
    )


__all__ = [
    "EXPORT_ROOT",
    "DatasetExportError",
    "DatasetExportResult",
    "export_dataset_run",
]
