"""Exercise real PostgreSQL locks using a disposable CI-only database."""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event

import pytest
from sqlalchemy import select, text

from app.extensions import db
from app.models import Contest, ContestResult, Notification, Post, User
from app.services import contest_lifecycle, results


@pytest.mark.parametrize("entry, other, empty", [
    ("results", "results", False), ("task", "task", False), ("cli", "cli", False),
    ("task", "task", True), ("cli", "cli", True),
    ("task", "cli", False), ("cli", "task", False),
    ("task", "cli", True), ("cli", "task", True),
])
def test_result_and_notification_generation_is_serialized(postgres_app, fixed_time, entry, other, empty):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fixed_time(now)
    author = User(twitter_id="pg-author", screen_name="pg_author", name="Author")
    contest = Contest(name="PG contest", start_time=now - timedelta(hours=3), end_time=now - timedelta(hours=2), voting_end_time=now, notified_post_start=True, notified_voting_start=True)
    db.session.add_all([author, contest])
    db.session.flush()
    if not empty:
        db.session.add(Post(user_id=author.id, contest_id=contest.id, content="Entry"))
    db.session.commit()
    contest_id = contest.id
    # Hold the same contest row while the second worker begins. Before the fix,
    # it reads "no results" then blocks on the FK insert; after the fix it blocks
    # before inspecting results/flags. pg_stat_activity proves the real overlap.
    db.session.execute(select(Contest).where(Contest.id == contest_id).with_for_update()).scalar_one()
    started = Event()
    backend = []

    def invoke(operation):
        if operation == "results":
            results.generate_contest_results(contest_id)
        elif operation == "task":
            contest_lifecycle.handle_contest_task(contest_id, "result_announce")
        else:
            contest_lifecycle.process_contests()

    def worker():
        with postgres_app.app_context():
            backend.append(db.session.execute(text("select pg_backend_pid()")).scalar_one())
            started.set()
            invoke(other)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(worker)
        try:
            assert started.wait(5)
            waiting = False
            deadline = time.monotonic() + 10
            with db.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
                while time.monotonic() < deadline:
                    waiting = observer.execute(text("select wait_event_type from pg_stat_activity where pid=:pid"), {"pid": backend[0]}).scalar_one() == "Lock"
                    if waiting:
                        break
                    time.sleep(0.02)
            assert waiting, "The second worker must overlap while the first holds the row lock"
            invoke(entry)
        finally:
            db.session.rollback()  # Release the lock even when an assertion fails.
        future.result(timeout=10)
    assert ContestResult.query.count() == int(not empty)
    assert Notification.query.count() == (0 if entry == "results" else 1)
    assert db.session.get(Contest, contest_id).notified_result_announce is (entry != "results")
