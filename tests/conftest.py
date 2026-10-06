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
        "TASKS_OIDC_AUDIENCE": "",
        "TASKS_SERVICE_ACCOUNT_EMAIL": "",
    }
)

import app as app_module  # noqa: E402
app_module.app  # Resolve the public entry before loading fakes and components.
from app.services import notifications as notifications_service  # noqa: E402
from app.services import contests as contest_service  # noqa: E402
from app.services import interactions as interaction_service  # noqa: E402
from app.services import posts as post_service  # noqa: E402
from app.services import users as user_service  # noqa: E402
from app.services import profile as profile_service  # noqa: E402
from app.services import results as results_service  # noqa: E402
from app.services import contest_lifecycle  # noqa: E402
from app.services import voting as voting_service  # noqa: E402
from app.integrations import cloud_tasks, x_oauth  # noqa: E402
from app import db  # noqa: E402
from app.models import Contest, User  # noqa: E402


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
        contest_service._contests_cache = None
        contest_service._contests_cache_time = 0
        db.create_all()
        try:
            yield flask_app
        finally:
            db.session.remove()
            db.drop_all()
            contest_service._contests_cache = None
            contest_service._contests_cache_time = 0


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(scope="session")
def task_signing_keys():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public_pem = private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return public_pem, private_pem


@pytest.fixture
def signed_task_headers(app, monkeypatch, task_signing_keys):
    import time
    from google.auth import jwt, crypt
    public, private = task_signing_keys
    app.config.update(TASKS_OIDC_AUDIENCE="https://backend.example",
                      TASKS_SERVICE_ACCOUNT_EMAIL="tasks@example.iam.gserviceaccount.com")
    monkeypatch.setattr(cloud_tasks.id_token, "_fetch_certs", lambda *_args: {"test-key": public.decode()})
    signer = crypt.RSASigner.from_string(private, key_id="test-key")
    def make(**overrides):
        now = int(time.time())
        claims = dict(iss="https://accounts.google.com", aud=app.config["TASKS_OIDC_AUDIENCE"],
                      sub="test-service-account-id", email=app.config["TASKS_SERVICE_ACCOUNT_EMAIL"],
                      email_verified=True, iat=now - 5, exp=now + 3600)
        claims.update(overrides)
        return {"Authorization": "Bearer " + jwt.encode(signer, claims).decode()}
    return make


@pytest.fixture
def task_client(app, signed_task_headers):
    client = app.test_client()
    client.environ_base["HTTP_AUTHORIZATION"] = signed_task_headers()["Authorization"]
    return client


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
        monkeypatch.setattr(user_service, "datetime", FixedDateTime)
        monkeypatch.setattr(contest_service, "datetime", FixedDateTime)
        monkeypatch.setattr(post_service, "datetime", FixedDateTime)
        monkeypatch.setattr(profile_service, "datetime", FixedDateTime)
        monkeypatch.setattr(voting_service, "datetime", FixedDateTime)
        monkeypatch.setattr(results_service, "datetime", FixedDateTime)
        monkeypatch.setattr(interaction_service, "datetime", FixedDateTime)
        monkeypatch.setattr(notifications_service, "datetime", FixedDateTime)
        monkeypatch.setattr(contest_lifecycle, "datetime", FixedDateTime)
        monkeypatch.setattr(cloud_tasks, "datetime", FixedDateTime)

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
    monkeypatch.setattr(cloud_tasks, "_cloud_tasks_client", client)
    monkeypatch.setenv("GCP_PROJECT_ID", "test")
    monkeypatch.setenv("GCP_LOCATION", "test")
    monkeypatch.setenv("GCP_QUEUE_NAME", "test")
    monkeypatch.setenv("TASK_HANDLER_URL", "https://backend.example")
    monkeypatch.setenv("TASKS_OIDC_AUDIENCE", "https://backend.example")
    monkeypatch.setenv("TASKS_SERVICE_ACCOUNT_EMAIL", "tasks@example.iam.gserviceaccount.com")
    return client
