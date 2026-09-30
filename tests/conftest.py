"""Test setup must run before importing app.py, which creates the Flask app."""

import os
import socket
from datetime import datetime
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
        "ADMIN_SCREEN_NAMES": "test_admin",
        "USE_R2": "False",
        "GCP_PROJECT_ID": "",
        "GCP_LOCATION": "",
        "GCP_QUEUE_NAME": "",
        "TASK_HANDLER_URL": "",
        "GCR_URL": "",
    }
)

import app as app_module  # noqa: E402
from blueprints import admin as admin_routes  # noqa: E402
from blueprints import comments as comment_routes  # noqa: E402
from blueprints import contests as contest_routes  # noqa: E402
from blueprints import interactions as interaction_routes  # noqa: E402
from blueprints import posts as post_routes  # noqa: E402
from blueprints import profile as profile_routes  # noqa: E402
from blueprints import results as result_routes  # noqa: E402
from blueprints import tasks as task_routes  # noqa: E402
from blueprints import voting as voting_routes  # noqa: E402
from cli import process_contests as contest_cli  # noqa: E402
from integrations import x_oauth  # noqa: E402
from app import db  # noqa: E402
from models import Contest, User  # noqa: E402


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """Fail fast if a test accidentally calls an external service."""

    def reject_network(*_args, **_kwargs):
        raise AssertionError("Tests must not open network connections")

    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_network)


@pytest.fixture
def app():
    flask_app = app_module.create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SECRET_KEY": "test-only-secret-key",
            "FRONTEND_URL": "http://localhost:3000",
        }
    )
    with flask_app.app_context():
        contest_routes._contests_cache = None
        contest_routes._contests_cache_time = 0
        db.create_all()
        try:
            yield flask_app
        finally:
            db.session.remove()
            db.drop_all()
            contest_routes._contests_cache = None
            contest_routes._contests_cache_time = 0


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def runner(app):
    return app.test_cli_runner()


@pytest.fixture
def user_factory(app):
    def create(screen_name):
        user = User(
            twitter_id=f"twitter-{screen_name}",
            screen_name=screen_name,
            name=screen_name,
        )
        db.session.add(user)
        db.session.commit()
        return user

    return create


@pytest.fixture
def contest_factory(app):
    def create(start_time, end_time, voting_end_time, **fields):
        contest = Contest(
            name=fields.pop("name", "Test contest"),
            start_time=start_time,
            end_time=end_time,
            voting_end_time=voting_end_time,
            **fields,
        )
        db.session.add(contest)
        db.session.commit()
        return contest

    return create


@pytest.fixture
def login(client):
    def sign_in(user, judge_contests=()):
        with client.session_transaction() as session:
            session["user_id"] = user.id
            session["screen_name"] = user.screen_name
            session["name"] = user.name
            session["profile_image_url"] = user.profile_image_url
            session["judge_for_contest_ids"] = list(judge_contests)

    return sign_in


@pytest.fixture
def fixed_time(monkeypatch):
    def freeze(moment):
        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return moment.astimezone(tz) if tz else moment.replace(tzinfo=None)

        monkeypatch.setattr(app_module, "datetime", FixedDateTime)
        monkeypatch.setattr(admin_routes, "datetime", FixedDateTime)
        monkeypatch.setattr(contest_routes, "datetime", FixedDateTime)
        monkeypatch.setattr(post_routes, "datetime", FixedDateTime)
        monkeypatch.setattr(profile_routes, "datetime", FixedDateTime)
        monkeypatch.setattr(voting_routes, "datetime", FixedDateTime)
        monkeypatch.setattr(result_routes, "datetime", FixedDateTime)
        monkeypatch.setattr(interaction_routes, "datetime", FixedDateTime)
        monkeypatch.setattr(comment_routes, "datetime", FixedDateTime)
        monkeypatch.setattr(task_routes, "datetime", FixedDateTime)
        monkeypatch.setattr(contest_cli, "datetime", FixedDateTime)

    return freeze


@pytest.fixture
def fake_x_authorization(monkeypatch):
    class FakeOAuthSession:
        def __init__(self, *_args, **_kwargs):
            pass

        def authorization_url(self, _url, **_kwargs):
            return "https://x.example/authorize", "test-oauth-state"

    monkeypatch.setattr(x_oauth, "OAuth2Session", FakeOAuthSession)


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
