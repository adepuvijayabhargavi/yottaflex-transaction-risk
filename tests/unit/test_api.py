"""Focused tests for API request validation and response allowlists."""

import pytest
from marshmallow import ValidationError

from app.blueprints.api.routes import (
    _safe_alert,
    _safe_evidence,
    _safe_investigation,
)
from app.schemas.api import AlertAssignmentSchema, CaseCreateSchema


def test_api_schemas_reject_unknown_fields_and_invalid_values():
    with pytest.raises(ValidationError):
        AlertAssignmentSchema().load({"assignee_id": 3, "unexpected": True})

    with pytest.raises(ValidationError):
        AlertAssignmentSchema().load({"assignee_id": 0})

    with pytest.raises(ValidationError):
        CaseCreateSchema().load(
            {"title": "Case", "alert_ids": [], "unknown": "not accepted"}
        )


def test_case_create_schema_applies_safe_defaults():
    payload = CaseCreateSchema().load({"title": "Review", "alert_ids": [1]})

    assert payload["priority"] == "MEDIUM"
    assert payload["description"] is None


def test_alert_response_allowlist_omits_customer_contact_and_balances():
    result = _safe_alert(
        {
            "alert": {"id": 1, "reference": "ALT-1", "details": "review"},
            "customer": {
                "id": 2,
                "name": "Sample Customer",
                "email": "private@example.test",
                "phone": "555-0100",
            },
            "transaction": {
                "id": 3,
                "reference": "TX-1",
                "debit_account": {
                    "id": 4,
                    "account_number": "ACC-1",
                    "balance": 500,
                    "customer": {
                        "id": 2,
                        "reference": "CUST-1",
                        "email": "private@example.test",
                    },
                },
            },
        }
    )

    assert result["customer"] == {"id": 2, "name": "Sample Customer"}
    assert result["transaction"]["debit_account"]["customer"] == {
        "id": 2,
        "reference": "CUST-1",
    }
    assert "email" not in str(result)
    assert "phone" not in str(result)
    assert "balance" not in str(result)
    assert "account_number" not in str(result)


def test_investigation_response_allowlists_stored_evidence_and_history():
    result = _safe_investigation(
        {
            "transaction": {"id": 1, "reference": "TX-1"},
            "assessments": [
                {
                    "id": 4,
                    "findings": [
                        {
                            "id": 5,
                            "rule_code": "AMOUNT",
                            "evidence": {
                                "amount": "500",
                                "threshold": "100",
                                "customer_email": "private@example.test",
                            },
                        }
                    ],
                }
            ],
        }
    )

    evidence = result["assessments"][0]["findings"][0]["evidence"]
    assert evidence == {"amount": "500", "threshold": "100"}
    assert "customer_email" not in str(result)
    assert _safe_evidence(["not", "an", "object"]) == {}
    assert _safe_evidence({"cycle_accounts": [1, {"email": "private"}, 2]}) == {
        "cycle_accounts": [1, 2]
    }
