"""Representative HTTP contracts before moving routes into Blueprints."""

from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models import Contest, User


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("DELETE", "/api/users/me", None),
        ("POST", "/api/admin/contests", {}),
        ("GET", "/api/admin/contests/management", None),
        ("GET", "/api/admin/news", None),
        ("POST", "/api/contests/1/judge/login", {"password": "secret"}),
        ("POST", "/api/contests/1/posts", None),
        ("POST", "/api/contests/1/vote", {"votes": {}}),
        ("PUT", "/api/posts/1/bookmark", None),
        ("PUT", "/api/posts/1/like", None),
        ("POST", "/api/posts/1/comments", {"content": "hello"}),
        ("GET", "/api/notifications", None),
        ("GET", "/api/notifications/unread-count", None),
        ("POST", "/api/notifications/read", None),
    ],
)
def test_anonymous_mutations_require_login(client, method, path, payload):
    response = client.open(path, method=method, json=payload)

    assert response.status_code == 401
    assert "error" in response.get_json()


def test_login_session_and_logout_contract(client, user_factory, login):
    user = user_factory("member")
    login(user, judge_contests=[12])

    response = client.get("/api/me")
    assert response.status_code == 200
    assert response.get_json() == {
        "logged_in": True,
        "user": {
            "id": user.id,
            "screen_name": "member",
            "name": "member",
            "profile_image_url": None,
            "isAdmin": False,
        },
        "judge_contests": [12],
    }

    assert client.get("/api/logout").get_json() == {
        "message": "Logged out successfully"
    }
    assert client.get("/api/me").get_json() == {"logged_in": False}


def test_oauth_callback_without_session_redirects(client):
    response = client.get("/api/callback/twitter?code=example&state=example")

    assert response.status_code == 302
    assert response.location == "http://localhost:3000?login_error=session_token_missing"


def test_withdrawal_is_soft_delete(client, user_factory, login):
    user = user_factory("departing")
    login(user)

    response = client.delete("/api/users/me")

    assert response.status_code == 200
    assert response.get_json() == {"message": "退会処理が完了しました"}
    assert db.session.get(User, user.id).deleted_at is not None
    assert client.get("/api/me").get_json() == {"logged_in": False}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/admin/contests"),
        ("GET", "/api/admin/contests/management"),
        ("GET", "/api/admin/news"),
        ("POST", "/api/admin/news"),
    ],
)
def test_non_admin_cannot_use_admin_api(client, user_factory, login, method, path):
    login(user_factory("member"))

    response = client.open(path, method=method, json={})

    assert response.status_code == 403
    assert response.get_json() == {"error": "Forbidden: Admins only"}


def test_admin_can_create_contest(client, user_factory, login):
    login(user_factory("test_admin"))

    response = client.post(
        "/api/admin/contests",
        json={
            "name": "New contest",
            "startTime": "2026-01-01T10:00:00Z",
            "endTime": "2026-01-01T11:00:00Z",
            "votingEndTime": "2026-01-01T12:00:00Z",
        },
    )

    assert response.status_code == 201
    assert response.get_json()["message"] == "Contest created successfully"
    assert db.session.get(Contest, response.get_json()["id"]).name == "New contest"


def test_judge_password_sets_session(client, user_factory, contest_factory, login):
    contest = contest_factory(
        NOW - timedelta(hours=2),
        NOW - timedelta(hours=1),
        NOW + timedelta(hours=1),
        judge_password="judge-secret",
    )
    login(user_factory("judge"))

    wrong = client.post(
        f"/api/contests/{contest.id}/judge/login", json={"password": "wrong"}
    )
    correct = client.post(
        f"/api/contests/{contest.id}/judge/login",
        json={"password": "judge-secret"},
    )

    assert wrong.status_code == 401
    assert correct.status_code == 200
    assert correct.get_json() == {"redirectUrl": f"/venue/{contest.id}"}
    with client.session_transaction() as session:
        assert session["judge_for_contest_ids"] == [contest.id]


def test_public_contest_and_profile_contract(
    client, user_factory, contest_factory, fixed_time
):
    fixed_time(NOW)
    contest = contest_factory(
        NOW - timedelta(hours=1), NOW + timedelta(hours=1), NOW + timedelta(hours=2)
    )
    user_factory("author")

    listing = client.get("/api/contests")
    detail = client.get(f"/api/contests/{contest.id}")
    profile = client.get("/api/profile/author")

    assert listing.status_code == 200
    assert [item["id"] for item in listing.get_json()["ongoing"]] == [contest.id]
    assert detail.status_code == 200
    assert detail.get_json()["id"] == contest.id
    assert detail.get_json()["postCount"] == 0
    assert profile.status_code == 200
    assert profile.get_json()["user"]["screen_name"] == "author"
    assert profile.get_json()["posts"] == []
    assert client.get("/api/profile/missing").status_code == 404


def test_public_news_and_user_list_are_empty(client):
    news = client.get("/api/news")
    users = client.get("/api/users")

    assert news.status_code == 200
    assert news.get_json() == []
    assert users.status_code == 200
    assert users.get_json()["users"] == []
