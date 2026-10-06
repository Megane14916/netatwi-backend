"""Unauthenticated task requests must never reach lifecycle mutations (#23)."""

from datetime import datetime, timedelta, timezone

import pytest
from app.models import Contest, ContestResult, Notification, Post, db


@pytest.mark.parametrize("event", ["post_start", "voting_start", "result_announce"])
@pytest.mark.parametrize("headers", [{}, {"X-CloudTasks-TaskName": "forged", "X-CloudTasks-QueueName": "forged"}, {"Authorization": "Basic forged"}])
def test_anonymous_or_forged_task_headers_cannot_mutate(
    app, client, contest_factory, user_factory, fixed_time, event, headers
):
    app.config.update(TASKS_OIDC_AUDIENCE="https://backend.example", TASKS_SERVICE_ACCOUNT_EMAIL="tasks@example.iam.gserviceaccount.com")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = user_factory("author")
    contest = contest_factory(now - timedelta(hours=3), now - timedelta(hours=2), now - timedelta(hours=1))
    db.session.add(Post(contest_id=contest.id, user_id=user.id, content="Entry"))
    db.session.commit()
    fixed_time(now)
    response = client.post(f"/api/tasks/contest/{contest.id}/{event}", headers=headers)
    assert response.status_code == 401
    db.session.expire_all()
    saved = db.session.get(Contest, contest.id)
    assert not any([saved.notified_post_start, saved.notified_voting_start, saved.notified_result_announce])
    assert Notification.query.count() == ContestResult.query.count() == 0
