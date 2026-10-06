"""Counters and file operations caused by post and vote endpoints."""

from flask import current_app
from app.integrations import images

from datetime import datetime, timedelta, timezone
from io import BytesIO

import app as app_module
from app import db
from app.models import Contest, Post, Vote


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def current_counts(contest_id):
    db.session.expire_all()
    contest = db.session.get(Contest, contest_id)
    return contest.post_count, contest.total_voters, contest.total_judges


def test_post_count_tracks_creation_duplicate_and_deletion(
    client, user_factory, contest_factory, login, fixed_time
):
    contest = contest_factory(
        NOW - timedelta(hours=1), NOW + timedelta(hours=1), NOW + timedelta(hours=2)
    )
    first_author = user_factory("first_author")
    second_author = user_factory("second_author")
    fixed_time(NOW)
    path = f"/api/contests/{contest.id}/posts"

    login(first_author)
    first = client.post(path, data={"content": "First"})
    duplicate = client.post(path, data={"content": "Again"})
    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert current_counts(contest.id) == (1, 0, 0)

    login(second_author)
    second = client.post(path, data={"content": "Second"})
    denied = client.delete(f"{path}/{first.get_json()['id']}")
    assert second.status_code == 201
    assert denied.status_code == 404
    assert current_counts(contest.id) == (2, 0, 0)

    login(first_author)
    deleted = client.delete(f"{path}/{first.get_json()['id']}")
    assert deleted.status_code == 200
    assert current_counts(contest.id) == (1, 0, 0)
    assert Post.query.filter_by(contest_id=contest.id).count() == 1


def test_vote_replacement_updates_voter_and_judge_counts(
    client, user_factory, contest_factory, login, fixed_time
):
    contest = contest_factory(
        NOW - timedelta(hours=2), NOW - timedelta(hours=1), NOW + timedelta(hours=1)
    )
    author = user_factory("author")
    voter = user_factory("voter")
    judge = user_factory("judge")
    post = Post(contest_id=contest.id, user_id=author.id, content="Entry")
    db.session.add(post)
    db.session.commit()
    fixed_time(NOW)
    path = f"/api/contests/{contest.id}/vote"

    login(voter)
    assert client.post(path, json={"votes": {str(post.id): 1}}).status_code == 200
    assert client.post(path, json={"votes": {str(post.id): 1}}).status_code == 200
    assert current_counts(contest.id) == (0, 1, 0)

    login(judge, judge_contests=[contest.id])
    assert client.post(path, json={"votes": {str(post.id): 0}}).status_code == 200
    assert current_counts(contest.id) == (0, 2, 1)
    assert Vote.query.filter_by(user_id=judge.id, contest_id=contest.id).one().count == 0

    assert client.post(path, json={"votes": {}}).status_code == 200
    assert current_counts(contest.id) == (0, 1, 0)
    login(voter)
    assert client.post(path, json={"votes": {}}).status_code == 200
    assert current_counts(contest.id) == (0, 0, 0)
    assert Vote.query.filter_by(contest_id=contest.id).count() == 0


def test_post_image_upload_edit_and_delete_use_r2_mock(
    client, user_factory, contest_factory, login, fixed_time, fake_r2
):
    contest = contest_factory(
        NOW - timedelta(hours=1), NOW + timedelta(hours=1), NOW + timedelta(hours=2)
    )
    login(user_factory("author"))
    fixed_time(NOW)
    path = f"/api/contests/{contest.id}/posts"

    created = client.post(
        path,
        data={
            "content": "Original",
            "images": [
                (BytesIO(b"first"), "first.png"),
                (BytesIO(b"second"), "second.png"),
            ],
        },
    )
    assert created.status_code == 201
    post_id = created.get_json()["id"]
    original_images = created.get_json()["images"]
    assert len(original_images) == 2
    assert all(url.startswith("https://r2.example/") for url in original_images)
    assert fake_r2.upload_fileobj.call_count == 2
    assert current_counts(contest.id) == (1, 0, 0)

    edited = client.put(
        f"{path}/{post_id}",
        data={
            "content": "Edited",
            "kept_images": f'["{original_images[0]}"]',
            "images": (BytesIO(b"third"), "third.png"),
        },
    )
    assert edited.status_code == 200
    edited_images = edited.get_json()["images"]
    assert edited_images[0] == original_images[0]
    assert len(edited_images) == 2
    assert fake_r2.upload_fileobj.call_count == 3
    assert fake_r2.delete_object.call_count == 1
    assert fake_r2.delete_object.call_args.kwargs == {
        "Bucket": "test-bucket",
        "Key": original_images[1].rsplit("/", 1)[1],
    }
    assert db.session.get(Post, post_id).images == edited_images

    deleted = client.delete(f"{path}/{post_id}")
    assert deleted.status_code == 200
    assert fake_r2.delete_object.call_count == 3
    deleted_keys = {
        call.kwargs["Key"] for call in fake_r2.delete_object.call_args_list
    }
    assert deleted_keys == {url.rsplit("/", 1)[1] for url in original_images + edited_images}
    assert db.session.get(Post, post_id) is None
    assert current_counts(contest.id) == (0, 0, 0)


def test_local_file_save_and_delete_are_confined_to_temp_folder(
    app, tmp_path, monkeypatch
):
    from werkzeug.datastructures import FileStorage

    monkeypatch.setitem(current_app.config, "USE_R2", False)
    monkeypatch.setitem(current_app.config, "UPLOAD_FOLDER", str(tmp_path))
    image = FileStorage(
        stream=BytesIO(b"local image"), filename="photo.png", content_type="image/png"
    )

    url = images.save_file(image)
    saved = tmp_path / url.rsplit("/", 1)[1]
    assert url.startswith("/static/uploads/")
    assert saved.read_bytes() == b"local image"

    images.delete_file(url)
    assert not saved.exists()
