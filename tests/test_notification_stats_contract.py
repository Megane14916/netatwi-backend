"""Notification/statistics behavior captured before the issue #17 extraction."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import Comment, ContestResult, Notification, Post, UserStats, Vote, db


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
FIELDS = ("gp_1st", "gp_2nd", "gp_3rd", "judge_awards", "daily_1st", "daily_2nd", "daily_3rd")


def make_post(contest, author, content="Entry"):
    post = Post(contest_id=contest.id, user_id=author.id, content=content)
    db.session.add(post)
    db.session.commit()
    return post


def observe_writes(monkeypatch):
    events = []
    for name in ("add", "commit", "rollback"):
        original = getattr(db.session, name)

        def record(*args, _name=name, _original=original, **kwargs):
            events.append(type(args[0]).__name__ if _name == "add" else _name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(db.session, name, record)
    return events


@pytest.mark.parametrize("kind", ("comment", "like"))
def test_notification_creation_order_and_remove_then_recreate(
    client, user_factory, contest_factory, login, fixed_time, monkeypatch, kind
):
    author = user_factory("author")
    sender = user_factory("sender")
    contest = contest_factory(NOW - timedelta(hours=2), NOW - timedelta(hours=1), NOW,
                              scoring_method="judge")
    post = make_post(contest, author)
    login(sender)
    fixed_time(NOW)
    events = observe_writes(monkeypatch)

    def create():
        if kind == "comment":
            return client.post(f"/api/posts/{post.id}/comments", json={"content": "Comment"})
        return client.put(f"/api/posts/{post.id}/like")

    first = create()
    assert first.status_code == (201 if kind == "comment" else 200)
    assert events == ["Comment" if kind == "comment" else "Vote", "Notification", "commit"]
    original_id = Notification.query.one().id
    events.clear()
    repeat = create()
    assert repeat.status_code == (409 if kind == "comment" else 200)
    assert events == ([] if kind == "comment" else ["commit"])
    assert Notification.query.count() == 1

    events.clear()
    path = (f"/api/comments/{first.get_json()['id']}" if kind == "comment"
            else f"/api/posts/{post.id}/like")
    assert client.delete(path).status_code == 200
    assert events == ["commit"]
    assert Notification.query.one().id == original_id
    events.clear()
    assert create().status_code == (201 if kind == "comment" else 200)
    assert events == ["Comment" if kind == "comment" else "Vote", "Notification", "commit"]
    assert [(n.user_id, n.sender_id, n.type, n.post_id, n.contest_id, n.is_read)
            for n in Notification.query.order_by(Notification.id).all()] == [
        (author.id, sender.id, kind, post.id, contest.id, False),
        (author.id, sender.id, kind, post.id, contest.id, False),
    ]


@pytest.mark.parametrize("kind", ("comment", "like"))
def test_notification_creation_failure_keeps_existing_error_boundary(
    client, user_factory, contest_factory, login, fixed_time, monkeypatch, kind
):
    author = user_factory("author")
    sender = user_factory("sender")
    contest = contest_factory(NOW - timedelta(hours=2), NOW - timedelta(hours=1), NOW,
                              scoring_method="judge")
    post = make_post(contest, author)
    login(sender)
    fixed_time(NOW)
    events = observe_writes(monkeypatch)
    original_add = db.session.add

    def reject_notification(instance, **kwargs):
        if isinstance(instance, Notification):
            events.append("notification failure")
            raise RuntimeError("notification failure")
        return original_add(instance, **kwargs)

    monkeypatch.setattr(db.session, "add", reject_notification)
    if kind == "comment":
        with pytest.raises(RuntimeError, match="notification failure"):
            client.post(f"/api/posts/{post.id}/comments", json={"content": "Comment"})
        assert events == ["Comment", "notification failure"]
        # The route itself does not roll back; discard pending fixture writes here.
        db.session.rollback()
    else:
        response = client.put(f"/api/posts/{post.id}/like")
        assert response.status_code == 500
        assert response.get_json() == {"error": "いいね処理中にエラーが発生しました。"}
        assert events == ["Vote", "notification failure", "rollback"]
    assert Notification.query.count() == Comment.query.count() == Vote.query.count() == 0
    assert db.session.get(Post, post.id).comment_count == 0


@pytest.mark.parametrize("length", (0, 40, 41))
def test_notification_previews_read_current_content_and_missing_comments(
    client, user_factory, contest_factory, login, length
):
    recipient = user_factory("recipient")
    sender = user_factory("sender")
    other_sender = user_factory("other_sender")
    contest = contest_factory(NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2))
    post = make_post(contest, recipient, "p" * length)
    comment = Comment(post_id=post.id, user_id=sender.id, content="old", created_at=NOW)
    notification = Notification(user_id=recipient.id, sender_id=sender.id, type="comment",
                                post_id=post.id, contest_id=contest.id, created_at=NOW)
    db.session.add_all([comment, notification, Comment(post_id=post.id, user_id=other_sender.id,
                                                     content="other", created_at=NOW + timedelta(seconds=1))])
    db.session.commit()
    comment.content = "c" * length
    db.session.commit()
    login(recipient)
    data = client.get("/api/notifications").get_json()
    assert len(data) == 1
    assert data[0]["post"] == {"content": "p" * min(length, 40) + ("..." if length > 40 else "")}
    assert data[0]["comment"] == {"content": "c" * min(length, 40) + ("..." if length > 40 else "")}
    db.session.delete(comment)
    db.session.commit()
    data = client.get("/api/notifications").get_json()
    assert data[0]["comment"] == {"content": None}
    assert data[0]["id"] == notification.id


def test_notification_listing_has_no_limit_and_does_not_write(
    client, user_factory, login, monkeypatch
):
    recipient = user_factory("recipient")
    other = user_factory("other")
    notifications = [Notification(user_id=recipient.id, type="like", is_read=i % 2 == 0,
                                  created_at=NOW + timedelta(seconds=i)) for i in range(105)]
    db.session.add_all(notifications + [Notification(user_id=other.id, type="like")])
    db.session.commit()
    expected_ids = [n.id for n in reversed(notifications)]
    login(recipient)
    events = observe_writes(monkeypatch)
    response = client.get("/api/notifications")
    assert response.status_code == 200
    assert [n["id"] for n in response.get_json()] == expected_ids
    assert client.get("/api/notifications/unread-count").get_json() == {"unread_count": 52}
    assert events == []
    assert Notification.query.count() == 106


@pytest.mark.parametrize("empty", (False, True))
def test_mark_read_commits_once_even_when_no_unread_rows(
    client, user_factory, login, monkeypatch, empty
):
    recipient = user_factory("recipient")
    other = user_factory("other")
    if not empty:
        db.session.add_all([
            Notification(user_id=recipient.id, type="like", is_read=False),
            Notification(user_id=recipient.id, type="like", is_read=True),
            Notification(user_id=other.id, type="like", is_read=False),
        ])
        db.session.commit()
    login(recipient)
    events = observe_writes(monkeypatch)
    for _ in range(2):
        events.clear()
        response = client.post("/api/notifications/read")
        assert response.status_code == 200
        assert response.get_json() == {"message": "All notifications marked as read"}
        assert events == ["commit"]
    assert Notification.query.filter_by(user_id=recipient.id, is_read=False).count() == 0
    assert Notification.query.filter_by(user_id=other.id, is_read=False).count() == (0 if empty else 1)


def test_mark_read_commit_failure_propagates_without_route_rollback(
    client, user_factory, login, monkeypatch
):
    recipient = user_factory("recipient")
    notification = Notification(user_id=recipient.id, type="like")
    db.session.add(notification)
    db.session.commit()
    notification_id = notification.id
    login(recipient)
    events = observe_writes(monkeypatch)

    def fail_commit():
        events.append("commit failure")
        raise RuntimeError("commit failure")

    monkeypatch.setattr(db.session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="commit failure"):
        client.post("/api/notifications/read")
    assert events == ["commit failure"]
    db.session.rollback()
    assert db.session.get(Notification, notification_id).is_read is False


def test_stats_all_ranking_priorities_and_name_tiebreak_order(
    runner, user_factory, contest_factory, monkeypatch
):
    gp = contest_factory(NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2), type="grandprix")
    daily = contest_factory(NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2), type="daily")
    other = contest_factory(NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2), type="other")
    # Insert in reverse rank/name order so database order cannot supply the expected order.
    beta = user_factory("beta")
    alpha = user_factory("alpha")
    users = [user_factory(f"priority-{i}") for i in reversed(range(7))]
    users.reverse()
    for i, user in enumerate(users):
        contest = gp if i < 3 else other if i == 3 else daily
        rank = i + 1 if i < 3 else 4 if i == 3 else i - 3
        post = make_post(contest, user)
        db.session.add(ContestResult(contest_id=contest.id, post_id=post.id, user_id=user.id,
                                    rank=rank, score=-1000, is_judge_award=i == 3))
    db.session.commit()
    added_users = []
    original_add = db.session.add

    def add(instance, **kwargs):
        if isinstance(instance, UserStats):
            added_users.append(instance.user_id)
        return original_add(instance, **kwargs)

    monkeypatch.setattr(db.session, "add", add)
    result = runner.invoke(args=["update-user-stats"])
    assert result.exit_code == 0, result.output
    assert added_users == [u.id for u in users] + [alpha.id, beta.id]
    stats = {s.user_id: s for s in UserStats.query.all()}
    for i, user in enumerate(users):
        assert stats[user.id].rank == i + 1
        assert tuple(getattr(stats[user.id], field) for field in FIELDS) == tuple(int(j == i) for j in range(7))
    assert stats[alpha.id].rank == stats[beta.id].rank == 8


def test_stats_count_result_rows_and_reset_existing_stats_after_removal(
    runner, user_factory, contest_factory
):
    user = user_factory("author")
    gp = contest_factory(NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2), type="grandprix")
    post = make_post(gp, user)
    # Multiple rows are counted even for the same post; rank outside top three still counts awards.
    db.session.add_all([
        ContestResult(contest_id=gp.id, post_id=post.id, user_id=user.id, rank=1, score=0),
        ContestResult(contest_id=gp.id, post_id=post.id, user_id=user.id, rank=1, score=9000),
        ContestResult(contest_id=gp.id, post_id=post.id, user_id=user.id, rank=4, is_judge_award=True),
    ])
    db.session.commit()
    assert runner.invoke(args=["update-user-stats"]).exit_code == 0
    stats = UserStats.query.one()
    stats_id = stats.id
    assert (stats.rank, stats.gp_1st, stats.judge_awards) == (1, 2, 1)
    ContestResult.query.delete()
    db.session.commit()
    assert runner.invoke(args=["update-user-stats"]).exit_code == 0
    stats = UserStats.query.one()
    assert stats.id == stats_id
    assert stats.rank == 1
    assert tuple(getattr(stats, field) for field in FIELDS) == (0,) * 7


def test_stats_commit_failure_propagates_without_completion_or_rollback(
    runner, user_factory, monkeypatch
):
    user_factory("author")
    events = observe_writes(monkeypatch)

    def fail_commit():
        events.append("commit failure")
        raise RuntimeError("commit failure")

    monkeypatch.setattr(db.session, "commit", fail_commit)
    result = runner.invoke(args=["update-user-stats"])
    assert result.exit_code == 1
    assert isinstance(result.exception, RuntimeError)
    assert str(result.exception) == "commit failure"
    assert result.output == "--- update-user-stats batch started ---\n"
    assert events == ["UserStats", "commit failure"]
    db.session.rollback()
    assert UserStats.query.count() == 0
