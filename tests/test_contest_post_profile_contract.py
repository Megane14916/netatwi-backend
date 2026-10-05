"""Contest and profile responses before moving their handlers into Blueprints."""

from datetime import datetime, timedelta, timezone

from app import db
from app.models import Post


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def test_contest_list_classifies_periods_and_latest_result(
    client, contest_factory, fixed_time
):
    fixed_time(NOW)
    ongoing = contest_factory(
        NOW - timedelta(hours=1), NOW + timedelta(hours=1), NOW + timedelta(hours=2)
    )
    voting = contest_factory(
        NOW - timedelta(hours=2), NOW - timedelta(hours=1), NOW + timedelta(hours=1)
    )
    upcoming = contest_factory(
        NOW + timedelta(hours=1), NOW + timedelta(hours=2), NOW + timedelta(hours=3)
    )
    closed = contest_factory(
        NOW - timedelta(hours=3), NOW - timedelta(hours=2), NOW - timedelta(hours=1)
    )

    response = client.get("/api/contests")

    assert response.status_code == 200
    payload = response.get_json()
    assert [item["id"] for item in payload["ongoing"]] == [ongoing.id]
    assert [item["id"] for item in payload["voting"]] == [voting.id]
    assert [item["id"] for item in payload["upcoming"]] == [upcoming.id]
    assert [item["id"] for item in payload["closed"]] == [closed.id]
    assert payload["latestResult"]["contest_id"] == closed.id
    assert payload["ongoing"][0]["startTime"].endswith("+09:00")


def test_profile_shows_posts_after_voting_ends(
    client, user_factory, contest_factory, fixed_time
):
    fixed_time(NOW)
    author = user_factory("profile_author")
    closed = contest_factory(
        NOW - timedelta(hours=3), NOW - timedelta(hours=2), NOW - timedelta(hours=1)
    )
    voting = contest_factory(
        NOW - timedelta(hours=2), NOW - timedelta(hours=1), NOW + timedelta(hours=1)
    )
    closed_post = Post(contest_id=closed.id, user_id=author.id, content="Visible")
    voting_post = Post(contest_id=voting.id, user_id=author.id, content="Hidden")
    db.session.add_all([closed_post, voting_post])
    db.session.commit()

    response = client.get("/api/profile/profile_author")

    assert response.status_code == 200
    assert [item["post_id"] for item in response.get_json()["posts"]] == [
        closed_post.id
    ]
    assert response.get_json()["posts"][0]["content"] == "Visible"
    assert response.get_json()["bookmarks"] == []
    assert response.get_json()["likes"] == []
