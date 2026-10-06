"""URLs supplied by a client are not proof of image ownership (Refs #71)."""

from datetime import datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import Mock

import pytest
import app as app_module
from app.models import Post, db


@pytest.fixture
def images(client, user_factory, contest_factory, login, fixed_time, monkeypatch):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    contest = contest_factory(now, now + timedelta(hours=1), now + timedelta(hours=2))
    owner, other = user_factory("owner"), user_factory("other")
    posts = [Post(contest_id=contest.id, user_id=u.id, content="Entry") for u in (owner, other)]
    for p, url in zip(posts, ("https://r2.example/own.png", "https://r2.example/other.png")):
        p.images = [url]
    db.session.add_all(posts)
    db.session.commit()
    login(owner)
    fixed_time(now)
    save, delete = Mock(return_value="https://r2.example/new.png"), Mock()
    monkeypatch.setattr(app_module, "save_file", save)
    monkeypatch.setattr(app_module, "delete_file", delete)
    return posts[0], posts[1], save, delete, f"/api/contests/{contest.id}/posts/{posts[0].id}"


@pytest.mark.parametrize("value", ["foreign", "arbitrary", "string", "dict", "null", "number", "element", "duplicate"])
def test_invalid_kept_images_are_rejected_before_side_effects(client, images, value):
    post, foreign, save, delete, path = images
    kept = {"foreign": foreign.images, "arbitrary": ["https://untrusted.example/other.png"],
            "string": post.images[0], "dict": {"url": post.images[0]}, "null": None,
            "number": 3, "element": [None], "duplicate": post.images * 2}[value]
    before = post.images
    response = client.put(path, json={"content": "Edited", "kept_images": kept})
    assert response.status_code == 400
    assert post.images == before and post.content == "Entry"
    save.assert_not_called()
    delete.assert_not_called()


@pytest.mark.parametrize("method", ["put", "delete"])
@pytest.mark.parametrize("shared", [False, True])
def test_legacy_unverified_or_foreign_images_are_never_deleted(client, images, method, shared):
    post, foreign, save, delete, path = images
    post.images = foreign.images if shared else ["https://r2.example/arbitrary-existing.png"]
    db.session.commit()
    response = getattr(client, method)(path, json={"content": "Edited", "kept_images": []})
    assert response.status_code == 200
    delete.assert_not_called()
    assert foreign.images == ["https://r2.example/other.png"]


def test_new_uploads_keep_their_ownership_through_edit_and_delete(client, images):
    post, _, save, delete, path = images
    response = client.put(path, data={"content": "New", "kept_images": "[]",
                                     "images": (BytesIO(b"image"), "new.png")})
    assert response.status_code == 200
    new = response.get_json()["images"]
    assert post.owned_images == new
    delete.assert_not_called()  # Legacy own.png has no trusted provenance.
    assert client.put(path, json={"content": "Kept", "kept_images": new}).status_code == 200
    assert client.delete(path).status_code == 200
    delete.assert_called_once_with(new[0])
