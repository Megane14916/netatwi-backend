"""Bookmark rows and cached counts must agree after overlapping mutations."""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event

import pytest
from sqlalchemy import select, text

from app.extensions import db
from app.models import Bookmark, Contest, Post, User
from app.services import interactions


@pytest.mark.parametrize("first_method, second_method", [
    ("PUT", "PUT"), ("PUT", "DELETE"), ("DELETE", "PUT"),
])
def test_bookmark_recount_is_serialized(postgres_app, first_method, second_method):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    users = [User(twitter_id=f"pg-{i}", screen_name=f"pg_{i}", name=f"User {i}")
             for i in range(3)]
    contest = Contest(name="Bookmarks", start_time=now,
                      end_time=now + timedelta(hours=1),
                      voting_end_time=now + timedelta(hours=2))
    db.session.add_all([*users, contest])
    db.session.flush()
    post = Post(user_id=users[0].id, contest_id=contest.id, content="Entry")
    db.session.add(post)
    db.session.flush()
    actor_ids = [users[1].id, users[2].id]
    for actor_id, method in zip(actor_ids, [first_method, second_method]):
        if method == "DELETE":
            db.session.add(Bookmark(user_id=actor_id, post_id=post.id))
    post.bookmark_count = int(first_method == "DELETE") + int(second_method == "DELETE")
    db.session.commit()
    post_id = post.id

    # NO KEY UPDATE allows the old implementation to insert/delete child rows
    # and compute a stale count before blocking on the counter UPDATE. The
    # fixed implementation blocks at the parent lock before any mutation.
    db.session.execute(select(Post).where(Post.id == post_id)
                       .with_for_update(key_share=True)).scalar_one()
    started = Event()
    backend = []

    def worker():
        with postgres_app.app_context():
            backend.append(db.session.execute(text("select pg_backend_pid()")).scalar_one())
            earlier_post = db.session.get(Post, post_id)
            started.set()
            return interactions.set_bookmark(post_id, actor_ids[1], earlier_post,
                                             second_method == "PUT")

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(worker)
        try:
            assert started.wait(5)
            waiting = False
            deadline = time.monotonic() + 10
            with db.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
                while time.monotonic() < deadline:
                    waiting = observer.execute(
                        text("select wait_event_type from pg_stat_activity where pid=:pid"),
                        {"pid": backend[0]},
                    ).scalar_one() == "Lock"
                    if waiting:
                        break
                    time.sleep(0.02)
            assert waiting, "The second mutation must overlap the first transaction"
            assert interactions.set_bookmark(post_id, actor_ids[0], post,
                                             first_method == "PUT")[1] == 200
        finally:
            db.session.rollback()
        assert future.result(timeout=10)[1] == 200

    expected = int(first_method == "PUT") + int(second_method == "PUT")
    assert Bookmark.query.filter_by(post_id=post_id).count() == expected
    assert db.session.get(Post, post_id).bookmark_count == expected
