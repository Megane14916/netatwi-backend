"""Image storage failures must not leave DB references broken (Refs #26)."""

from app.integrations import images

from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from unittest.mock import Mock

import pytest
import app as app_module
from app.models import Contest, Post, db
from app.services.posts import cleanup_images, _cleanup_signer


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
    monkeypatch.setattr(images, "save_file", save)
    monkeypatch.setattr(images, "delete_file", delete)
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


def test_failed_cleanup_logs_signed_retry_and_retry_is_idempotent(app, runner, monkeypatch, caplog):
    delete = Mock(side_effect=RuntimeError("storage unavailable"))
    monkeypatch.setattr(images, "delete_file", delete)
    assert cleanup_images(["owned.png"]) == ["owned.png"]
    record = next(record.message for record in caplog.records if "IMAGE_CLEANUP_PENDING" in record.message)
    token = json.loads(record.split(" ", 1)[1])["token"]
    delete.side_effect = None
    for _ in range(2):
        result = runner.invoke(args=["retry-image-cleanup", "--token", token])
        assert result.exit_code == 0, result.output
    assert delete.call_count == 3


def test_retry_rejects_forged_token_and_retains_referenced_image(
    app, runner, user_factory, contest_factory, monkeypatch
):
    user = user_factory("owner")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    contest = contest_factory(now, now + timedelta(hours=1), now + timedelta(hours=2))
    post = Post(contest_id=contest.id, user_id=user.id, content="Saved")
    post.images = ["owned.png"]
    db.session.add(post)
    db.session.commit()
    delete = Mock()
    monkeypatch.setattr(images, "delete_file", delete)
    for token in ["forged", _cleanup_signer().dumps("owned.png")]:
        result = runner.invoke(args=["retry-image-cleanup", "--token", token])
        assert result.exit_code != 0
    delete.assert_not_called()


@pytest.mark.parametrize("method", ["post", "put"])
def test_partial_upload_error_url_is_compensated(
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
    error = RuntimeError("partial upload failed")
    error.uploaded_image_url = "partial.png"
    monkeypatch.setattr(images, "save_file", Mock(side_effect=error))
    delete = Mock()
    monkeypatch.setattr(images, "delete_file", delete)
    login(user)
    fixed_time(now)
    response = getattr(client, method)(path, data={"content": "Changed", "images": (BytesIO(b"image"), "image.png")})
    assert response.status_code == 500
    delete.assert_called_once_with("partial.png")


@pytest.mark.parametrize("use_r2", [False, True])
def test_storage_partial_failure_retains_generated_cleanup_url(app, tmp_path, use_r2):
    from app.integrations import images
    from werkzeug.datastructures import FileStorage
    file = FileStorage(stream=BytesIO(b"image"), filename="image.png")
    storage = Mock()
    storage.upload_fileobj.side_effect = RuntimeError("partial write")
    def partial_save(path):
        from pathlib import Path
        Path(path).write_bytes(b"partial")
        raise RuntimeError("partial write")
    file.save = partial_save
    settings = dict(UPLOAD_FOLDER=str(tmp_path), USE_R2=use_r2,
                    R2_BUCKET_NAME="fake-bucket", get_r2_client=lambda: storage,
                    logger=app.logger)
    with pytest.raises(RuntimeError) as raised:
        images._save_file(file, R2_PUBLIC_URL="https://fake.example", **settings)
    url = raised.value.uploaded_image_url
    assert url.startswith("https://fake.example/" if use_r2 else "/static/uploads/")
    images._delete_file(url, **settings)
    images._delete_file(url, **settings)
    if use_r2:
        assert storage.delete_object.call_count == 2
    else:
        assert list(tmp_path.iterdir()) == []


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
    monkeypatch.setattr(images, "save_file", save)
    monkeypatch.setattr(images, "delete_file", delete)
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
