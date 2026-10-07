"""Shared disposable PostgreSQL setup for concurrency tests."""

import os

import pytest

from app import create_app
from app.extensions import db


@pytest.fixture
def postgres_app():
    uri = os.environ.get("TEST_POSTGRESQL_URI")
    if not uri:
        pytest.skip("Disposable PostgreSQL is provided by the CI service container")
    # Never accept a production database URL from a developer's environment.
    assert uri == "postgresql+psycopg2://netatwi_test:netatwi_test@127.0.0.1:5432/netatwi_test"
    application = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": uri, "SECRET_KEY": "postgres-test", "FRONTEND_URL": "http://localhost:3000", "USE_R2": False, "SQLALCHEMY_ENGINE_OPTIONS": {"connect_args": {"connect_timeout": 5, "options": "-c statement_timeout=15000"}}})
    with application.app_context():
        db.create_all()
        try:
            yield application
        finally:
            db.session.remove()
            db.drop_all()
            db.engine.dispose()
