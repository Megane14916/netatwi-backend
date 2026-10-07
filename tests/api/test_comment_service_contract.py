"""Comment behavior captured before the issue #43 service extraction."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event

from app.extensions import db
from app.models import Comment, Notification, Post
from app.services import notifications


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


@pytest.fixture
def comment_case(user_factory, contest_factory):
    author = user_factory("author")
    owner = user_factory("owner")
    contest = contest_factory(NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2))
    post = Post(contest_id=contest.id, user_id=author.id, content="Entry")
    db.session.add(post)
    db.session.commit()
    return post, owner, contest


def observe_mutations(monkeypatch):
    events = []
    for name in ("add", "delete", "commit", "rollback"):
        original = getattr(db.session, name)

        def record(*args, _name=name, _original=original, **kwargs):
            if _name in ("add", "delete"):
                events.append(f"{_name} {type(args[0]).__name__}")
            else:
                events.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(db.session, name, record)
    return events


def test_comment_lists_preserve_complete_payload_order_and_empty_groups(
    client, comment_case, user_factory, monkeypatch
):
    post, owner, contest = comment_case
    other = user_factory("other")
    owner.name, owner.profile_image_url = "表示名", "https://image.example/owner.png"
    empty_post = Post(contest_id=contest.id, user_id=other.id, content="Empty")
    late = Comment(user_id=owner.id, post_id=post.id, content=" late ", is_judge=True,
                   created_at=NOW + timedelta(seconds=2), updated_at=NOW + timedelta(days=1))
    early = Comment(user_id=other.id, post_id=post.id, content="early", is_judge=False,
                    created_at=NOW, updated_at=NOW + timedelta(seconds=1))
    db.session.add_all([empty_post, late, early])
    db.session.commit()
    expected = [
        {"id": early.id, "user_id": other.id, "post_id": post.id, "content": "early",
         "is_judge": False, "created_at": "2026-01-01T21:00:00+09:00",
         "updated_at": "2026-01-01T21:00:01+09:00",
         "user": {"name": "other", "screen_name": "other", "profile_image_url": None}},
        {"id": late.id, "user_id": owner.id, "post_id": post.id, "content": " late ",
         "is_judge": True, "created_at": "2026-01-01T21:00:02+09:00",
         "updated_at": "2026-01-02T21:00:00+09:00",
         "user": {"name": "表示名", "screen_name": "owner",
                  "profile_image_url": "https://image.example/owner.png"}},
    ]
    writes = observe_mutations(monkeypatch)
    listed = client.get(f"/api/posts/{post.id}/comments")
    grouped = client.get(f"/api/comments?postIds={post.id},{empty_post.id},999,{post.id}")
    assert listed.status_code == grouped.status_code == 200
    assert listed.get_json() == expected
    assert grouped.get_json() == {str(post.id): expected}
    assert client.get(f"/api/posts/{empty_post.id}/comments").get_json() == []
    assert writes == []


@pytest.mark.parametrize("query, status, payload", [
    ("", 200, {}), ("?postIds=", 200, {}), ("?postIds=999", 200, {}),
    ("?postIds=1,", 400, {"error": "Invalid postIds format"}),
    ("?postIds=1,no", 400, {"error": "Invalid postIds format"}),
])
def test_multiple_comment_input_contract(client, monkeypatch, query, status, payload):
    writes = observe_mutations(monkeypatch)
    response = client.get("/api/comments" + query)
    assert response.status_code == status
    assert response.get_json() == payload
    assert writes == []


@pytest.mark.parametrize("judge, content, status", [
    (False, "", 400), (False, " \n\t ", 400), (True, " \n\t ", 400),
    (False, "x" * 140, 201), (False, "x" * 141, 400),
    (True, "x" * 141, 201), (False, " あ😀\r\n ", 201),
])
def test_add_comment_raw_content_and_judge_boundary(
    client, comment_case, login, fixed_time, monkeypatch, judge, content, status
):
    post, owner, contest = comment_case
    login(owner, judge_contests=[contest.id] if judge else [contest.id + 1])
    fixed_time(NOW)
    writes = observe_mutations(monkeypatch)
    response = client.post(f"/api/posts/{post.id}/comments", json={"content": content})
    assert response.status_code == status
    if status == 201:
        comment = Comment.query.one()
        assert response.get_json() == {"message": "Comment added successfully", "id": comment.id}
        assert (comment.content, comment.is_judge) == (content, judge)
        assert writes == ["add Comment", "commit"]
    else:
        assert response.get_json() == {"error": "Comment must be between 1 and 140 characters"}
        assert Comment.query.count() == 0
        assert writes == []
    assert db.session.get(Post, post.id).comment_count == int(status == 201)
    assert Notification.query.count() == 0


def test_duplicate_validates_length_first_and_does_not_write(
    client, comment_case, login, fixed_time, monkeypatch
):
    post, owner, _ = comment_case
    login(owner)
    fixed_time(NOW)
    path = f"/api/posts/{post.id}/comments"
    assert client.post(path, json={"content": "First"}).status_code == 201
    writes = observe_mutations(monkeypatch)
    assert client.post(path, json={"content": ""}).status_code == 400
    repeated = client.post(path, json={"content": "Second"})
    assert repeated.status_code == 409
    assert repeated.get_json() == {"error": "You have already commented on this post"}
    assert writes == []
    assert Comment.query.one().content == "First"
    assert db.session.get(Post, post.id).comment_count == 1


@pytest.mark.parametrize("offset, notified", [
    (timedelta(microseconds=-1), False),
    (timedelta(hours=1, microseconds=-1), False),
    (timedelta(hours=1), False),
    (timedelta(hours=2, microseconds=-1), False),
    (timedelta(hours=2), True),
    (timedelta(days=1), True),
])
def test_comment_is_allowed_across_periods_and_notification_starts_at_result(
    client, comment_case, login, fixed_time, monkeypatch, offset, notified
):
    post, owner, contest = comment_case
    login(owner)
    fixed_time(NOW + offset)
    writes = observe_mutations(monkeypatch)
    response = client.post(f"/api/posts/{post.id}/comments", json={"content": "Comment"})
    assert response.status_code == 201
    assert writes == (["add Comment", "add Notification", "commit"] if notified
                      else ["add Comment", "commit"])
    assert post.comment_count == 1
    assert Notification.query.count() == int(notified)
    if notified:
        notification = Notification.query.one()
        assert (notification.user_id, notification.sender_id, notification.post_id,
                notification.contest_id, notification.type) == (
            post.user_id, owner.id, post.id, contest.id, "comment",
        )


@pytest.mark.parametrize("stored_judge, session_judge, status", [
    (True, False, 200), (False, True, 400),
])
def test_edit_uses_stored_judge_flag_and_keeps_content_and_counters(
    client, comment_case, login, monkeypatch, stored_judge, session_judge, status
):
    post, owner, contest = comment_case
    comment = Comment(user_id=owner.id, post_id=post.id, content="Original", is_judge=stored_judge)
    post.comment_count = 7
    db.session.add(comment)
    db.session.commit()
    login(owner, judge_contests=[contest.id] if session_judge else [])
    writes = observe_mutations(monkeypatch)
    content = " " + "x" * 141 + "\r\n"
    response = client.put(f"/api/comments/{comment.id}", json={"content": content})
    assert response.status_code == status
    assert response.get_json() == ({"message": "Comment updated"} if status == 200
                                   else {"error": "Invalid content length"})
    db.session.expire_all()
    assert comment.content == (content if status == 200 else "Original")
    assert comment.is_judge == stored_judge
    assert post.comment_count == 7
    assert Notification.query.count() == 0
    assert writes == (["commit"] if status == 200 else [])


@pytest.mark.parametrize("method", ("POST", "PUT", "DELETE"))
def test_auth_and_lookup_precede_json_input(client, comment_case, login, monkeypatch, method):
    post, owner, _ = comment_case
    path = f"/api/posts/{post.id}/comments" if method == "POST" else "/api/comments/999"
    writes = observe_mutations(monkeypatch)
    response = client.open(path, method=method, data="{", content_type="application/json")
    assert response.status_code == 401
    assert response.get_json() == {"error": "Unauthorized"}
    login(owner)
    missing = "/api/posts/999/comments" if method == "POST" else "/api/comments/999"
    response = client.open(missing, method=method, data="{", content_type="application/json")
    assert response.status_code == 404
    assert writes == []


def test_edit_owner_check_precedes_bad_json(client, comment_case, login, user_factory, monkeypatch):
    post, owner, _ = comment_case
    comment = Comment(user_id=owner.id, post_id=post.id, content="Original")
    db.session.add(comment)
    db.session.commit()
    login(user_factory("stranger"))
    writes = observe_mutations(monkeypatch)
    for method in ("PUT", "DELETE"):
        response = client.open(f"/api/comments/{comment.id}", method=method,
                               data="{", content_type="application/json")
        assert response.status_code == 403
        assert response.get_json() == {"error": "Forbidden"}
    assert writes == []
    assert Comment.query.one().content == "Original"


@pytest.mark.parametrize("method", ("POST", "PUT"))
@pytest.mark.parametrize("body, exception", [(None, AttributeError), ([], AttributeError),
                                           ({"content": None}, AttributeError),
                                           ({"content": 123}, AttributeError)])
def test_invalid_json_shapes_return_400_without_writes(
    client, comment_case, login, monkeypatch, method, body, exception
):
    post, owner, _ = comment_case
    comment = Comment(user_id=owner.id, post_id=post.id, content="Original")
    db.session.add(comment)
    db.session.commit()
    login(owner)
    path = f"/api/posts/{post.id}/comments" if method == "POST" else f"/api/comments/{comment.id}"
    writes = observe_mutations(monkeypatch)
    # json=None would omit the JSON body in Flask's test client.
    import json

    response = client.open(path, method=method, data=json.dumps(body), content_type="application/json")
    assert response.status_code == 400
    assert "error" in response.get_json()
    assert writes == []


def test_add_and_delete_preserve_counter_notification_and_commit_order(
    client, comment_case, login, fixed_time, monkeypatch
):
    post, owner, _ = comment_case
    login(owner)
    fixed_time(NOW + timedelta(hours=2))
    writes = observe_mutations(monkeypatch)
    original_notify = notifications.create_comment_notification

    def notify(*args):
        assert Comment.query.filter_by(post_id=post.id, user_id=owner.id).count() == 1
        assert db.session.get(Post, post.id).comment_count == 1
        writes.append("notify")
        return original_notify(*args)

    def observe_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.startswith("UPDATE post SET comment_count="):
            writes.append("counter update")

    monkeypatch.setattr(notifications, "create_comment_notification", notify)
    event.listen(db.engine, "before_cursor_execute", observe_sql)
    try:
        response = client.post(f"/api/posts/{post.id}/comments", json={"content": "Comment"})
        assert response.status_code == 201
        assert writes == ["add Comment", "counter update", "notify", "add Notification", "commit"]
        comment_id = response.get_json()["id"]
        writes.clear()
        response = client.delete(f"/api/comments/{comment_id}", data="{", content_type="application/json")
        assert response.get_json() == {"message": "Comment deleted"}
        assert writes == ["delete Comment", "counter update", "commit"]
        writes.clear()
        assert client.delete(f"/api/comments/{comment_id}").status_code == 404
        assert writes == []
    finally:
        event.remove(db.engine, "before_cursor_execute", observe_sql)
    assert Comment.query.count() == 0
    assert post.comment_count == 0
    assert Notification.query.count() == 1


def test_delete_keeps_existing_negative_counter_behavior(client, comment_case, login):
    post, owner, _ = comment_case
    comment = Comment(user_id=owner.id, post_id=post.id, content="Original")
    db.session.add(comment)
    db.session.commit()
    login(owner)
    response = client.delete(f"/api/comments/{comment.id}")
    assert response.status_code == 200
    assert post.comment_count == -1


@pytest.mark.parametrize("method", ("POST", "PUT", "DELETE"))
def test_commit_failure_propagates_without_added_rollback(
    client, comment_case, login, fixed_time, monkeypatch, method
):
    post, owner, _ = comment_case
    if method != "POST":
        comment = Comment(user_id=owner.id, post_id=post.id, content="Original")
        post.comment_count = 1
        db.session.add(comment)
        db.session.commit()
        path = f"/api/comments/{comment.id}"
    else:
        path = f"/api/posts/{post.id}/comments"
    login(owner)
    fixed_time(NOW)
    writes = observe_mutations(monkeypatch)

    def fail_commit():
        writes.append("commit failure")
        raise RuntimeError("commit failure")

    monkeypatch.setattr(db.session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="commit failure"):
        client.open(path, method=method, json={"content": "Changed"})
    assert writes == (["add Comment", "commit failure"] if method == "POST"
                      else ["delete Comment", "commit failure"] if method == "DELETE"
                      else ["commit failure"])
    db.session.rollback()
    assert Comment.query.count() == (0 if method == "POST" else 1)
    assert post.comment_count == (0 if method == "POST" else 1)
    if method != "POST":
        assert Comment.query.one().content == "Original"
