"""A signed session does not keep a withdrawn account active (Refs #72)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models import Post


PROTECTED = [
    ("POST", "/api/contests/1/posts"),
    ("PUT", "/api/contests/1/posts/1"),
    ("DELETE", "/api/contests/1/posts/1"),
    ("POST", "/api/contests/1/vote"),
    ("POST", "/api/contests/1/judge/login"),
    ("POST", "/api/posts/1/comments"),
    ("PUT", "/api/comments/1"),
    ("DELETE", "/api/comments/1"),
    ("PUT", "/api/posts/1/bookmark"),
    ("DELETE", "/api/posts/1/bookmark"),
    ("PUT", "/api/posts/1/like"),
    ("DELETE", "/api/posts/1/like"),
    ("GET", "/api/notifications"),
    ("GET", "/api/notifications/unread-count"),
    ("POST", "/api/notifications/read"),
    ("POST", "/api/admin/contests"),
    ("GET", "/api/admin/contests/management"),
    ("PUT", "/api/admin/contests/1"),
    ("DELETE", "/api/admin/contests/1"),
    ("GET", "/api/admin/news"),
    ("POST", "/api/admin/news"),
    ("DELETE", "/api/admin/news/1"),
    ("DELETE", "/api/users/me"),
]


def sign_in(client, user_id):
    with client.session_transaction() as session:
        session.update(user_id=user_id, screen_name="test_admin", name="Admin",
                       judge_for_contest_ids=[1])


@pytest.mark.parametrize("state", ["deleted", "missing"])
@pytest.mark.parametrize("method,path", PROTECTED)
def test_stale_session_is_cleared_before_any_protected_action(client, user_factory, state, method, path):
    user = user_factory("test_admin")
    user_id = user.id
    if state == "deleted":
        user.deleted_at = datetime.now(timezone.utc)
        db.session.commit()
    else:
        user_id = 99999
    sign_in(client, user_id)
    before = {table.name: db.session.execute(db.select(db.func.count()).select_from(table)).scalar()
              for table in db.metadata.sorted_tables}
    response = client.open(path, method=method, json={"votes": {}, "content": "Attack", "password": "secret"})
    assert response.status_code == 401
    with client.session_transaction() as session:
        assert dict(session) == {}
    assert before == {table.name: db.session.execute(db.select(db.func.count()).select_from(table)).scalar()
                      for table in db.metadata.sorted_tables}


def test_withdrawal_invalidates_another_browser_and_me(app, user_factory, contest_factory, fixed_time):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    contest = contest_factory(now, now + timedelta(hours=1), now + timedelta(hours=2))
    user = user_factory("member")
    first, second, third = app.test_client(), app.test_client(), app.test_client()
    for client in (first, second, third):
        sign_in(client, user.id)
    fixed_time(now)
    assert first.delete("/api/users/me").status_code == 200
    assert second.post(f"/api/contests/{contest.id}/posts", data={"content": "Entry"}).status_code == 401
    assert Post.query.count() == 0
    assert third.get("/api/me").get_json() == {"logged_in": False}
    for client in (second, third):
        with client.session_transaction() as session:
            assert dict(session) == {}
