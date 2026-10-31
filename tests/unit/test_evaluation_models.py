"""Evaluation metadata isolation and ground-truth definition checks."""

from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateTable

from app.evaluation import EvaluationBase, GroundTruth
from app.extensions import db
from app.models import Base


def test_evaluation_metadata_is_separate_from_core_metadata():
    configure_mappers()

    assert EvaluationBase.metadata is db.metadatas["eval"]
    assert GroundTruth.__table__.metadata is EvaluationBase.metadata
    assert set(EvaluationBase.metadata.tables) == {
        "yottaflex_eval.ground_truth",
    }
    assert "yottaflex_eval.ground_truth" not in Base.metadata.tables
    assert len(Base.metadata.tables) == 19
    assert all(table.schema == "yottaflex" for table in Base.metadata.tables.values())


def test_ground_truth_has_no_core_foreign_keys():
    configure_mappers()

    assert not GroundTruth.__table__.foreign_keys
    for table in Base.metadata.tables.values():
        for foreign_key in table.foreign_keys:
            target = foreign_key.target_fullname.lower()
            assert "ground_truth" not in target
            assert "yottaflex_eval" not in target


def test_ground_truth_constraints_and_indexes():
    configure_mappers()

    check_names = {
        constraint.name
        for constraint in GroundTruth.__table__.constraints
        if constraint.name
    }
    unique_names = {
        constraint.name
        for constraint in GroundTruth.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    index_names = {index.name for index in GroundTruth.__table__.indexes}

    assert {
        "ck_ground_truth_primary_pattern_matches_label",
        "ck_ground_truth_pattern_codes_is_array",
        "ck_ground_truth_dataset_run_reference_not_blank",
        "ck_ground_truth_transaction_reference_not_blank",
    }.issubset(check_names)
    assert {
        "uq_ground_truth_reference",
        "uq_ground_truth_run_transaction",
    }.issubset(unique_names)
    assert {
        "ix_ground_truth_dataset_run_reference",
        "ix_ground_truth_transaction_reference",
        "ix_ground_truth_is_fraud",
        "ix_ground_truth_primary_pattern",
        "ix_ground_truth_created_at",
    } == index_names


def test_ground_truth_compiles_for_mysql():
    configure_mappers()

    dialect = mysql.dialect()
    assert str(CreateTable(GroundTruth.__table__).compile(dialect=dialect))
