"""Core and evaluation migration environment separation checks."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import configure_mappers

from app.evaluation import EvaluationBase
from app.models import Base

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CORE_MIGRATIONS = PROJECT_ROOT / "migrations"
EVAL_MIGRATIONS = PROJECT_ROOT / "migrations_eval"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_migration_metadata_contains_the_expected_tables(app):
    with app.app_context():
        configure_mappers()

        assert len(Base.metadata.tables) == 19
        assert len(EvaluationBase.metadata.tables) == 1
        assert all(
            table.schema == "yottaflex" for table in Base.metadata.tables.values()
        )
        assert all(
            table.schema == "yottaflex_eval"
            for table in EvaluationBase.metadata.tables.values()
        )
        assert "yottaflex_eval.ground_truth" not in Base.metadata.tables
        assert set(EvaluationBase.metadata.tables) == {
            "yottaflex_eval.ground_truth",
        }


def test_core_migration_environment_uses_only_core_metadata():
    source = _read(CORE_MIGRATIONS / "env.py")

    assert "from app.models import SCHEMA, Base" in source
    assert "target_metadata = Base.metadata" in source
    assert "migration_database_url()" in source
    assert "validate_target_metadata()" in source
    assert "app.evaluation" not in source
    assert "EvaluationBase" not in source
    assert "yottaflex_eval" not in source


def test_evaluation_migration_environment_uses_only_evaluation_metadata():
    source = _read(EVAL_MIGRATIONS / "env.py")

    assert "from app.evaluation import SCHEMA, EvaluationBase, GroundTruth" in source
    assert "target_metadata = EvaluationBase.metadata" in source
    assert "migration_database_url(evaluation=True)" in source
    assert "validate_target_metadata()" in source
    assert "from app.models" not in source
    assert "target_metadata = Base.metadata" not in source


def test_migration_configs_do_not_hardcode_credentials():
    for alembic_ini in (
        CORE_MIGRATIONS / "alembic.ini",
        EVAL_MIGRATIONS / "alembic.ini",
    ):
        source = _read(alembic_ini).lower()

        assert "sqlalchemy.url" not in source
        assert "mysql+pymysql" not in source
        assert "password" not in source
        assert "secret" not in source


def test_migration_directories_have_separate_version_histories():
    core_versions = CORE_MIGRATIONS / "versions"
    eval_versions = EVAL_MIGRATIONS / "versions"

    assert core_versions.is_dir()
    assert eval_versions.is_dir()
    assert core_versions.resolve() != eval_versions.resolve()
    assert (EVAL_MIGRATIONS / "versions" / ".gitkeep").is_file()
