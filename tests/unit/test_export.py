"""Focused tests for safe dataset export serialization."""

from __future__ import annotations

import pytest

from app.services.export import (
    DatasetExportError,
    _csv_bytes,
    _normalize_formats,
    _sql_bytes,
)


def test_export_formats_are_validated_and_normalized():
    assert _normalize_formats("all") == ("csv", "json", "sql")
    assert _normalize_formats(("sql", "csv")) == ("csv", "sql")

    with pytest.raises(DatasetExportError, match="Formats must be"):
        _normalize_formats("../outside")
    with pytest.raises(DatasetExportError, match="distinct"):
        _normalize_formats(("csv", "csv"))


def test_csv_uses_fixed_columns_and_escapes_delimiters():
    encoded = _csv_bytes(
        "customers",
        [
            {
                "customer_reference": "CUST-1",
                "first_name": 'Taylor,"=cmd',
                "last_name": "Example",
                "email": None,
                "phone": None,
                "country_code": "US",
                "risk_segment": "STANDARD",
                "onboarding_date": "2026-10-30",
                "is_active": True,
            }
        ],
    )
    text = encoded.decode("utf-8")

    assert text.startswith(
        "customer_reference,first_name,last_name,email,phone,country_code,"
    )
    assert '"Taylor,""=cmd"' in text
    assert "DROP TABLE" not in text


def test_sql_uses_allowlisted_identifiers_and_never_interpolates_text():
    hostile_name = "x'); DROP TABLE yottaflex.customers; --"
    encoded = _sql_bytes(
        ("customers",),
        {
            "customers": [
                {
                    "customer_reference": "CUST-1",
                    "first_name": hostile_name,
                    "last_name": "Example",
                    "email": None,
                    "phone": None,
                    "country_code": "US",
                    "risk_segment": "STANDARD",
                    "onboarding_date": "2026-10-30",
                    "is_active": True,
                }
            ]
        },
    )
    sql = encoded.decode("utf-8")

    assert "INSERT INTO `yottaflex`.`customers`" in sql
    assert hostile_name not in sql
    assert "DROP TABLE" not in sql
    assert "CONVERT(X'" in sql

    with pytest.raises(DatasetExportError, match="unsupported table"):
        _sql_bytes(("users",), {"users": []})


def test_sql_rejects_non_numeric_values_in_numeric_columns():
    with pytest.raises(DatasetExportError, match="numeric value"):
        _sql_bytes(
            ("risk_rules",),
            {
                "risk_rules": [
                    {
                        "code": "RULE",
                        "version": "1; DROP TABLE users",
                        "name": "Rule",
                        "description": None,
                        "category": "test",
                        "severity": "LOW",
                        "score_weight": 1,
                        "configuration": {},
                        "is_active": True,
                        "effective_from": "2026-10-30T00:00:00",
                        "effective_to": None,
                    }
                ]
            },
        )
