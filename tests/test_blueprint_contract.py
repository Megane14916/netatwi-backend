"""Admin and news responses before moving their handlers into Blueprints."""

from datetime import datetime, timedelta, timezone

from app import db
from models import Contest, News


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def test_admin_contest_management_update_and_delete(
    client, user_factory, contest_factory, login, fixed_time
):
    contest = contest_factory(
        NOW + timedelta(hours=1), NOW + timedelta(hours=2), NOW + timedelta(hours=3)
    )
    login(user_factory("test_admin"))
    fixed_time(NOW)

    management = client.get("/api/admin/contests/management")
    assert management.status_code == 200
    assert [item["id"] for item in management.get_json()] == [contest.id]

    updated = client.put(
        f"/api/admin/contests/{contest.id}",
        json={"name": "Renamed", "generalVoteWeight": 70},
    )
    assert updated.status_code == 200
    assert updated.get_json() == {"message": "Contest updated successfully"}
    assert db.session.get(Contest, contest.id).name == "Renamed"
    assert db.session.get(Contest, contest.id).general_vote_weight == 70

    deleted = client.delete(f"/api/admin/contests/{contest.id}")
    assert deleted.status_code == 200
    assert deleted.get_json() == {"message": "大会が正常に削除されました。"}
    assert db.session.get(Contest, contest.id) is None


def test_admin_news_create_list_and_delete(client, user_factory, login):
    login(user_factory("test_admin"))

    missing = client.post("/api/admin/news", json={})
    created = client.post(
        "/api/admin/news",
        json={"tweet_id": "https://x.com/example/status/123456"},
    )
    assert missing.status_code == 400
    assert missing.get_json() == {"error": "ツイートIDまたはURLは必須です。"}
    assert created.status_code == 201
    assert created.get_json()["message"] == "ニュースを追加しました。"
    news_id = created.get_json()["id"]
    assert db.session.get(News, news_id).tweet_id == "123456"

    public = client.get("/api/news")
    admin = client.get("/api/admin/news")
    assert public.status_code == admin.status_code == 200
    assert public.get_json() == admin.get_json()
    assert public.get_json()[0]["tweet_id"] == "123456"

    deleted = client.delete(f"/api/admin/news/{news_id}")
    assert deleted.status_code == 200
    assert deleted.get_json() == {"message": "ニュースを削除しました。"}
    assert db.session.get(News, news_id) is None
