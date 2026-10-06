"""Step 11 posting validation regressions (first part of #21)."""

from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from unittest.mock import Mock

import pytest
import app as app_module
from app.models import Post, db


@pytest.mark.parametrize("method,content,kept,new,rule", [
    ("post", "a" * 281, 0, 0, "optional"),
    ("post", "あ" * 141, 0, 0, "optional"),
    ("post", "text", 0, -1, "required"),
    ("post", "", 0, -1, "optional"),
    ("put", "text", 0, 0, "required"),
    ("put", "text", 2, 3, "optional"),
    ("put", "text", 0, 5, "optional"),
])
def test_invalid_final_post_has_no_storage_or_db_effects(
    client, contest_factory, user_factory, login, fixed_time, monkeypatch,
    method, content, kept, new, rule
):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    contest = contest_factory(now, now + timedelta(hours=1), now + timedelta(hours=2), image_rule=rule)
    user = user_factory("author")
    path = f"/api/contests/{contest.id}/posts"
    post = None
    if method == "put":
        post = Post(contest_id=contest.id, user_id=user.id, content="Original")
        post.images = [f"old{i}.png" for i in range(max(kept, 1))]
        post.record_image_uploads(post.images)
        db.session.add(post)
        db.session.commit()
        path += f"/{post.id}"
    upload, delete = Mock(side_effect=lambda file: file.filename), Mock()
    monkeypatch.setattr(app_module, "save_file", upload)
    monkeypatch.setattr(app_module, "delete_file", delete)
    login(user)
    fixed_time(now)
    data = {"content": content, "kept_images": json.dumps(post.images[:kept] if post else [])}
    if new:
        data["images"] = [(BytesIO(b"image"), "bad.txt" if new < 0 else f"new{i}.png") for i in range(abs(new))]
    response = getattr(client, method)(path, data=data)
    assert response.status_code == 400
    upload.assert_not_called()
    delete.assert_not_called()
    db.session.expire_all()
    if post:
        assert post.content == "Original" and len(post.images) == max(kept, 1)
    else:
        assert Post.query.count() == 0


@pytest.mark.parametrize("content", ["a" * 280, "あ" * 140, "a" * 257 + "https://example.com/long/path"])
def test_create_weighted_boundary_is_accepted(client, contest_factory, user_factory, login, fixed_time, content):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    contest = contest_factory(now, now + timedelta(hours=1), now + timedelta(hours=2))
    login(user_factory("author"))
    fixed_time(now)
    assert client.post(f"/api/contests/{contest.id}/posts", data={"content": content}).status_code == 201
