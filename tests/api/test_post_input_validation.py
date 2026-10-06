"""Step 11 posting validation regressions (first part of #21)."""

from app.integrations import images

from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from unittest.mock import Mock

import pytest
import app as app_module
from app.extensions import db
from app.models import Post


@pytest.mark.parametrize("method,content,kept,new,rule", [
    ("post", "a" * 281, 0, 0, "optional"),
    ("post", "あ" * 141, 0, 0, "optional"),
    ("post", "text", 0, -1, "required"),
    ("post", "", 0, -1, "optional"),
    ("put", "text", 0, 0, "required"),
    ("put", "text", 2, 3, "optional"),
    ("put", "text", 0, 5, "optional"),
    ("post", "text", 0, 1, "none"),
    ("put", "text", 1, 0, "none"),
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
    monkeypatch.setattr(images, "save_file", upload)
    monkeypatch.setattr(images, "delete_file", delete)
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


def test_edit_required_contest_accepts_four_final_images(client, contest_factory, user_factory, login, fixed_time, monkeypatch):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    contest = contest_factory(now, now + timedelta(hours=1), now + timedelta(hours=2), image_rule="required")
    user = user_factory("author")
    post = Post(contest_id=contest.id, user_id=user.id, content="Original")
    post.images = ["old.png"]
    db.session.add(post)
    db.session.commit()
    monkeypatch.setattr(images, "save_file", lambda file: file.filename)
    login(user)
    fixed_time(now)
    response = client.put(f"/api/contests/{contest.id}/posts/{post.id}", data={
        "content": "", "kept_images": '["old.png"]',
        "images": [(BytesIO(b"image"), f"new{i}.png") for i in range(3)]})
    assert response.status_code == 200 and len(response.get_json()["images"]) == 4


def test_storage_returning_no_image_does_not_create_empty_post(client, contest_factory, user_factory, login, fixed_time, monkeypatch):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    contest = contest_factory(now, now + timedelta(hours=1), now + timedelta(hours=2), image_rule="required")
    monkeypatch.setattr(images, "save_file", lambda file: None)
    login(user_factory("author"))
    fixed_time(now)
    response = client.post(f"/api/contests/{contest.id}/posts", data={"images": (BytesIO(b"image"), "image.png")})
    assert response.status_code == 500
    assert Post.query.count() == 0


@pytest.mark.parametrize("request_kind", ["json_missing", "json_null", "form_missing"])
@pytest.mark.parametrize("keep_image", [False, True])
@pytest.mark.parametrize("rule", ["optional", "required"])
def test_edit_without_text_accepts_images_and_rejects_empty_post(
    client, contest_factory, user_factory, login, fixed_time, monkeypatch,
    request_kind, keep_image, rule
):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    contest = contest_factory(now, now + timedelta(hours=1), now + timedelta(hours=2), image_rule=rule)
    user = user_factory("author")
    post = Post(contest_id=contest.id, user_id=user.id, content="Original")
    post.images = ["owned.png"]
    post.record_image_uploads(post.images)
    db.session.add(post)
    db.session.commit()
    upload, delete = Mock(), Mock()
    monkeypatch.setattr(images, "save_file", upload)
    monkeypatch.setattr(images, "delete_file", delete)
    login(user)
    fixed_time(now)
    kept = post.images if keep_image else []
    path = f"/api/contests/{contest.id}/posts/{post.id}"
    if request_kind == "form_missing":
        response = client.put(path, data={"kept_images": json.dumps(kept)})
    else:
        payload = {"kept_images": kept}
        if request_kind == "json_null":
            payload["content"] = None
        response = client.put(path, json=payload)

    assert response.status_code == (200 if keep_image else 400)
    upload.assert_not_called()
    delete.assert_not_called()
    db.session.expire_all()
    assert post.images == ["owned.png"]
    assert post.owned_images == ["owned.png"]
    assert post.content == ("" if keep_image else "Original")
    if keep_image:
        assert response.get_json()["content"] == ""
        assert response.get_json()["images"] == ["owned.png"]


@pytest.mark.parametrize("rule", ["optional", "required"])
def test_edit_without_text_accepts_new_image(
    client, contest_factory, user_factory, login, fixed_time, monkeypatch, rule
):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    contest = contest_factory(now, now + timedelta(hours=1), now + timedelta(hours=2), image_rule=rule)
    user = user_factory("author")
    post = Post(contest_id=contest.id, user_id=user.id, content="Original")
    db.session.add(post)
    db.session.commit()
    upload, delete = Mock(return_value="new.png"), Mock()
    monkeypatch.setattr(images, "save_file", upload)
    monkeypatch.setattr(images, "delete_file", delete)
    login(user)
    fixed_time(now)

    response = client.put(f"/api/contests/{contest.id}/posts/{post.id}", data={
        "images": (BytesIO(b"image"), "new.png"),
    })

    assert response.status_code == 200
    assert response.get_json()["content"] == ""
    upload.assert_called_once()
    delete.assert_not_called()
    db.session.expire_all()
    assert post.content == ""
    assert post.images == post.owned_images == ["new.png"]
