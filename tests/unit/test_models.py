"""Core model metadata and integrity-definition checks."""

from pathlib import Path

from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateTable

from app.evaluation import EvaluationBase
from app.extensions import db
from app.models import Alert, CaseAlert, RiskRule, Transaction

PROJECT_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_TABLES = {
    "yottaflex.account_status_history",
    "yottaflex.accounts",
    "yottaflex.alerts",
    "yottaflex.audit_events",
    "yottaflex.case_alerts",
    "yottaflex.case_decisions",
    "yottaflex.case_notes",
    "yottaflex.cases",
    "yottaflex.customers",
    "yottaflex.dataset_runs",
    "yottaflex.devices",
    "yottaflex.merchants",
    "yottaflex.risk_assessments",
    "yottaflex.risk_findings",
    "yottaflex.risk_rules",
    "yottaflex.transactions",
    "yottaflex.transfer_groups",
    "yottaflex.users",
    "yottaflex.validation_events",
}


def test_core_metadata_contains_all_tables(app):
    with app.app_context():
        configure_mappers()

        assert set(db.metadata.tables) == EXPECTED_TABLES
        assert all("id" in table.c for table in db.metadata.tables.values())


def test_key_constraints_and_computed_link_state(app):
    with app.app_context():
        configure_mappers()

        risk_rule_constraints = {
            constraint.name
            for constraint in RiskRule.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        case_alert_constraints = {
            constraint.name
            for constraint in CaseAlert.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
        }

        assert "uq_risk_rules_code_version" in risk_rule_constraints
        assert "uq_risk_rules_active_code" in risk_rule_constraints
        assert RiskRule.__table__.c.active_code.computed is not None
        assert "uq_case_alerts_active_alert_id" in case_alert_constraints
        assert CaseAlert.__table__.c.active_alert_id.computed is not None
        assert Alert.__table__.c.finding_id.unique is True
        assert {
            "ck_transactions_amount_positive",
            "ck_transactions_accounts_match_transaction_type",
        }.issubset(
            {
                constraint.name
                for constraint in Transaction.__table__.constraints
                if constraint.name
            }
        )


def test_core_tables_compile_for_mysql(app):
    with app.app_context():
        configure_mappers()

        dialect = mysql.dialect()
        for table in db.metadata.sorted_tables:
            assert str(CreateTable(table).compile(dialect=dialect))


def test_data_dictionary_lists_every_model_table():
    dictionary = (PROJECT_ROOT / "docs" / "data-dictionary.md").read_text(
        encoding="utf-8"
    )

    for metadata in (db.metadata, EvaluationBase.metadata):
        for table in metadata.tables.values():
            assert table.name in dictionary
            assert table.fullname in dictionary
