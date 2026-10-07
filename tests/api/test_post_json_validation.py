import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from app.extensions import db
from app.models import Post
from app.integrations import images


@pytest.mark.parametrize("body", ["null", "[]", "true", "42", '"text"', "{", ""])
def test_post_edit_invalid_json_has_no_side_effects(client, user_factory, contest_factory, login, fixed_time, monkeypatch, body):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fixed_time(now)
    author = user_factory("author")
    contest = contest_factory(now, now + timedelta(hours=1), now + timedelta(hours=2))
    post = Post(user_id=author.id, contest_id=contest.id, content="Original")
    post.images = ["/original.png"]
    db.session.add(post)
    db.session.commit()
    login(author)
    save, delete = Mock(), Mock()
    monkeypatch.setattr(images, "save_file", save)
    monkeypatch.setattr(images, "delete_file", delete)
    response = client.put(f"/api/contests/{contest.id}/posts/{post.id}", data=body, content_type="application/json")
    assert response.status_code == 400
    assert response.get_json() == {"error": "Expected a JSON object"}
    assert post.content == "Original" and post.images == ["/original.png"]
    save.assert_not_called()
    delete.assert_not_called()
