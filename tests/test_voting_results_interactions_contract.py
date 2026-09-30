"""Responses and side effects captured before the issue #10 route move."""

from datetime import datetime, timedelta, timezone

import pytest

from models import Bookmark, Comment, ContestResult, Notification, Post, UserStats, Vote, db


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
JST_NOW = "2026-01-01T21:00:00+09:00"


def make_post(contest, author, **fields):
    post = Post(
        contest_id=contest.id, user_id=author.id, content="Entry", created_at=NOW,
        **fields,
    )
    db.session.add(post)
    db.session.commit()
    return post


def test_results_include_awards_voters_and_reader_interactions(
    client, user_factory, contest_factory, login, fixed_time
):
    contest = contest_factory(NOW - timedelta(hours=2), NOW - timedelta(hours=1), NOW)
    author = user_factory("author")
    reader = user_factory("reader")
    judge = user_factory("judge")
    post = make_post(contest, author, bookmark_count=1, comment_count=1)
    post.images = ["/static/uploads/test.png"]
    contest.post_count, contest.total_voters, contest.total_judges = 1, 2, 1
    db.session.add_all([
        ContestResult(contest_id=contest.id, post_id=post.id, user_id=author.id,
                      score=12.5, rank=1, is_advanced=True),
        Vote(contest_id=contest.id, post_id=post.id, user_id=reader.id, count=1),
        Vote(contest_id=contest.id, post_id=post.id, user_id=judge.id, count=0,
             is_judge_vote=True, is_judge_award=True, judge_comment="Award"),
        Bookmark(user_id=reader.id, post_id=post.id),
        Comment(user_id=reader.id, post_id=post.id, content="Comment"),
    ])
    db.session.commit()
    login(reader)
    fixed_time(NOW)

    response = client.get(f"/api/contests/{contest.id}/results")
    assert response.status_code == 200
    author_data = {"screen_name": "author", "name": "author", "profile_image_url": None}
    assert response.get_json() == {
        "contest": {"id": contest.id, "name": contest.name, "theme": None},
        "results": [{
            "rank": 1, "post_id": post.id, "content": "Entry",
            "images": ["/static/uploads/test.png"], "created_at": JST_NOW,
            "score": 12.5, "user": author_data,
            "voters": [
                {"screen_name": "judge", "name": "judge", "count": 0, "is_judge": True},
                {"screen_name": "reader", "name": "reader", "count": 1, "is_judge": False},
            ],
            "bookmarkCount": 1, "commentCount": 1, "hasCommented": True,
            "isBookmarked": True, "awards": ["judge賞"], "is_advanced": True,
        }],
        "judgeAwards": [{
            "judge": {"screen_name": "judge", "name": "judge", "profile_image_url": None},
            "comment": "Award",
            "post": {"post_id": post.id, "content": "Entry",
                     "images": ["/static/uploads/test.png"], "user": author_data,
                     "created_at": JST_NOW},
        }],
        "totalPosters": 1, "totalVoters": 2, "totalJudges": 1,
    }


def test_empty_results_keep_existing_response_shape(client, contest_factory, fixed_time):
    contest = contest_factory(NOW - timedelta(hours=2), NOW - timedelta(hours=1), NOW)
    fixed_time(NOW)
    response = client.get(f"/api/contests/{contest.id}/results")
    assert response.status_code == 200
    assert response.get_json() == {
        "contest": {"id": contest.id, "name": contest.name, "theme": None},
        "results": [], "judgeAwards": [], "totalPosters": 0, "totalVoters": 0,
    }


@pytest.mark.parametrize("before_result, own_post", [(True, False), (False, False), (False, True)])
def test_comment_notification_boundary_and_recipient(
    client, user_factory, contest_factory, login, fixed_time, before_result, own_post
):
    contest = contest_factory(NOW - timedelta(hours=2), NOW - timedelta(hours=1), NOW)
    author = user_factory("author")
    commenter = author if own_post else user_factory("commenter")
    post = make_post(contest, author)
    login(commenter)
    fixed_time(NOW - timedelta(microseconds=1) if before_result else NOW)

    response = client.post(f"/api/posts/{post.id}/comments", json={"content": " Comment "})
    assert response.status_code == 201
    comment = db.session.get(Comment, response.get_json()["id"])
    assert comment.content == " Comment "
    assert db.session.get(Post, post.id).comment_count == 1
    notifications = Notification.query.all()
    if before_result or own_post:
        assert notifications == []
    else:
        assert len(notifications) == 1
        notification = notifications[0]
        assert (notification.user_id, notification.sender_id, notification.type,
                notification.post_id, notification.contest_id) == (
            author.id, commenter.id, "comment", post.id, contest.id,
        )


def test_comment_queries_and_owner_validation(
    client, user_factory, contest_factory, login
):
    contest = contest_factory(NOW - timedelta(hours=2), NOW - timedelta(hours=1), NOW)
    post = make_post(contest, user_factory("author"))
    owner = user_factory("owner")
    comment = Comment(user_id=owner.id, post_id=post.id, content="Original")
    db.session.add(comment)
    db.session.commit()
    login(user_factory("other"))
    for method in (client.put, client.delete):
        response = method(f"/api/comments/{comment.id}", json={"content": "Changed"})
        assert response.status_code == 403
        assert response.get_json() == {"error": "Forbidden"}
    login(owner)
    rejected = client.put(f"/api/comments/{comment.id}", json={"content": " "})
    assert rejected.status_code == 400
    assert rejected.get_json() == {"error": "Invalid content length"}
    assert db.session.get(Comment, comment.id).content == "Original"
    assert client.get("/api/comments").get_json() == {}
    invalid = client.get("/api/comments?postIds=invalid")
    assert invalid.status_code == 400
    assert invalid.get_json() == {"error": "Invalid postIds format"}
    assert client.get("/api/posts/999/comments").status_code == 404


def test_notifications_are_scoped_ordered_and_include_previews(
    client, user_factory, contest_factory, login
):
    contest = contest_factory(NOW - timedelta(hours=2), NOW - timedelta(hours=1), NOW)
    recipient = user_factory("recipient")
    sender = user_factory("sender")
    post = make_post(contest, recipient)
    post.content = "p" * 41
    comment = Comment(user_id=sender.id, post_id=post.id, content="c" * 41)
    older = Notification(user_id=recipient.id, type="contest_post_start", created_at=NOW)
    newer = Notification(user_id=recipient.id, sender_id=sender.id, type="comment",
                         post_id=post.id, contest_id=contest.id,
                         created_at=NOW + timedelta(seconds=1))
    other = Notification(user_id=sender.id, type="contest_post_start", created_at=NOW)
    db.session.add_all([comment, older, newer, other])
    db.session.commit()
    login(recipient)

    response = client.get("/api/notifications")
    assert response.status_code == 200
    assert response.get_json() == [
        {"id": newer.id, "type": "comment", "is_read": False, "post_id": post.id,
         "contest_id": contest.id, "created_at": "2026-01-01T21:00:01+09:00",
         "sender": {"name": "sender", "screen_name": "sender", "profile_image_url": None},
         "post": {"content": "p" * 40 + "..."},
         "comment": {"content": "c" * 40 + "..."},
         "contest": {"name": contest.name, "type": contest.type}},
        {"id": older.id, "type": "contest_post_start", "is_read": False,
         "post_id": None, "contest_id": None, "created_at": JST_NOW,
         "sender": None, "post": None, "comment": None, "contest": None},
    ]
    assert client.get("/api/notifications/unread-count").get_json() == {"unread_count": 2}
    for _ in range(2):
        marked = client.post("/api/notifications/read")
        assert marked.status_code == 200
        assert marked.get_json() == {"message": "All notifications marked as read"}
    db.session.expire_all()
    assert db.session.get(Notification, other.id).is_read is False
    assert client.get("/api/notifications/unread-count").get_json() == {"unread_count": 0}


def test_users_list_filters_sorts_and_paginates(client, user_factory):
    beta = user_factory("beta")
    alpha = user_factory("alpha")
    deleted = user_factory("deleted")
    user_factory("without_stats")
    deleted.deleted_at = NOW
    db.session.add_all([
        UserStats(user_id=beta.id, rank=1, gp_1st=2, judge_awards=3),
        UserStats(user_id=alpha.id, rank=1),
        UserStats(user_id=deleted.id, rank=0),
    ])
    db.session.commit()

    response = client.get("/api/users")
    assert response.status_code == 200
    data = response.get_json()
    assert [user["id"] for user in data["users"]] == [alpha.id, beta.id]
    assert data["users"][1] == {
        "id": beta.id, "twitter_id": "twitter-beta", "name": "beta",
        "screen_name": "beta", "profile_image_url": None,
        "stats": {"gp_1st": 2, "gp_2nd": 0, "gp_3rd": 0, "daily_1st": 0,
                  "daily_2nd": 0, "daily_3rd": 0, "judge_awards": 3},
    }
    assert {key: value for key, value in data.items() if key != "users"} == {
        "page": 1, "total_pages": 1, "total_items": 2, "has_next": False, "has_prev": False,
    }
    for query in ("BETA", "twitter-beta"):
        assert [user["id"] for user in client.get(f"/api/users?q={query}").get_json()["users"]] == [beta.id]
    assert client.get("/api/users?page=2").get_json() == {
        "users": [], "page": 2, "total_pages": 1, "total_items": 2,
        "has_next": False, "has_prev": True,
    }
