from datetime import datetime, timedelta, timezone
import pytest
from unittest.mock import Mock

from app.extensions import db
from app.models import Comment, Notification, Post
from app.services import comments


@pytest.mark.parametrize("method, path, body", [
    ("GET", "/api/contests/999", None), ("GET", "/api/contests/999/posts", None),
    ("GET", "/api/contests/999/results", None), ("POST", "/api/contests/999/posts", {"content": "Entry"}),
    ("POST", "/api/contests/999/vote", {"votes": {}}),
    ("PUT", "/api/posts/999/like", None), ("POST", "/api/contests/999/judge/login", {"password": "secret"}),
])
def test_not_found_is_json_404(client, user_factory, login, method, path, body):
    login(user_factory("member"))
    if path.endswith("/posts") and method == "POST":
        response = client.post(path, data=body)
    else:
        response = client.open(path, method=method, json=body)
    assert response.status_code == 404
    assert response.get_json() == {"error": "Not Found"}


def test_unhandled_comment_failure_is_json_500_with_safe_context(client, user_factory, contest_factory, login, monkeypatch, caplog, capsys):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    author, viewer = user_factory("author"), user_factory("viewer")
    contest = contest_factory(now, now + timedelta(hours=1), now + timedelta(hours=2))
    post = Post(user_id=author.id, contest_id=contest.id, content="Entry")
    db.session.add(post)
    db.session.commit()
    login(viewer)
    monkeypatch.setattr(comments, "add_comment", Mock(side_effect=RuntimeError("secret-token session-cookie oauth-code private-key")))
    response = client.post(f"/api/posts/{post.id}/comments", json={"content": "Comment"})
    assert response.status_code == 500
    assert response.get_json() == {"error": "Internal server error"}
    assert Comment.query.count() == Notification.query.count() == 0
    assert "comments.add_comment" in caplog.text and "RuntimeError" in caplog.text
    output = capsys.readouterr()
    for value in ("secret-token", "session-cookie", "oauth-code", "private-key"):
        assert value not in caplog.text + output.out + output.err
