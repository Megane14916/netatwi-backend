"""Test setup must run before importing app.py, which creates the Flask app."""

import os
import socket
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


# load_dotenv() does not override existing values. Set every external endpoint
# before importing app so a developer's .env cannot select a real database.
os.environ.update(
    {
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SECRET_KEY": "test-only-secret-key",
        "FRONTEND_URL": "http://localhost:3000",
        "FLASK_DEBUG": "True",
        "X_CONSUMER_KEY": "test-client-id",
        "X_CONSUMER_SECRET": "test-client-secret",
        "USE_R2": "False",
        "GCP_PROJECT_ID": "",
        "GCP_LOCATION": "",
        "GCP_QUEUE_NAME": "",
        "TASK_HANDLER_URL": "",
        "GCR_URL": "",
    }
)

import app as app_module  # noqa: E402
from app import app as flask_app, db  # noqa: E402


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """Fail fast if a test accidentally calls an external service."""

    def reject_network(*_args, **_kwargs):
        raise AssertionError("Tests must not open network connections")

    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_network)


@pytest.fixture
def app():
    flask_app.config["TESTING"] = True
    with flask_app.app_context():
        app_module._contests_cache = None
        app_module._contests_cache_time = 0
        db.create_all()
        try:
            yield flask_app
        finally:
            db.session.remove()
            db.drop_all()
            app_module._contests_cache = None
            app_module._contests_cache_time = 0


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def runner(app):
    return app.test_cli_runner()


@pytest.fixture
def fake_x_authorization(monkeypatch):
    class FakeOAuthSession:
        def __init__(self, *_args, **_kwargs):
            pass

        def authorization_url(self, _url, **_kwargs):
            return "https://x.example/authorize", "test-oauth-state"

    monkeypatch.setattr(app_module, "OAuth2Session", FakeOAuthSession)


@pytest.fixture
def fake_r2(monkeypatch):
    client = Mock()
    monkeypatch.setattr(app_module, "USE_R2", True)
    monkeypatch.setattr(app_module, "R2_BUCKET_NAME", "test-bucket")
    monkeypatch.setattr(app_module, "R2_PUBLIC_URL", "https://r2.example")
    monkeypatch.setattr(app_module, "get_r2_client", lambda: client)
    return client


@pytest.fixture
def fake_cloud_tasks(monkeypatch):
    client = Mock()
    client.queue_path.return_value = "projects/test/locations/test/queues/test"
    client.create_task.return_value = SimpleNamespace(name="test-task")
    monkeypatch.setattr(app_module, "_cloud_tasks_client", client)
    monkeypatch.setenv("GCP_PROJECT_ID", "test")
    monkeypatch.setenv("GCP_LOCATION", "test")
    monkeypatch.setenv("GCP_QUEUE_NAME", "test")
    monkeypatch.setenv("TASK_HANDLER_URL", "https://backend.example")
    return client
