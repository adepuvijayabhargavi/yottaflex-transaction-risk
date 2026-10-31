"""Alembic environment for the evaluation-only yottaflex_eval schema."""

from __future__ import annotations

import logging
from logging.config import fileConfig

from alembic import context
from flask import current_app
from sqlalchemy import create_engine

from app.database import migration_database_url
from app.evaluation import SCHEMA, EvaluationBase, GroundTruth  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")


def validate_target_metadata() -> None:
    """Refuse to run if any table belongs outside the evaluation schema."""

    unexpected_tables = sorted(
        name
        for name, table in EvaluationBase.metadata.tables.items()
        if table.schema != SCHEMA
    )
    if unexpected_tables:
        joined_names = ", ".join(unexpected_tables)
        raise RuntimeError(
            "Evaluation migrations can only include yottaflex_eval tables. "
            f"Unexpected tables: {joined_names}"
        )


validate_target_metadata()
target_metadata = EvaluationBase.metadata


def get_migration_url() -> str:
    """Use the dedicated evaluation migration user and database."""

    return migration_database_url(evaluation=True)


def get_configure_args() -> dict[str, object]:
    args = dict(current_app.extensions["migrate"].configure_args)
    args.setdefault("version_table_schema", SCHEMA)
    return args


def run_migrations_offline() -> None:
    """Run migrations without creating an engine or database connection."""

    context.configure(
        url=get_migration_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        version_table_schema=SCHEMA,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations using the evaluation migration connection."""

    def process_revision_directives(context, revision, directives):
        if getattr(config.cmd_opts, "autogenerate", False):
            script = directives[0]
            if script.upgrade_ops.is_empty():
                directives[:] = []
                logger.info("No changes in schema detected.")

    configure_args = get_configure_args()
    if configure_args.get("process_revision_directives") is None:
        configure_args["process_revision_directives"] = process_revision_directives

    connectable = create_engine(get_migration_url(), pool_pre_ping=True)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            **configure_args,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
