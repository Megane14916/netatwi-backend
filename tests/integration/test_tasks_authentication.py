"""Unauthenticated task requests must never reach lifecycle mutations (#23)."""

from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import Mock
from app.integrations import cloud_tasks
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


@pytest.mark.parametrize("claims,status", [
    ({"aud": "https://other.example"}, 401),
    ({"iss": "https://forged.example"}, 401),
    ({"iat": 1, "exp": 2}, 401),
    ({"email": "other@example.iam.gserviceaccount.com"}, 403),
    ({"email_verified": False}, 403),
    ({"email_verified": "true"}, 403),
])
@pytest.mark.parametrize("event", ["post_start", "voting_start", "result_announce"])
def test_signed_but_invalid_or_unauthorized_token_never_mutates(
    app, client, signed_task_headers, contest_factory, user_factory, fixed_time, claims, status, event
):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    contest = contest_factory(now - timedelta(hours=3), now - timedelta(hours=2), now - timedelta(hours=1))
    user = user_factory("author")
    db.session.add(Post(contest_id=contest.id, user_id=user.id, content="Entry"))
    db.session.commit()
    fixed_time(now)
    response = client.post(f"/api/tasks/contest/{contest.id}/{event}", headers=signed_task_headers(**claims))
    assert response.status_code == status
    db.session.expire_all()
    assert not any([contest.notified_post_start, contest.notified_voting_start, contest.notified_result_announce])
    assert ContestResult.query.count() == Notification.query.count() == 0


def test_tampered_signature_and_config_or_certificate_failure_fail_closed(
    app, client, signed_task_headers, monkeypatch, caplog
):
    from google.auth.exceptions import TransportError
    headers = signed_task_headers()
    token = headers["Authorization"].split()[1]
    parts = token.split(".")
    parts[2] = ("A" if parts[2][0] != "A" else "B") + parts[2][1:]
    assert client.post("/api/tasks/contest/999/post_start", headers={"Authorization": "Bearer " + ".".join(parts)}).status_code == 401
    monkeypatch.setattr(cloud_tasks.id_token, "_fetch_certs", Mock(side_effect=TransportError("cert unavailable")))
    assert client.post("/api/tasks/contest/999/post_start", headers=headers).status_code == 503
    app.config["TASKS_OIDC_AUDIENCE"] = ""
    assert client.post("/api/tasks/contest/999/post_start", headers=headers).status_code == 503
    assert token not in caplog.text


@pytest.mark.parametrize("setting", ["TASKS_OIDC_AUDIENCE", "TASKS_SERVICE_ACCOUNT_EMAIL"])
def test_scheduler_never_enqueues_unsigned_task(app, fake_cloud_tasks, monkeypatch, setting):
    monkeypatch.setenv(setting, "")
    with pytest.raises(ValueError, match="OIDC"):
        cloud_tasks.schedule_contest_task(1, "post_start", datetime.now(timezone.utc))
    fake_cloud_tasks.create_task.assert_not_called()
