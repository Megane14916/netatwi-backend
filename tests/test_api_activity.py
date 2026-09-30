"""Current post, vote, result, and interaction responses at key boundaries."""

from datetime import datetime, timedelta, timezone

from app import db
from models import Bookmark, Comment, Contest, ContestResult, Notification, Post, Vote


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def make_post(contest, user, content="A post"):
    post = Post(contest_id=contest.id, user_id=user.id, content=content)
    db.session.add(post)
    db.session.commit()
    return post


def test_post_create_list_duplicate_and_period_boundary(
    client, user_factory, contest_factory, login, fixed_time
):
    contest = contest_factory(NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2))
    author = user_factory("author")
    fixed_time(NOW)
    login(author)

    created = client.post(f"/api/contests/{contest.id}/posts", data={"content": "Hello"})
    listing = client.get(f"/api/contests/{contest.id}/posts")
    duplicate = client.post(f"/api/contests/{contest.id}/posts", data={"content": "Again"})

    assert created.status_code == 201
    assert created.get_json()["content"] == "Hello"
    assert created.get_json()["user_id"] == author.id
    assert listing.status_code == 200
    assert listing.get_json()["posts"][0]["id"] == created.get_json()["id"]
    assert listing.get_json()["totalPosters"] == 1
    assert duplicate.status_code == 409
    assert duplicate.get_json() == {"error": "Already posted"}

    fixed_time(NOW + timedelta(hours=1))
    login(user_factory("late_author"))
    outside = client.post(f"/api/contests/{contest.id}/posts", data={"content": "Late"})
    assert outside.status_code == 403
    assert outside.get_json() == {"error": "Outside period"}
    assert Post.query.filter_by(contest_id=contest.id).count() == 1


def test_final_post_requires_qualifier_result(
    client, user_factory, contest_factory, login, fixed_time
):
    qualifier = contest_factory(
        NOW - timedelta(days=2), NOW - timedelta(days=1), NOW - timedelta(hours=1)
    )
    final = contest_factory(
        NOW - timedelta(hours=1),
        NOW + timedelta(hours=1),
        NOW + timedelta(hours=2),
        parent_contest_id=qualifier.id,
    )
    fixed_time(NOW)
    login(user_factory("not_advanced"))

    response = client.post(f"/api/contests/{final.id}/posts", data={"content": "Hi"})

    assert response.status_code == 403
    assert response.get_json() == {
        "error": "予選を通過していないため、この大会には投稿できません"
    }


def test_post_edit_requires_owner_and_can_delete(
    client, user_factory, contest_factory, login, fixed_time
):
    contest = contest_factory(
        NOW - timedelta(hours=1), NOW + timedelta(hours=1), NOW + timedelta(hours=2)
    )
    author = user_factory("author")
    stranger = user_factory("stranger")
    post = make_post(contest, author)
    fixed_time(NOW)

    login(stranger)
    denied = client.put(
        f"/api/contests/{contest.id}/posts/{post.id}", json={"content": "Edited"}
    )
    assert denied.status_code == 404
    assert denied.get_json() == {"error": "Not found"}

    login(author)
    edited = client.put(
        f"/api/contests/{contest.id}/posts/{post.id}", json={"content": "Edited"}
    )
    deleted = client.delete(f"/api/contests/{contest.id}/posts/{post.id}")

    assert edited.status_code == 200
    assert edited.get_json()["content"] == "Edited"
    assert deleted.status_code == 200
    assert deleted.get_json() == {"message": "Deleted successfully"}
    assert db.session.get(Post, post.id) is None


def test_vote_replacement_and_voting_end_boundary(
    client, user_factory, contest_factory, login, fixed_time
):
    contest = contest_factory(NOW - timedelta(hours=2), NOW, NOW + timedelta(hours=1))
    post = make_post(contest, user_factory("author"))
    voter = user_factory("voter")
    login(voter)
    fixed_time(NOW)
    path = f"/api/contests/{contest.id}/vote"
    payload = {"votes": {str(post.id): 1}}

    invalid = client.post(path, json={"votes": []})
    first = client.post(path, json=payload)
    second = client.post(path, json=payload)

    assert invalid.status_code == 400
    assert invalid.get_json() == {"error": "Invalid vote data"}
    assert first.status_code == second.status_code == 200
    assert first.get_json() == {"message": "Voted"}
    assert Vote.query.filter_by(user_id=voter.id, contest_id=contest.id).count() == 1
    assert db.session.get(Contest, contest.id).total_voters == 1

    fixed_time(NOW + timedelta(hours=1))
    outside = client.post(path, json={"votes": {}})
    assert outside.status_code == 403
    assert outside.get_json() == {"error": "Outside period"}
    assert Vote.query.filter_by(user_id=voter.id, contest_id=contest.id).count() == 1


def test_judge_can_submit_zero_score(
    client, user_factory, contest_factory, login, fixed_time
):
    contest = contest_factory(NOW - timedelta(hours=2), NOW, NOW + timedelta(hours=1))
    post = make_post(contest, user_factory("author"))
    judge = user_factory("judge")
    login(judge, judge_contests=[contest.id])
    fixed_time(NOW)

    response = client.post(
        f"/api/contests/{contest.id}/vote", json={"votes": {str(post.id): 0}}
    )

    vote = Vote.query.filter_by(user_id=judge.id, post_id=post.id).one()
    assert response.status_code == 200
    assert vote.count == 0
    assert vote.is_judge_vote is True
    assert db.session.get(Contest, contest.id).total_judges == 1


def test_result_visibility_and_persisted_score(
    client, user_factory, contest_factory, fixed_time
):
    contest = contest_factory(NOW - timedelta(hours=2), NOW - timedelta(hours=1), NOW)
    author = user_factory("author")
    post = make_post(contest, author)
    contest.post_count = 1
    db.session.add(
        ContestResult(
            contest_id=contest.id,
            post_id=post.id,
            user_id=author.id,
            score=12.5,
            rank=1,
        )
    )
    db.session.commit()
    path = f"/api/contests/{contest.id}/results"

    fixed_time(NOW - timedelta(microseconds=1))
    early = client.get(path)
    assert early.status_code == 403
    assert early.get_json() == {"error": "Voting ongoing"}

    fixed_time(NOW)
    published = client.get(path)
    assert published.status_code == 200
    data = published.get_json()
    assert data["contest"] == {"id": contest.id, "name": contest.name, "theme": None}
    assert data["totalPosters"] == 1
    assert data["judgeAwards"] == []
    assert data["results"][0]["post_id"] == post.id
    assert data["results"][0]["score"] == 12.5
    assert data["results"][0]["rank"] == 1
    assert data["results"][0]["user"]["screen_name"] == "author"


def test_comment_create_duplicate_edit_and_delete(
    client, user_factory, contest_factory, login, fixed_time
):
    contest = contest_factory(
        NOW - timedelta(hours=1), NOW + timedelta(hours=1), NOW + timedelta(hours=2)
    )
    post = make_post(contest, user_factory("author"))
    commenter = user_factory("commenter")
    login(commenter)
    fixed_time(NOW)
    path = f"/api/posts/{post.id}/comments"

    created = client.post(path, json={"content": "First"})
    duplicate = client.post(path, json={"content": "Again"})
    listed = client.get(path)
    grouped = client.get(f"/api/comments?postIds={post.id}")

    assert created.status_code == 201
    assert duplicate.status_code == 409
    assert listed.get_json()[0]["content"] == "First"
    assert grouped.get_json()[str(post.id)][0]["content"] == "First"
    assert db.session.get(Post, post.id).comment_count == 1

    comment_id = created.get_json()["id"]
    updated = client.put(f"/api/comments/{comment_id}", json={"content": "Updated"})
    deleted = client.delete(f"/api/comments/{comment_id}")
    assert updated.status_code == deleted.status_code == 200
    assert db.session.get(Comment, comment_id) is None
    assert db.session.get(Post, post.id).comment_count == 0


def test_judge_comment_can_exceed_140_characters(
    client, user_factory, contest_factory, login
):
    contest = contest_factory(
        NOW - timedelta(hours=1), NOW + timedelta(hours=1), NOW + timedelta(hours=2)
    )
    post = make_post(contest, user_factory("author"))
    long_comment = "x" * 141
    login(user_factory("member"))

    rejected = client.post(f"/api/posts/{post.id}/comments", json={"content": long_comment})
    assert rejected.status_code == 400

    login(user_factory("judge"), judge_contests=[contest.id])
    accepted = client.post(f"/api/posts/{post.id}/comments", json={"content": long_comment})
    assert accepted.status_code == 201
    assert db.session.get(Comment, accepted.get_json()["id"]).is_judge is True


def test_bookmark_put_and_delete_are_idempotent(
    client, user_factory, contest_factory, login
):
    contest = contest_factory(
        NOW - timedelta(hours=1), NOW + timedelta(hours=1), NOW + timedelta(hours=2)
    )
    post = make_post(contest, user_factory("author"))
    login(user_factory("reader"))
    path = f"/api/posts/{post.id}/bookmark"

    first = client.put(path)
    repeat = client.put(path)
    removed = client.delete(path)

    assert first.get_json()["bookmarkCount"] == 1
    assert repeat.get_json()["bookmarkCount"] == 1
    assert removed.get_json()["bookmarkCount"] == 0
    assert Bookmark.query.filter_by(post_id=post.id).count() == 0


def test_like_after_judge_only_result_creates_notification(
    client, user_factory, contest_factory, login, fixed_time
):
    contest = contest_factory(
        NOW - timedelta(hours=2),
        NOW - timedelta(hours=1),
        NOW,
        scoring_method="judge",
    )
    author = user_factory("author")
    post = make_post(contest, author)
    login(user_factory("reader"))
    fixed_time(NOW)
    path = f"/api/posts/{post.id}/like"

    liked = client.put(path)
    repeated = client.put(path)
    unliked = client.delete(path)

    assert liked.status_code == repeated.status_code == unliked.status_code == 200
    assert liked.get_json() == {"isLiked": True, "likeCount": 1}
    assert repeated.get_json() == {"isLiked": True, "likeCount": 1}
    assert unliked.get_json() == {"isLiked": False, "likeCount": 0}
    assert Notification.query.filter_by(user_id=author.id, type="like").count() == 1


def test_notification_list_and_mark_read(
    client, user_factory, contest_factory, login
):
    contest = contest_factory(
        NOW - timedelta(hours=2), NOW - timedelta(hours=1), NOW
    )
    recipient = user_factory("recipient")
    sender = user_factory("sender")
    post = make_post(contest, recipient)
    db.session.add(
        Notification(
            user_id=recipient.id,
            sender_id=sender.id,
            type="like",
            post_id=post.id,
            contest_id=contest.id,
        )
    )
    db.session.commit()
    login(recipient)

    listed = client.get("/api/notifications")
    before = client.get("/api/notifications/unread-count")
    marked = client.post("/api/notifications/read")
    after = client.get("/api/notifications/unread-count")

    assert listed.status_code == 200
    assert listed.get_json()[0]["sender"]["screen_name"] == "sender"
    assert listed.get_json()[0]["is_read"] is False
    assert before.get_json() == {"unread_count": 1}
    assert marked.get_json() == {"message": "All notifications marked as read"}
    assert after.get_json() == {"unread_count": 0}
