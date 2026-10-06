"""Image storage failures must not leave DB references broken (Refs #26)."""

from datetime import datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import Mock

import pytest
import app as app_module
from app.models import Contest, Post, db


@pytest.mark.parametrize("method", ["post", "put", "delete"])
def test_db_failure_keeps_old_files_and_removes_new_uploads(
    client, contest_factory, user_factory, login, fixed_time, monkeypatch, method
):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    contest = contest_factory(now, now + timedelta(hours=1), now + timedelta(hours=2), post_count=1 if method != "post" else 0)
    user = user_factory("author")
    path = f"/api/contests/{contest.id}/posts"
    post = None
    if method != "post":
        post = Post(contest_id=contest.id, user_id=user.id, content="Original")
        post.images = ["old.png"]
        post.record_image_uploads(["old.png"])
        db.session.add(post)
        db.session.commit()
        path += f"/{post.id}"
    contest_id = contest.id
    stored = {"old.png"}
    def save(file):
        stored.add("new.png")
        return "new.png"
    def delete(url):
        stored.discard(url)
    monkeypatch.setattr(app_module, "save_file", save)
    monkeypatch.setattr(app_module, "delete_file", delete)
    monkeypatch.setattr(db.session, "commit", Mock(side_effect=RuntimeError("DB failure")))
    login(user)
    fixed_time(now)
    response = getattr(client, method)(path, data={"content": "Changed", "images": (BytesIO(b"image"), "new.png")})
    assert response.status_code == 500
    assert stored == {"old.png"}
    db.session.expire_all()
    if post:
        assert post.content == "Original" and post.images == ["old.png"]
    else:
        assert Post.query.count() == 0
    assert db.session.get(Contest, contest_id).post_count == (1 if post else 0)


@pytest.mark.parametrize("method", ["post", "put"])
def test_later_upload_failure_compensates_earlier_success(
    client, contest_factory, user_factory, login, fixed_time, monkeypatch, method
):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    contest = contest_factory(now, now + timedelta(hours=1), now + timedelta(hours=2))
    user = user_factory("author")
    path = f"/api/contests/{contest.id}/posts"
    if method == "put":
        post = Post(contest_id=contest.id, user_id=user.id, content="Original")
        db.session.add(post)
        db.session.commit()
        path += f"/{post.id}"
    save = Mock(side_effect=["first.png", RuntimeError("second upload failed")])
    delete = Mock()
    monkeypatch.setattr(app_module, "save_file", save)
    monkeypatch.setattr(app_module, "delete_file", delete)
    login(user)
    fixed_time(now)
    response = getattr(client, method)(path, data={"content": "Changed", "images": [
        (BytesIO(b"first"), "first.png"), (BytesIO(b"second"), "second.png")]})
    assert response.status_code == 500
    delete.assert_called_once_with("first.png")
    if method == "put":
        assert post.content == "Original" and post.images == []
    else:
        assert Post.query.count() == 0
