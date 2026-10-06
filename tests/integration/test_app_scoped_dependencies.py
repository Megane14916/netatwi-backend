"""Regression coverage for configuration, cache and fake isolation (#69)."""

from datetime import datetime, timedelta, timezone

from app import create_app
from app.extensions import db
from app.models import Contest
from tests.integration.test_package_entry_contract import run_isolated
from app.integrations import images, cloud_tasks
from unittest.mock import Mock


def test_contest_cache_never_leaks_between_databases():
    apps = [create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "SECRET_KEY": name}) for name in ("first", "second")]
    now = datetime.now(timezone.utc)
    try:
        for application, name in zip(apps, ("first", "second")):
            with application.app_context():
                db.create_all()
                db.session.add(Contest(name=name, start_time=now-timedelta(hours=1), end_time=now+timedelta(hours=1), voting_end_time=now+timedelta(hours=2)))
                db.session.commit()
        for index in (0, 1, 0, 1):
            result = apps[index].test_client().get("/api/contests")
            assert [c["name"] for c in result.get_json()["ongoing"]] == ["first" if index == 0 else "second"]
    finally:
        for application in apps:
            with application.app_context():
                db.session.remove()
                db.drop_all()


def test_oauth_import_before_configuration_uses_each_application_credentials():
    run_isolated('''
        import os
        os.environ.pop("X_CONSUMER_KEY", None)
        os.environ.pop("X_CONSUMER_SECRET", None)
        from app.integrations import x_oauth
        from app import create_app
        calls = []
        class FakeOAuth:
            def __init__(self, client_id, **kwargs):
                calls.append((client_id, kwargs["redirect_uri"]))
            def authorization_url(self, *args, **kwargs):
                return "https://x.example/auth", "state"
        x_oauth.OAuth2Session = FakeOAuth
        apps = [create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "X_CONSUMER_KEY": name, "X_CONSUMER_SECRET": name+"-secret", "FRONTEND_URL": "https://"+name+".example"}) for name in ("one", "two")]
        for index in (1, 0, 1):
            assert apps[index].test_client().get("/api/login/twitter").status_code == 200
        assert calls == [("two", "https://two.example/api/callback/twitter"), ("one", "https://one.example/api/callback/twitter"), ("two", "https://two.example/api/callback/twitter")]
    ''')


def test_r2_client_is_lazy_and_uses_active_application_configuration(monkeypatch):
    applications = [create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "R2_ENDPOINT_URL": "https://"+name+".example", "R2_ACCESS_KEY_ID": name, "R2_SECRET_ACCESS_KEY": name+"-secret"}) for name in ("first", "second")]
    factory = Mock(side_effect=[Mock(), Mock()])
    monkeypatch.setattr(images.boto3, "client", factory)
    assert all("r2_client" not in a.extensions for a in applications)
    for index in (1, 0, 1):
        with applications[index].app_context():
            assert images.get_r2_client() is applications[index].extensions["r2_client"]
    assert factory.call_count == 2
    assert [c.kwargs["endpoint_url"] for c in factory.call_args_list] == ["https://second.example", "https://first.example"]
    assert [c.kwargs["aws_access_key_id"] for c in factory.call_args_list] == ["second", "first"]


def test_cloud_tasks_clients_and_configuration_are_lazy_and_app_scoped(monkeypatch):
    applications = [create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "GCP_PROJECT_ID": name, "GCP_LOCATION": "location", "GCP_QUEUE_NAME": "queue", "TASK_HANDLER_URL": "https://"+name+".example", "TASKS_OIDC_AUDIENCE": "https://"+name+".example", "TASKS_SERVICE_ACCOUNT_EMAIL": name+"@example.com"}) for name in ("first", "second")]
    clients = [Mock(), Mock()]
    factory = Mock(side_effect=[clients[1], clients[0]])
    monkeypatch.setattr(cloud_tasks.tasks_v2, "CloudTasksClient", factory)
    assert all("cloud_tasks_client" not in a.extensions for a in applications)
    for index in (1, 0, 1):
        with applications[index].app_context():
            cloud_tasks.schedule_contest_task(1, "post_start", datetime.now(timezone.utc))
            assert applications[index].extensions["cloud_tasks_client"] is clients[index]
    assert factory.call_count == 2
    for client, name in zip(clients, ("first", "second")):
        client.queue_path.assert_called_with(name, "location", "queue")
        http = client.create_task.call_args.kwargs["request"]["task"]["http_request"]
        assert http["url"] == "https://"+name+".example/api/tasks/contest/1/post_start"
        assert http["oidc_token"] == {"service_account_email": name+"@example.com", "audience": "https://"+name+".example"}
