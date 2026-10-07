import json
from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models import Comment, Notification, Post


@pytest.fixture
def entry(user_factory, contest_factory, login):
    author, viewer = user_factory("author"), user_factory("viewer")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    contest = contest_factory(now, now + timedelta(hours=1), now + timedelta(hours=2))
    post = Post(user_id=author.id, contest_id=contest.id, content="Entry")
    comment = Comment(user_id=viewer.id, post=post, content="Original")
    db.session.add_all([post, comment])
    db.session.commit()
    login(viewer)
    return post, comment


@pytest.mark.parametrize("method", ["POST", "PUT"])
@pytest.mark.parametrize("body", [None, [], "text", 42, True, {"content": None}, {"content": []}, {"content": {}}, {"content": 123}, {"content": False}])
def test_invalid_comment_input_returns_json_400_without_mutations(client, entry, method, body):
    post, comment = entry
    path = f"/api/posts/{post.id}/comments" if method == "POST" else f"/api/comments/{comment.id}"
    response = client.open(path, method=method, data=json.dumps(body), content_type="application/json")
    assert response.status_code == 400
    assert isinstance(response.get_json()["error"], str)
    assert Comment.query.count() == 1
    assert db.session.get(Comment, comment.id).content == "Original"
    assert db.session.get(Post, post.id).comment_count == 0
    assert Notification.query.count() == 0


@pytest.mark.parametrize("body, content_type", [("{", "application/json"), ("", "application/json"), ("content=hello", "text/plain")])
def test_comment_body_parser_returns_json_error(client, entry, body, content_type):
    response = client.post(f"/api/posts/{entry[0].id}/comments", data=body, content_type=content_type)
    assert response.status_code == 400
    assert response.get_json() == {"error": "Expected a JSON object"}


@pytest.mark.parametrize("ids", ["0", "-1", str(2**31), "1.0"])
def test_grouped_comments_reject_invalid_database_ids(client, ids):
    response = client.get(f"/api/comments?postIds={ids}")
    assert response.status_code == 400
    assert response.get_json() == {"error": "Invalid postIds format"}
