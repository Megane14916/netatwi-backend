"""Characterize CRUD validation and image/DB ordering before service extraction."""

from app.integrations import images

from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from sqlalchemy import event

import app as app_module
from app.extensions import db
from app.models import Bookmark, Comment, Contest, ContestResult, Notification, Post, Vote


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


@pytest.fixture
def entry(client, user_factory, contest_factory, login, fixed_time):
    contest = contest_factory(NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2))
    author = user_factory("author")
    login(author)
    fixed_time(NOW)
    return contest, author, f"/api/contests/{contest.id}/posts"


def add_post(contest, author, images=()):
    post = Post(contest_id=contest.id, user_id=author.id, content="Original")
    post.images = list(images)
    post.record_image_uploads(list(images))
    db.session.add(post)
    db.session.commit()
    return post


@pytest.mark.parametrize("method", ["post", "put", "delete"])
def test_crud_login_precedes_input_validation(client, method):
    path = "/api/contests/999/posts" + ("/999" if method != "post" else "")
    response = getattr(client, method)(path)
    assert response.status_code == 401
    assert response.get_json() == {"error": "Login required"}


@pytest.mark.parametrize("data,error", [({}, "Content or images required"),
    ({"content": "text", "images": [(BytesIO(b"x"), f"{i}.png") for i in range(5)]},
     "Max 4 images allowed")])
def test_create_validation_precedes_missing_contest(client, entry, data, error):
    response = client.post("/api/contests/999/posts", data=data)
    assert response.status_code == 400
    assert response.get_json() == {"error": error}


def test_missing_contest_is_json_404(client, entry):
    response = client.post("/api/contests/999/posts", data={"content": "text"})
    assert response.status_code == 404
    assert response.get_json() == {"error": "Not Found"}


@pytest.mark.parametrize("rule,filename,expected", [
    ("required", None, 400), ("required", "bad.txt", 400),
    ("forbidden", "good.PNG", 201),
])
def test_image_rule_and_extension_behavior(client, entry, fake_r2, rule, filename, expected):
    contest, _, path = entry
    contest.image_rule = rule
    db.session.commit()
    data = {"content": "text\r\nend"}
    if filename:
        data["images"] = (BytesIO(b"image"), filename)
    response = client.post(path, data=data)
    assert response.status_code == expected
    if expected == 400:
        assert response.get_json() == {"error": "Unsupported image extension" if filename else "画像を最低1枚添付してください"}
    else:
        assert response.get_json()["content"] == data["content"]
        assert len(response.get_json()["images"]) == (filename == "good.PNG")
    assert fake_r2.upload_fileobj.call_count == (filename == "good.PNG")


@pytest.mark.parametrize("advanced", [False, True])
def test_qualifier_result_checked_before_upload(client, entry, contest_factory, fake_r2, advanced):
    contest, author, path = entry
    qualifier = contest_factory(NOW - timedelta(days=2), NOW - timedelta(days=1), NOW)
    contest.parent_contest_id = qualifier.id
    qualifier_post = add_post(qualifier, author)
    db.session.add(ContestResult(contest_id=qualifier.id, post_id=qualifier_post.id,
                                user_id=author.id, score=1, rank=1, is_advanced=advanced))
    db.session.commit()
    response = client.post(path, data={"images": (BytesIO(b"image"), "good.png")})
    assert response.status_code == (201 if advanced else 403)
    if not advanced:
        assert response.get_json() == {"error": "予選を通過していないため、この大会には投稿できません"}
    assert fake_r2.upload_fileobj.call_count == advanced


def test_required_image_precedes_duplicate_and_duplicate_precedes_upload(client, entry, fake_r2):
    contest, author, path = entry
    add_post(contest, author)
    contest.image_rule = "required"
    db.session.commit()
    empty = client.post(path, data={"content": "text"})
    duplicate = client.post(path, data={"images": (BytesIO(b"image"), "good.png")})
    assert empty.status_code == 400
    assert empty.get_json() == {"error": "画像を最低1枚添付してください"}
    assert duplicate.status_code == 409
    assert duplicate.get_json() == {"error": "Already posted"}
    fake_r2.upload_fileobj.assert_not_called()


@pytest.mark.parametrize("method", ["post", "put", "delete"])
@pytest.mark.parametrize("offset,allowed", [(timedelta(microseconds=-1), False),
    (timedelta(0), True), (timedelta(hours=1), False)])
def test_all_crud_period_boundaries(client, entry, fixed_time, fake_r2, method, offset, allowed):
    contest, author, path = entry
    if method != "post":
        path += f"/{add_post(contest, author).id}"
    fixed_time(NOW + offset)
    response = getattr(client, method)(path, data={"content": "text"})
    assert response.status_code == ((201 if method == "post" else 200) if allowed else 403)
    if not allowed:
        assert response.get_json() == {"error": "Outside period"}
        fake_r2.upload_fileobj.assert_not_called()
        fake_r2.delete_object.assert_not_called()


@pytest.mark.parametrize("content,error", [("", "No content"), ("x" * 281, "Text too long (max 280)")])
def test_update_validation_precedes_ownership_query(client, entry, content, error):
    _, _, path = entry
    response = client.put(f"{path}/999", json={"content": content})
    assert response.status_code == 400
    assert response.get_json() == {"error": error}


def test_update_normalizes_text_and_allows_four_images(client, entry, fake_r2):
    contest, author, path = entry
    post = add_post(contest, author, ["https://r2.example/old.png"])
    response = client.put(f"{path}/{post.id}", data={
        "content": "a\r\nb\rc", "kept_images": "[]",
        "images": [(BytesIO(b"x"), f"{i}.png") for i in range(4)],
    })
    assert response.status_code == 200
    assert response.get_json()["content"] == "a\nb\nc"
    assert response.get_json()["myVotes"] is None
    assert len(response.get_json()["images"]) == 4
    assert fake_r2.upload_fileobj.call_count == 4
    fake_r2.delete_object.assert_called_once_with(Bucket="test-bucket", Key="old.png")


@pytest.mark.parametrize("method", ["post", "put", "delete"])
def test_commit_failure_compensates_new_uploads_and_rolls_back(
    client, entry, monkeypatch, method
):
    contest, author, path = entry
    post = None if method == "post" else add_post(contest, author, ["old.png"])
    post_id = post.id if post else None
    contest_id = contest.id
    events = []
    monkeypatch.setattr(images, "save_file", lambda file: events.append("upload") or "new.png")
    monkeypatch.setattr(images, "delete_file", lambda url: events.append("delete"))
    original_rollback = db.session.rollback

    def failed_commit():
        events.append("commit")
        raise RuntimeError("commit failed")

    def rollback():
        events.append("rollback")
        original_rollback()

    monkeypatch.setattr(db.session, "commit", failed_commit)
    monkeypatch.setattr(db.session, "rollback", rollback)
    data = {"content": "Edited", "images": (BytesIO(b"image"), "new.png")}
    response = getattr(client, method)(path + (f"/{post_id}" if post else ""), data=data)
    assert response.status_code == 500
    assert response.get_json() == {"error": "Error"}
    assert events == (["commit", "rollback"] if method == "delete" else
                      ["upload", "commit", "rollback", "delete", "rollback"])
    db.session.expire_all()
    assert db.session.get(Contest, contest_id).post_count == 0
    if post_id:
        persisted = db.session.get(Post, post_id)
        assert persisted.content == "Original"
        assert persisted.images == ["old.png"]
    else:
        assert Post.query.count() == 0


def test_delete_commits_related_rows_and_counter_before_images(client, entry, monkeypatch):
    contest, author, path = entry
    post = add_post(contest, author, ["first.png", "second.png"])
    post_id, contest_id = post.id, contest.id
    db.session.add_all([
        Vote(contest_id=contest_id, user_id=author.id, post_id=post_id, count=1),
        Comment(post_id=post_id, user_id=author.id, content="comment"),
        Notification(user_id=author.id, sender_id=author.id, type="like", post_id=post_id),
        Bookmark(post_id=post_id, user_id=author.id),
        ContestResult(contest_id=contest_id, post_id=post_id, user_id=author.id, score=1, rank=1),
    ])
    db.session.commit()
    events = []

    def delete_image(url):
        events.append(url)
        raise RuntimeError("image deletion failed")

    def record_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.startswith(("DELETE", "UPDATE")):
            events.append(statement.split()[2 if statement.startswith("DELETE") else 1])

    monkeypatch.setattr(images, "delete_file", delete_image)
    event.listen(db.engine, "before_cursor_execute", record_sql)
    try:
        response = client.delete(f"{path}/{post_id}")
    finally:
        event.remove(db.engine, "before_cursor_execute", record_sql)
    assert response.status_code == 200
    assert response.get_json() == {"message": "Deleted successfully"}
    assert events == ["vote", "comment", "notification", "bookmark", "contest_result",
                      "post", "contest", "first.png", "second.png"]
    for model in (Vote, Comment, Notification, Bookmark, ContestResult, Post):
        assert model.query.count() == 0
    assert db.session.get(Contest, contest_id).post_count == 0


def test_r2_upload_and_delete_errors_propagate_for_compensation(entry, fake_r2):
    from werkzeug.datastructures import FileStorage

    fake_r2.upload_fileobj.side_effect = RuntimeError("upload failed")
    fake_r2.delete_object.side_effect = RuntimeError("delete failed")
    with pytest.raises(RuntimeError, match="upload failed"):
        images.save_file(FileStorage(stream=BytesIO(b"image"), filename="image.png"))
    with pytest.raises(RuntimeError, match="delete failed"):
        images.delete_file("https://r2.example/old.png?query=1")
    fake_r2.delete_object.assert_called_once_with(Bucket="test-bucket", Key="old.png")
