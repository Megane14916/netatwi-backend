"""Result persistence and notification failures must remain retryable (Refs #22)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import Contest, ContestResult, Notification, Post, db


@pytest.mark.parametrize("entry", ["task", "cli"])
@pytest.mark.parametrize("failure", ["bulk", "commit", "notification"])
def test_result_failure_rolls_back_and_retry_runs_once(
    task_client, runner, contest_factory, user_factory, fixed_time, monkeypatch, entry, failure
):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = user_factory("author")
    contest = contest_factory(now - timedelta(hours=3), now - timedelta(hours=2), now,
                              notified_post_start=True, notified_voting_start=True)
    contest_id = contest.id
    db.session.add(Post(contest_id=contest_id, user_id=user.id, content="Entry"))
    db.session.commit()
    fixed_time(now)

    method = {"bulk": "bulk_save_objects", "commit": "commit",
              "notification": "bulk_insert_mappings" if entry == "task" else "add"}[failure]
    original = getattr(db.session, method)

    def fail(*args, **kwargs):
        raise RuntimeError("injected persistence failure")

    def invoke():
        if entry == "task":
            return task_client.post(f"/api/tasks/contest/{contest_id}/result_announce")
        return runner.invoke(args=["process-contests"])

    monkeypatch.setattr(db.session, method, fail)
    if entry == "task":
        with pytest.raises(RuntimeError, match="injected persistence failure"):
            invoke()
    else:
        assert invoke().exit_code != 0
    db.session.expire_all()
    assert ContestResult.query.count() == 0
    assert Notification.query.count() == 0
    assert not db.session.get(Contest, contest_id).notified_result_announce

    monkeypatch.setattr(db.session, method, original)
    for _ in range(2):
        result = invoke()
        assert (result.status_code if entry == "task" else result.exit_code) == (200 if entry == "task" else 0)
    assert ContestResult.query.count() == 1
    assert Notification.query.count() == 1
    assert db.session.get(Contest, contest_id).notified_result_announce
