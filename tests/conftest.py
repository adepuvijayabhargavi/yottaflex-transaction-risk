"""Shared pytest fixtures."""

import json

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import configure_mappers

from app import create_app
from app.evaluation import EvaluationBase
from app.models import Base


@pytest.fixture()
def app():
    """Create a Flask application configured for testing."""

    test_app = create_app("testing")
    yield test_app


@pytest.fixture()
def client(app):
    """Create a Flask test client."""

    return app.test_client()


@pytest.fixture()
def schema_engine():
    """Create an ephemeral SQLite database with both application schemas."""

    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("ATTACH DATABASE ':memory:' AS yottaflex")
        cursor.execute("ATTACH DATABASE ':memory:' AS yottaflex_eval")
        cursor.close()
        dbapi_connection.create_function(
            "CHAR_LENGTH",
            1,
            lambda value: len(value) if value is not None else None,
        )
        dbapi_connection.create_function("JSON_TYPE", 1, _sqlite_json_type)

    configure_mappers()
    Base.metadata.create_all(engine)
    EvaluationBase.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _sqlite_json_type(value):
    """Approximate MySQL JSON_TYPE for SQLite-backed tests."""

    if value is None:
        return None

    parsed = json.loads(value)
    if isinstance(parsed, list):
        return "ARRAY"
    if isinstance(parsed, dict):
        return "OBJECT"
    if isinstance(parsed, bool):
        return "BOOLEAN"
    if isinstance(parsed, str):
        return "TEXT"
    if isinstance(parsed, (int, float)):
        return "NUMBER"
    return "NULL"
