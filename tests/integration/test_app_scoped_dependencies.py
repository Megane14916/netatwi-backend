"""Regression coverage for configuration, cache and fake isolation (#69)."""

from datetime import datetime, timedelta, timezone

from app import create_app
from app.extensions import db
from app.models import Contest
from tests.integration.test_package_entry_contract import run_isolated


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
