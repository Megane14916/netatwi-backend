from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from app.extensions import db
from app.models import Bookmark, Comment, Notification, Post, User
from app.services import comments, notifications, users


@pytest.fixture
def mutation_case(user_factory, contest_factory):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    author, viewer = user_factory("author"), user_factory("viewer")
    contest = contest_factory(now, now + timedelta(hours=1), now + timedelta(hours=2))
    post = Post(user_id=author.id, contest_id=contest.id, content="Original")
    comment = Comment(user_id=viewer.id, post=post, content="Original")
    notice = Notification(user_id=viewer.id, type="comment", post=post)
    db.session.add_all([post, comment, notice])
    db.session.commit()
    return author.id, viewer.id, post.id, comment.id, notice.id


@pytest.mark.parametrize("operation", ["comment_add", "comment_update", "comment_delete", "notification_read", "withdraw"])
def test_failed_service_commit_rolls_back_immediately_and_can_retry(mutation_case, monkeypatch, fixed_time, operation):
    author, viewer, post_id, comment_id, notice_id = mutation_case
    fixed_time(datetime(2026, 1, 1, tzinfo=timezone.utc))
    def invoke():
        if operation == "comment_add":
            return comments.add_comment(post_id, author, db.session.get(Post, post_id), "Added", [])
        if operation == "comment_update":
            return comments.update_comment(db.session.get(Comment, comment_id), "Updated")
        if operation == "comment_delete":
            return comments.delete_comment(db.session.get(Comment, comment_id))
        if operation == "notification_read":
            return notifications.mark_notifications_read(viewer)
        return users.withdraw_user(viewer)
    original = db.session.commit
    monkeypatch.setattr(db.session, "commit", Mock(side_effect=RuntimeError("commit failure")))
    with pytest.raises(RuntimeError, match="commit failure"):
        invoke()
    # Do not issue a test-side rollback: the service must already be usable.
    assert db.session.get(Comment, comment_id).content == "Original"
    assert Comment.query.count() == 1
    assert db.session.get(Post, post_id).comment_count == 0
    assert not db.session.get(Notification, notice_id).is_read
    assert db.session.get(User, viewer).deleted_at is None
    monkeypatch.setattr(db.session, "commit", original)
    invoke()


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_bookmark_recount_failure_does_not_leave_partial_write(client, mutation_case, user_factory, login, monkeypatch, method):
    from sqlalchemy.orm import Query
    _, viewer, post_id, _, _ = mutation_case
    post = db.session.get(Post, post_id)
    if method == "DELETE":
        db.session.add(Bookmark(user_id=viewer, post_id=post_id))
        post.bookmark_count = 1
        db.session.commit()
    before = int(method == "DELETE")
    login(db.session.get(User, viewer))
    original = Query.count
    def fail(query):
        if query.column_descriptions[0]["entity"] is Bookmark:
            raise RuntimeError("recount failure")
        return original(query)
    monkeypatch.setattr(Query, "count", fail)
    response = client.open(f"/api/posts/{post_id}/bookmark", method=method)
    assert response.status_code == 500
    monkeypatch.setattr(Query, "count", original)
    assert Bookmark.query.count() == before
    assert post.bookmark_count == before
