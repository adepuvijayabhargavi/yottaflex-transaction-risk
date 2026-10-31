"""Cross-model integrity, relationship, and index audit checks."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Numeric, UniqueConstraint, inspect
from sqlalchemy.orm import configure_mappers

import app.models as core_models
from app.evaluation import EvaluationBase, GroundTruth
from app.models import (
    Account,
    AccountStatusHistory,
    Alert,
    AuditEvent,
    Case,
    CaseAlert,
    CaseDecision,
    CaseNote,
    Customer,
    DatasetRun,
    Device,
    Merchant,
    RiskAssessment,
    RiskFinding,
    RiskRule,
    Transaction,
    TransferGroup,
    User,
    ValidationEvent,
)
from app.models.base import AppendOnlyMixin, Base
from app.models.enums import (
    AlertStatus,
    CaseStatus,
    TransactionStatus,
    TransactionType,
)


def test_all_twenty_models_have_primary_keys(app):
    with app.app_context():
        configure_mappers()

        assert len(Base.metadata.tables) == 19
        assert len(EvaluationBase.metadata.tables) == 1
        assert len(Base.metadata.tables) + len(EvaluationBase.metadata.tables) == 20

        for table in (
            *Base.metadata.tables.values(),
            *EvaluationBase.metadata.tables.values(),
        ):
            assert table.primary_key.columns


def test_every_foreign_key_resolves_within_its_schema(app):
    with app.app_context():
        configure_mappers()

        for metadata in (Base.metadata, EvaluationBase.metadata):
            for table in metadata.tables.values():
                for foreign_key in table.foreign_keys:
                    referenced_column = foreign_key.column
                    assert referenced_column.name
                    assert referenced_column.table.metadata is metadata
                    assert referenced_column.table.schema == table.schema


def test_all_reciprocal_relationships_are_configured(app):
    with app.app_context():
        configure_mappers()

        for mapper in Base.registry.mappers:
            if not mapper.class_.__module__.startswith("app.models"):
                continue

            for relationship in mapper.relationships:
                if relationship.back_populates is None:
                    continue

                reverse = inspect(relationship.mapper.class_).relationships[
                    relationship.back_populates
                ]
                assert reverse.mapper.class_ is mapper.class_
                assert reverse.back_populates == relationship.key


def test_critical_relationship_pairs(app):
    expected = [
        (Customer, "accounts", Account, True),
        (Account, "customer", Customer, False),
        (Customer, "devices", Device, True),
        (Device, "customer", Customer, False),
        (Customer, "transfer_groups", TransferGroup, True),
        (TransferGroup, "initiated_by_customer", Customer, False),
        (Account, "debit_transactions", Transaction, True),
        (Account, "credit_transactions", Transaction, True),
        (Transaction, "debit_account", Account, False),
        (Transaction, "credit_account", Account, False),
        (TransferGroup, "transactions", Transaction, True),
        (Transaction, "transfer_group", TransferGroup, False),
        (Device, "transactions", Transaction, True),
        (Transaction, "device", Device, False),
        (Merchant, "transactions", Transaction, True),
        (Transaction, "merchant", Merchant, False),
        (RiskAssessment, "findings", RiskFinding, True),
        (RiskAssessment, "alerts", Alert, True),
        (RiskFinding, "assessment", RiskAssessment, False),
        (RiskFinding, "alert", Alert, False),
        (Alert, "transaction", Transaction, False),
        (Alert, "assessment", RiskAssessment, False),
        (Alert, "finding", RiskFinding, False),
        (Alert, "triggering_rule", RiskRule, False),
        (Case, "case_alerts", CaseAlert, True),
        (CaseAlert, "case", Case, False),
        (CaseAlert, "alert", Alert, False),
        (Case, "notes", CaseNote, True),
        (Case, "decisions", CaseDecision, True),
        (CaseDecision, "triggering_alert", Alert, False),
        (User, "audit_events", AuditEvent, True),
        (AuditEvent, "actor", User, False),
    ]
    relationships = {
        (model, key): inspect(model).relationships[key] for model, key, _, _ in expected
    }

    with app.app_context():
        configure_mappers()

        for model, key, target, uselist in expected:
            relationship = relationships[(model, key)]
            assert relationship.mapper.class_ is target
            assert relationship.uselist is uselist


def test_user_action_relationships_point_to_user(app):
    user_actions = [
        (AccountStatusHistory, "changed_by"),
        (Alert, "assigned_to"),
        (Case, "assigned_to"),
        (Case, "opened_by"),
        (Case, "closed_by"),
        (CaseAlert, "linked_by"),
        (CaseAlert, "unlinked_by"),
        (CaseDecision, "decided_by"),
        (CaseNote, "author"),
        (ValidationEvent, "resolved_by"),
        (AuditEvent, "actor"),
    ]

    with app.app_context():
        configure_mappers()

        for model, relationship_name in user_actions:
            assert inspect(model).relationships[relationship_name].mapper.class_ is User


def test_alert_reference_foreign_keys_exist(app):
    with app.app_context():
        configure_mappers()

        foreign_keys = {
            foreign_key.parent.name: foreign_key.target_fullname
            for foreign_key in Alert.__table__.foreign_keys
        }

        assert foreign_keys == {
            "transaction_id": "yottaflex.transactions.id",
            "assessment_id": "yottaflex.risk_assessments.id",
            "finding_id": "yottaflex.risk_findings.id",
            "triggering_rule_id": "yottaflex.risk_rules.id",
            "assigned_to_user_id": "yottaflex.users.id",
        }


def test_expected_integrity_constraints_are_present(app):
    expected = {
        Account: {
            "ck_accounts_overdraft_limit_non_negative",
            "ck_accounts_balance_within_overdraft",
            "ck_accounts_closed_at_matches_status",
            "ck_accounts_closed_after_opened",
        },
        AccountStatusHistory: {"ck_account_status_history_status_actually_changed"},
        DatasetRun: {"ck_dataset_runs_completed_after_started"},
        Device: {"ck_devices_last_seen_after_first_seen"},
        Transaction: {
            "ck_transactions_amount_positive",
            "ck_transactions_accounts_match_transaction_type",
            "ck_transactions_debit_status_snapshot_required",
            "ck_transactions_credit_status_snapshot_required",
        },
        TransferGroup: {
            "ck_transfer_groups_expected_total_non_negative",
            "ck_transfer_groups_actual_total_non_negative",
            "ck_transfer_groups_reconciled_status_has_timestamp",
            "ck_transfer_groups_reconciled_totals_match",
        },
        RiskRule: {
            "uq_risk_rules_code_version",
            "uq_risk_rules_active_code",
            "ck_risk_rules_version_positive",
            "ck_risk_rules_score_weight_range",
            "ck_risk_rules_effective_window_valid",
        },
        RiskAssessment: {
            "uq_risk_assessments_transaction_model_version",
            "ck_risk_assessments_score_range",
        },
        RiskFinding: {
            "uq_risk_findings_assessment_rule",
            "ck_risk_findings_score_range",
        },
        Alert: {
            "uq_alerts_finding_id",
            "ck_alerts_score_range",
            "ck_alerts_acknowledged_after_created",
            "ck_alerts_closed_after_created",
            "ck_alerts_closed_after_acknowledged",
        },
        Case: {
            "ck_cases_closed_after_opened",
            "ck_cases_closed_at_matches_status",
        },
        CaseAlert: {
            "uq_case_alerts_active_alert_id",
            "ck_case_alerts_unlinked_after_linked",
            "ck_case_alerts_unlink_requires_actor_and_reason",
        },
        ValidationEvent: {"ck_validation_events_resolved_after_created"},
        GroundTruth: {
            "uq_ground_truth_reference",
            "uq_ground_truth_run_transaction",
            "ck_ground_truth_primary_pattern_matches_label",
            "ck_ground_truth_pattern_codes_is_array",
        },
    }

    with app.app_context():
        configure_mappers()

        for model, expected_names in expected.items():
            actual_names = {
                constraint.name
                for constraint in model.__table__.constraints
                if constraint.name
            }
            assert expected_names.issubset(actual_names), model.__name__


def test_case_link_history_and_decision_timestamps(app):
    with app.app_context():
        configure_mappers()

        assert CaseAlert.__table__.c.linked_by_user_id.nullable is False
        assert CaseAlert.__table__.c.unlinked_by_user_id.nullable is True
        assert CaseAlert.__table__.c.unlinked_at.nullable is True
        assert CaseAlert.__table__.c.unlink_reason.nullable is True
        assert CaseAlert.__table__.c.active_alert_id.computed is not None
        assert all(
            foreign_key.ondelete == "RESTRICT"
            for foreign_key in CaseAlert.__table__.foreign_keys
        )

        assert CaseDecision.__table__.c.decision.nullable is False
        assert CaseDecision.__table__.c.rationale.nullable is False
        assert CaseDecision.__table__.c.decided_at.nullable is False
        assert CaseDecision.__table__.c.decided_at.default is not None
        assert CaseDecision.__table__.c.triggering_alert_id.nullable is False


def test_history_tables_are_append_only(app):
    append_only_models = (
        AccountStatusHistory,
        CaseDecision,
        CaseNote,
        AuditEvent,
    )

    with app.app_context():
        configure_mappers()

        for model in append_only_models:
            assert issubclass(model, AppendOnlyMixin)
            assert "updated_at" not in model.__table__.c
            assert all(column.onupdate is None for column in model.__table__.columns)


def test_critical_check_expressions_match_the_integrity_rules(app):
    with app.app_context():
        configure_mappers()

        def check_sql(model, name):
            return str(
                next(
                    constraint.sqltext
                    for constraint in model.__table__.constraints
                    if constraint.name == name
                )
            )

        assert "amount > 0" in check_sql(
            Transaction,
            "ck_transactions_amount_positive",
        )
        assert "debit_account_id <> credit_account_id" in check_sql(
            Transaction,
            "ck_transactions_accounts_match_transaction_type",
        )
        assert "balance >= -overdraft_limit" in check_sql(
            Account,
            "ck_accounts_balance_within_overdraft",
        )
        assert "actual_total = expected_total" in check_sql(
            TransferGroup,
            "ck_transfer_groups_reconciled_totals_match",
        )
        unlink_sql = check_sql(
            CaseAlert,
            "ck_case_alerts_unlink_requires_actor_and_reason",
        )
        assert "unlinked_by_user_id IS NOT NULL" in unlink_sql
        assert "unlink_reason IS NOT NULL" in unlink_sql
        assert "length(trim(unlink_reason)) > 0" in unlink_sql
        assert "last_seen_at >= first_seen_at" in check_sql(
            Device,
            "ck_devices_last_seen_after_first_seen",
        )
        assert "completed_at IS NULL OR completed_at >= started_at" in check_sql(
            DatasetRun,
            "ck_dataset_runs_completed_after_started",
        )


def test_constraint_names_are_unique_and_foreign_keys_restrict_deletes(app):
    with app.app_context():
        configure_mappers()

        for metadata in (Base.metadata, EvaluationBase.metadata):
            constraint_names: set[str] = set()
            for table in metadata.tables.values():
                for constraint in table.constraints:
                    if constraint.name:
                        assert constraint.name not in constraint_names
                        constraint_names.add(constraint.name)

                for foreign_key in table.foreign_keys:
                    if table.schema == "yottaflex":
                        assert foreign_key.ondelete == "RESTRICT"


def test_final_policy_constraints(app):
    with app.app_context():
        configure_mappers()

        active_rule_unique = next(
            constraint
            for constraint in RiskRule.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
            and constraint.name == "uq_risk_rules_active_code"
        )
        assessment_unique = next(
            constraint
            for constraint in RiskAssessment.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
            and constraint.name == "uq_risk_assessments_transaction_model_version"
        )
        finding_unique = next(
            constraint
            for constraint in RiskFinding.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
            and constraint.name == "uq_risk_findings_assessment_rule"
        )
        alert_finding_unique = next(
            constraint
            for constraint in Alert.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
            and constraint.name == "uq_alerts_finding_id"
        )

        assert {column.name for column in active_rule_unique.columns} == {"active_code"}
        assert RiskRule.__table__.c.active_code.computed is not None
        assert {column.name for column in assessment_unique.columns} == {
            "transaction_id",
            "model_version",
        }
        assert {column.name for column in finding_unique.columns} == {
            "assessment_id",
            "rule_id",
        }
        assert {column.name for column in alert_finding_unique.columns} == {
            "finding_id"
        }
        assert Alert.__table__.c.finding_id.unique is True

        assert AuditEvent.__table__.c.event_type.nullable is False
        assert AuditEvent.__table__.c.entity_type.nullable is False
        assert AuditEvent.__table__.c.summary.nullable is False
        assert AuditEvent.__table__.c.occurred_at.nullable is False
        assert AuditEvent.__table__.c.actor_user_id.nullable is True
        assert AuditEvent.__table__.c.details.nullable is True


def test_composite_indexes_match_supported_query_patterns(app):
    expected = {
        AccountStatusHistory: {
            "ix_account_status_history_account_changed_at": (
                "account_id",
                "changed_at",
            ),
        },
        Alert: {
            "ix_alerts_status_created_at": ("status", "created_at"),
            "ix_alerts_assigned_status_created_at": (
                "assigned_to_user_id",
                "status",
                "created_at",
            ),
        },
        AuditEvent: {
            "ix_audit_events_entity_occurred_at": (
                "entity_type",
                "entity_id",
                "occurred_at",
            ),
        },
        Case: {
            "ix_cases_status_opened_at": ("status", "opened_at"),
            "ix_cases_assigned_status_opened_at": (
                "assigned_to_user_id",
                "status",
                "opened_at",
            ),
        },
        CaseAlert: {
            "ix_case_alerts_case_id_unlinked_at": ("case_id", "unlinked_at"),
        },
        CaseDecision: {
            "ix_case_decisions_case_id_decided_at": ("case_id", "decided_at"),
        },
        CaseNote: {
            "ix_case_notes_case_id_noted_at": ("case_id", "noted_at"),
        },
        DatasetRun: {
            "ix_dataset_runs_status_started_at": ("status", "started_at"),
        },
        RiskAssessment: {
            "ix_risk_assessments_transaction_assessed_at": (
                "transaction_id",
                "assessed_at",
            ),
        },
        Transaction: {
            "ix_transactions_debit_account_occurred_at": (
                "debit_account_id",
                "occurred_at",
            ),
            "ix_transactions_credit_account_occurred_at": (
                "credit_account_id",
                "occurred_at",
            ),
        },
        ValidationEvent: {
            "ix_validation_events_entity_created_at": (
                "entity_type",
                "entity_id",
                "created_at",
            ),
            "ix_validation_events_resolution_created_at": (
                "resolution_status",
                "created_at",
            ),
        },
    }
    redundant = {
        Alert: {"ix_alerts_status", "ix_alerts_assigned_to_user_id"},
        Case: {"ix_cases_status", "ix_cases_assigned_to_user_id"},
        CaseAlert: {"ix_case_alerts_case_id"},
        CaseDecision: {"ix_case_decisions_case_id"},
        CaseNote: {"ix_case_notes_case_id"},
        DatasetRun: {"ix_dataset_runs_status"},
        RiskAssessment: {"ix_risk_assessments_transaction_id"},
        Transaction: {
            "ix_transactions_debit_account_id",
            "ix_transactions_credit_account_id",
        },
        ValidationEvent: {
            "ix_validation_events_entity",
            "ix_validation_events_resolution_status",
        },
        AccountStatusHistory: {"ix_account_status_history_account_id"},
        AuditEvent: {"ix_audit_events_entity"},
    }

    with app.app_context():
        configure_mappers()

        for model, indexes in expected.items():
            actual = {
                index.name: tuple(column.name for column in index.columns)
                for index in model.__table__.indexes
            }
            for index_name, columns in indexes.items():
                assert actual[index_name] == columns

        for model, index_names in redundant.items():
            actual_names = {index.name for index in model.__table__.indexes}
            assert index_names.isdisjoint(actual_names)


def test_money_columns_use_decimal_18_2(app):
    money_columns = {
        Account: {"balance", "overdraft_limit"},
        Transaction: {"amount"},
        TransferGroup: {"expected_total", "actual_total"},
    }

    with app.app_context():
        configure_mappers()

        for model, column_names in money_columns.items():
            for column_name in column_names:
                column_type = model.__table__.c[column_name].type
                assert isinstance(column_type, Numeric)
                assert column_type.precision == 18
                assert column_type.scale == 2
                assert column_type.asdecimal is True


def test_supported_transaction_alert_and_case_values(app):
    assert {item.value for item in TransactionType} == {
        "OUTGOING",
        "INCOMING",
        "INTERNAL",
    }
    assert {item.value for item in TransactionStatus} == {
        "PENDING",
        "POSTED",
        "FAILED",
        "REVERSED",
    }
    assert {item.value for item in AlertStatus} == {
        "OPEN",
        "ACKNOWLEDGED",
        "CLOSED",
        "DISMISSED",
    }
    assert {item.value for item in CaseStatus} == {
        "OPEN",
        "IN_REVIEW",
        "ESCALATED",
        "CLOSED",
    }

    with app.app_context():
        configure_mappers()

        for model, column_name in (
            (Transaction, "transaction_type"),
            (Transaction, "status"),
            (Alert, "status"),
            (Case, "status"),
        ):
            column_type = model.__table__.c[column_name].type
            assert isinstance(column_type, SAEnum)
            assert column_type.validate_strings is True


def test_every_enum_column_has_validated_allowed_values(app):
    with app.app_context():
        configure_mappers()

        enum_columns = 0
        for metadata in (Base.metadata, EvaluationBase.metadata):
            for table in metadata.tables.values():
                for column in table.columns:
                    if not isinstance(column.type, SAEnum):
                        continue

                    enum_columns += 1
                    assert column.type.validate_strings is True
                    assert column.type.enums

        assert enum_columns > 0


def test_every_foreign_key_column_is_indexed(app):
    with app.app_context():
        configure_mappers()

        for table in Base.metadata.tables.values():
            indexed_leading_columns = {
                next(iter(index.columns)).name
                for index in table.indexes
                if index.columns
            }
            indexed_leading_columns.update(
                next(iter(constraint.columns)).name
                for constraint in table.constraints
                if isinstance(constraint, UniqueConstraint) and constraint.columns
            )
            indexed_leading_columns.update(
                column.name for column in table.primary_key.columns
            )

            for foreign_key in table.foreign_keys:
                assert (
                    foreign_key.parent.name in indexed_leading_columns
                ), f"{table.fullname}.{foreign_key.parent.name} is not indexed"


def test_no_duplicate_index_or_unique_constraint_columns(app):
    with app.app_context():
        configure_mappers()

        for table in Base.metadata.tables.values():
            seen_columns: set[tuple[str, ...]] = set()

            definitions = list(table.indexes)
            definitions.extend(
                constraint
                for constraint in table.constraints
                if isinstance(constraint, UniqueConstraint)
            )

            for definition in definitions:
                columns = tuple(column.name for column in definition.columns)
                assert (
                    columns not in seen_columns
                ), f"Duplicate index/unique definition on {table.fullname}: {columns}"
                seen_columns.add(columns)


def test_core_models_have_no_evaluation_references(app):
    with app.app_context():
        configure_mappers()

        assert not EvaluationBase.metadata.tables[
            "yottaflex_eval.ground_truth"
        ].foreign_keys
        for table in Base.metadata.tables.values():
            for foreign_key in table.foreign_keys:
                assert "yottaflex_eval" not in foreign_key.target_fullname
                assert "ground_truth" not in foreign_key.target_fullname.lower()

        core_model_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in Path(core_models.__file__).parent.rglob("*.py")
        )
        for forbidden in ("app.evaluation", "yottaflex_eval", "ground_truth"):
            assert forbidden not in core_model_source


def test_risk_engine_source_has_no_evaluation_references():
    risk_engine = Path(core_models.__file__).parent.parent / "services" / "risk_engine"
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in risk_engine.rglob("*.py")
    )

    for forbidden in ("app.evaluation", "yottaflex_eval", "ground_truth"):
        assert forbidden not in source
