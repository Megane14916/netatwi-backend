"""Authentication behavior captured before the issue #12 service extraction."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import secrets

import pytest
import requests

from app.integrations import x_oauth
from app.models import User, db


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
FRONTEND = "http://localhost:3000"


@pytest.mark.parametrize("flow", ["login", "login_failure", "success", "mismatch", "error", "http", "fetch"])
def test_oauth_logs_never_contain_request_session_token_or_error_secrets(
    client, fake_oauth, caplog, capsys, flow
):
    secret = "sensitive-value-do-not-log"
    with client.session_transaction() as session:
        session.update(oauth_state=secret + "-state", code_verifier=secret + "-verifier")
        session[secret + "-key"] = secret + "-value"
    client.set_cookie("private", secret + "-cookie")
    token = secret + "-token"
    fake_oauth.oauth.return_value.fetch_token.return_value = {"access_token": token}
    if flow == "login_failure":
        fake_oauth.oauth.return_value.authorization_url.side_effect = RuntimeError(secret)
    elif flow == "http":
        fake_oauth.response.status_code = 403
        fake_oauth.response.text = secret + "-body"
        fake_oauth.response.raise_for_status.side_effect = requests.HTTPError(secret)
    elif flow == "fetch":
        fake_oauth.oauth.return_value.fetch_token.side_effect = RuntimeError(secret)
    headers = {"Authorization": "Bearer " + secret, "X-Forwarded-Proto": "https"}
    path = "/api/login/twitter" if flow.startswith("login") else "/api/callback/twitter"
    state = "mismatch-" + secret if flow == "mismatch" else secret + "-state"
    with caplog.at_level("INFO", logger="app"):
        client.get(path, headers=headers, query_string={"state": state, "code": secret + "-code",
                                                       **({"error": secret + "-error"} if flow == "error" else {})})
    output = capsys.readouterr()
    assert secret not in caplog.text + output.out + output.err
    assert token[:10] not in caplog.text
    assert "OAuth request" in caplog.text


@pytest.fixture
def fake_oauth(monkeypatch):
    oauth = Mock()
    oauth.return_value.authorization_url.return_value = (
        "https://x.example/authorize?scope=tweet.read+users.read", "oauth-state",
    )
    oauth.return_value.fetch_token.return_value = {"access_token": "test-access-token"}
    response = Mock(status_code=200)
    response.json.return_value = {"data": {
        "id": "twitter-member", "username": "updated", "name": "Updated Name",
        "profile_image_url": "https://x.example/avatar_normal.png",
    }}
    get = Mock(return_value=response)
    random = Mock(return_value=VERIFIER)
    monkeypatch.setattr(x_oauth, "OAuth2Session", oauth)
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(secrets, "token_urlsafe", random)
    return SimpleNamespace(oauth=oauth, response=response, get=get, random=random)


def seed_callback_session(client, **overrides):
    with client.session_transaction() as session:
        session.update({
            "oauth_state": "oauth-state", "code_verifier": VERIFIER,
            "judge_for_contest_ids": [9], "unrelated": "keep",
            **overrides,
        })


def observe_transactions(monkeypatch):
    events = []
    for method in ("commit", "rollback"):
        original = getattr(db.session, method)

        def record(*args, _method=method, _original=original, **kwargs):
            events.append(_method)
            return _original(*args, **kwargs)

        monkeypatch.setattr(db.session, method, record)
    return events


def test_oauth_start_preserves_pkce_scope_session_and_logs(client, fake_oauth, caplog):
    seed_callback_session(client, user_id=123)
    with caplog.at_level("INFO", logger="app"):
        response = client.get("/api/login/twitter")
    assert response.status_code == 200
    assert response.get_json() == {
        "authorization_url": "https://x.example/authorize?scope=tweet.read%20users.read",
    }
    fake_oauth.random.assert_called_once_with(48)
    fake_oauth.oauth.assert_called_once_with(
        "test-client-id", redirect_uri=f"{FRONTEND}/api/callback/twitter",
        scope=["tweet.read", "users.read"],
    )
    fake_oauth.oauth.return_value.authorization_url.assert_called_once_with(
        "https://x.com/i/oauth2/authorize",
        code_challenge="E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        code_challenge_method="s256",
    )
    with client.session_transaction() as session:
        assert dict(session) == {
            "oauth_state": "oauth-state", "code_verifier": VERIFIER,
            "judge_for_contest_ids": [9],
        }
    assert [r.getMessage() for r in caplog.records if r.name == "app"
            and r.filename in ("auth.py", "x_oauth.py")] == [
        f"Generated Callback URL: {FRONTEND}/api/callback/twitter",
        "Saved to session - State: oauth-state",
    ]


def test_oauth_start_failure_keeps_previous_session(client, fake_oauth, caplog):
    seed_callback_session(client)
    fake_oauth.oauth.return_value.authorization_url.side_effect = RuntimeError("authorization failed")
    response = client.get("/api/login/twitter")
    assert response.status_code == 500
    assert response.get_json() == {"error": "Failed to connect to Twitter"}
    with client.session_transaction() as session:
        assert session["oauth_state"] == "oauth-state"
        assert session["unrelated"] == "keep"
    assert "!!! ERROR at /api/login/twitter: authorization failed" in caplog.text


@pytest.mark.parametrize("existing", (False, True))
def test_callback_syncs_user_commits_then_sets_session(
    client, fake_oauth, user_factory, monkeypatch, caplog, existing
):
    user = user_factory("member") if existing else None
    seed_callback_session(client)
    events = observe_transactions(monkeypatch)
    with caplog.at_level("INFO", logger="app"):
        response = client.get("/api/callback/twitter?state=oauth-state&code=code")
    assert response.status_code == 302
    assert response.location == FRONTEND
    assert events == ["commit"]
    saved = User.query.filter_by(twitter_id="twitter-member").one()
    if existing:
        assert saved.id == user.id
    assert (saved.screen_name, saved.name, saved.profile_image_url) == (
        "updated", "Updated Name", "https://x.example/avatar.png",
    )
    fake_oauth.oauth.assert_called_once_with(
        "test-client-id", redirect_uri=f"{FRONTEND}/api/callback/twitter", state="oauth-state",
    )
    token_args = fake_oauth.oauth.return_value.fetch_token.call_args.kwargs
    assert {k: v for k, v in token_args.items() if k != "auth"} == {
        "token_url": "https://api.x.com/2/oauth2/token", "client_secret": "test-client-secret",
        "code": "code", "code_verifier": VERIFIER,
    }
    assert (token_args["auth"].username, token_args["auth"].password) == (
        "test-client-id", "test-client-secret",
    )
    fake_oauth.get.assert_called_once_with(
        "https://api.x.com/2/users/me?user.fields=profile_image_url",
        headers={"Authorization": "Bearer test-access-token"},
    )
    with client.session_transaction() as session:
        assert dict(session) == {
            "_permanent": True, "user_id": saved.id, "screen_name": "updated",
            "name": "Updated Name", "profile_image_url": "https://x.example/avatar.png",
            "judge_for_contest_ids": [9], "unrelated": "keep",
        }
    messages = [r.getMessage() for r in caplog.records if r.name == "app"
                and r.filename in ("auth.py", "x_oauth.py")]
    assert messages == [
        "=== CALLBACK START ===",
        "Session keys present: ['code_verifier', 'judge_for_contest_ids', 'oauth_state', 'unrelated']",
        "Access Token successfully fetched (starts with: test-acces...)",
        "Login successful for user: updated",
    ]


@pytest.mark.parametrize("state,verifier,query,reason", [
    (None, None, "error=denied", "denied"),
    (None, VERIFIER, "state=oauth-state&code=code", "session_token_missing"),
    ("oauth-state", None, "state=oauth-state&code=code", "verifier_missing"),
    ("oauth-state", VERIFIER, "state=oauth-state", "verifier_missing"),
    ("oauth-state", VERIFIER, "state=wrong&code=code", "state_mismatch"),
])
def test_callback_validation_consumes_tokens_without_external_calls(
    client, fake_oauth, monkeypatch, state, verifier, query, reason
):
    seed_callback_session(client, oauth_state=state, code_verifier=verifier)
    events = observe_transactions(monkeypatch)
    response = client.get(f"/api/callback/twitter?{query}")
    assert response.status_code == 302
    assert response.location == f"{FRONTEND}?login_error={reason}"
    fake_oauth.oauth.assert_not_called()
    fake_oauth.get.assert_not_called()
    assert events == []
    with client.session_transaction() as session:
        assert dict(session) == {"judge_for_contest_ids": [9], "unrelated": "keep"}


@pytest.mark.parametrize("failure", ("fetch", "token", "http", "user_id", "commit"))
def test_callback_failures_rollback_and_preserve_other_session_data(
    client, fake_oauth, monkeypatch, caplog, failure
):
    seed_callback_session(client)
    events = observe_transactions(monkeypatch)
    if failure == "fetch":
        fake_oauth.oauth.return_value.fetch_token.side_effect = RuntimeError("fetch failed")
    elif failure == "token":
        fake_oauth.oauth.return_value.fetch_token.return_value = {}
    elif failure == "http":
        fake_oauth.response.status_code = 403
        fake_oauth.response.text = "X error body"
        fake_oauth.response.raise_for_status.side_effect = requests.HTTPError("denied")
    elif failure == "user_id":
        fake_oauth.response.json.return_value = {"data": {}}
    else:
        def fail_commit():
            events.append("commit")
            raise RuntimeError("commit failed")
        monkeypatch.setattr(db.session, "commit", fail_commit)
    response = client.get("/api/callback/twitter?state=oauth-state&code=code")
    assert response.status_code == 302
    assert response.location == f"{FRONTEND}?login_error=callback_failed"
    assert events == (["commit", "rollback"] if failure == "commit" else ["rollback"])
    assert User.query.count() == 0
    with client.session_transaction() as session:
        assert dict(session) == {"judge_for_contest_ids": [9], "unrelated": "keep"}
    if failure == "http":
        assert "X API Error Response Body: X error body" in caplog.text
    assert "!!! ERROR at /api/callback/twitter:" in caplog.text


def test_deleted_user_callback_does_not_update_or_commit(
    client, fake_oauth, user_factory, monkeypatch
):
    user = user_factory("member")
    user.deleted_at = NOW
    db.session.commit()
    seed_callback_session(client)
    events = observe_transactions(monkeypatch)
    response = client.get("/api/callback/twitter?state=oauth-state&code=code")
    assert response.location == f"{FRONTEND}?login_error=account_deleted"
    assert events == []
    assert db.session.get(User, user.id).screen_name == "member"
    with client.session_transaction() as session:
        assert "user_id" not in session


@pytest.mark.parametrize("scoring,password,configured,status,message", [
    ("both", "", "secret", 400, "パスワードを入力してください。"),
    ("both", "wrong", "secret", 401, "パスワードが正しくありません。"),
    ("both", "secret", None, 401, "パスワードが正しくありません。"),
    ("user", "secret", "secret", 400, "この大会は一般投票のみのため、審査員として参加できません。"),
])
def test_judge_rejections_leave_session_and_database_unchanged(
    client, contest_factory, user_factory, login, monkeypatch,
    scoring, password, configured, status, message,
):
    contest = contest_factory(
        NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2),
        scoring_method=scoring, judge_password=configured,
    )
    login(user_factory("judge"), judge_contests=[9])
    events = observe_transactions(monkeypatch)
    response = client.post(f"/api/contests/{contest.id}/judge/login", json={"password": password})
    assert response.status_code == status
    assert response.get_json() == {"error": message}
    assert events == []
    with client.session_transaction() as session:
        assert session["judge_for_contest_ids"] == [9]


def test_judge_success_is_idempotent_and_missing_contest_stays_500(
    client, contest_factory, user_factory, login, monkeypatch, capsys
):
    contest = contest_factory(NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2), judge_password="secret")
    user = user_factory("judge")
    login(user, judge_contests=[9])
    events = observe_transactions(monkeypatch)
    for _ in range(2):
        response = client.post(f"/api/contests/{contest.id}/judge/login", json={"password": "secret"})
        assert response.status_code == 200
        assert response.get_json() == {"redirectUrl": f"/venue/{contest.id}"}
    with client.session_transaction() as session:
        assert session["judge_for_contest_ids"] == [9, contest.id]
    assert capsys.readouterr().out == (
        f"--- Judge Login Success: User {user.id} for Contest {contest.id} ---\n"
        f" -> Current Judge Contests in Session: [9, {contest.id}]\n"
    ) * 2
    missing = client.post("/api/contests/999/judge/login", json={"password": "secret"})
    assert missing.status_code == 500
    assert missing.get_json() == {"error": "審査員認証中にエラーが発生しました。"}
    assert events == []


def test_judge_null_json_keeps_exception_outside_handler(client, user_factory, login):
    login(user_factory("judge"))
    with pytest.raises(AttributeError):
        client.post("/api/contests/1/judge/login", data="null", content_type="application/json")


def test_judge_rate_limit_remains_five_per_minute(
    client, contest_factory, user_factory, login, capsys
):
    contest = contest_factory(NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2), judge_password="secret")
    login(user_factory("judge"))
    responses = [client.post(f"/api/contests/{contest.id}/judge/login", json={"password": "secret"}) for _ in range(6)]
    assert [response.status_code for response in responses] == [200] * 5 + [429]
    assert capsys.readouterr().out.count("Judge Login Success") == 5
