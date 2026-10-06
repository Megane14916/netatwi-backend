"""Deletion must work with real FK constraints and retain unrelated data (Refs #27)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import Bookmark, Comment, Contest, ContestResult, Notification, Post, Vote, db


@pytest.mark.parametrize("kind", ["contest", "post"])
@pytest.mark.parametrize("fail_commit", [False, True])
@pytest.mark.parametrize("loaded", [False, True])
def test_related_deletion_with_foreign_keys_and_rollback(
    client, user_factory, contest_factory, login, fixed_time, monkeypatch, kind, fail_commit, loaded
):
    db.session.execute(db.text("PRAGMA foreign_keys=ON"))
    assert db.session.execute(db.text("PRAGMA foreign_keys")).scalar() == 1
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = user_factory("test_admin")
    contest = contest_factory(now, now + timedelta(hours=1), now + timedelta(hours=2), post_count=1)
    child = contest_factory(now, now, now, parent_contest_id=contest.id)
    other = contest_factory(now, now, now)
    post = Post(user_id=user.id, contest_id=contest.id, content="Delete")
    other_post = Post(user_id=user.id, contest_id=other.id, content="Retain")
    db.session.add_all([post, other_post])
    db.session.flush()
    for p in (post, other_post):
        db.session.add_all([
            Vote(user_id=user.id, contest_id=p.contest_id, post_id=p.id, count=1),
            Bookmark(user_id=user.id, post_id=p.id),
            Comment(user_id=user.id, post_id=p.id, content="Comment"),
            ContestResult(user_id=user.id, contest_id=p.contest_id, post_id=p.id, rank=1),
            Notification(user_id=user.id, contest_id=p.contest_id, post_id=p.id, type="like"),
        ])
    db.session.add(Notification(user_id=user.id, contest_id=contest.id, type="contest_post_start"))
    db.session.commit()
    contest_id, post_id, child_id = contest.id, post.id, child.id
    if loaded:
        list(contest.posts), list(contest.children), list(contest.results), list(contest.notifications)
        list(post.votes), list(post.comments), list(post.bookmarks), list(post.results), list(post.notifications)
    login(user)
    fixed_time(now)
    before = {m: m.query.count() for m in (Contest, Post, Vote, Bookmark, Comment, ContestResult, Notification)}
    if fail_commit:
        monkeypatch.setattr(db.session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit failed")))
    path = f"/api/admin/contests/{contest_id}" if kind == "contest" else f"/api/contests/{contest_id}/posts/{post_id}"
    response = client.delete(path)
    assert response.status_code == (500 if fail_commit else 200)
    db.session.expire_all()
    if fail_commit:
        assert {m: m.query.count() for m in before} == before
        assert db.session.get(Contest, child_id).parent_contest_id == contest_id
    else:
        assert db.session.get(Post, post_id) is None
        for m in (Post, Vote, Bookmark, Comment, ContestResult):
            assert m.query.count() == 1
        assert Notification.query.count() == (1 if kind == "contest" else 2)
        assert db.session.get(Contest, child_id).parent_contest_id == (None if kind == "contest" else contest_id)
        assert db.session.get(Contest, contest_id) is None if kind == "contest" else db.session.get(Contest, contest_id).post_count == 0
    assert db.session.execute(db.text("PRAGMA foreign_key_check")).all() == []
