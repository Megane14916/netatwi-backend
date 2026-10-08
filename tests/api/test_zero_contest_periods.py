"""Contest periods may be empty, but their boundaries cannot be reversed."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from app.extensions import db
from app.integrations import cloud_tasks
from app.models import Contest


BASE = {"name": "Empty period", "startTime": "2026-01-01T00:00:00Z",
        "endTime": "2026-01-01T01:00:00Z", "votingEndTime": "2026-01-01T02:00:00Z"}
ZERO_PERIODS = [
    {"endTime": BASE["startTime"]},
    {"votingEndTime": BASE["endTime"]},
    {"endTime": BASE["startTime"], "votingEndTime": BASE["startTime"]},
]


@pytest.fixture
def admin_case(user_factory, login, monkeypatch):
    login(user_factory("test_admin"))
    scheduler = Mock()
    monkeypatch.setattr(cloud_tasks, "schedule_contest_task", scheduler)
    return scheduler


@pytest.mark.parametrize("method", ["POST", "PUT"])
@pytest.mark.parametrize("patch", ZERO_PERIODS)
def test_zero_periods_can_be_created_and_updated(client, admin_case, contest_factory, method, patch):
    path = "/api/admin/contests"
    if method == "PUT":
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        contest = contest_factory(now, now + timedelta(hours=1), now + timedelta(hours=2))
        path += f"/{contest.id}"
    data = dict(BASE, **patch)
    response = client.open(path, method=method, json=data)
    assert response.status_code == (201 if method == "POST" else 200)
    target = db.session.get(Contest, response.get_json()["id"] if method == "POST" else contest.id)
    assert [target.start_time, target.end_time, target.voting_end_time] == [
        datetime.fromisoformat(data[field].replace("Z", "+00:00")).replace(tzinfo=None)
        for field in ("startTime", "endTime", "votingEndTime")
    ]
    assert admin_case.call_count == 3


@pytest.mark.parametrize("patch", ZERO_PERIODS)
def test_qualifier_can_have_zero_periods(client, admin_case, patch):
    times = dict(BASE, **patch)
    payload = dict(BASE, hasQualifier=True)
    for field in ("startTime", "endTime", "votingEndTime"):
        payload["qualifier" + field[0].upper() + field[1:]] = times[field]
    response = client.post("/api/admin/contests", json=payload)
    assert response.status_code == 201
    qualifier = db.session.get(Contest, response.get_json()["qualifier_id"])
    assert qualifier.start_time <= qualifier.end_time <= qualifier.voting_end_time
    assert qualifier.start_time == qualifier.end_time or qualifier.end_time == qualifier.voting_end_time
    assert admin_case.call_count == 6


@pytest.mark.parametrize("patch", ZERO_PERIODS[:2])
def test_partial_update_can_make_a_period_empty(client, admin_case, contest_factory, patch):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    contest = contest_factory(now, now + timedelta(hours=1), now + timedelta(hours=2))
    response = client.put(f"/api/admin/contests/{contest.id}", json=patch)
    assert response.status_code == 200
    assert contest.start_time == contest.end_time or contest.end_time == contest.voting_end_time


@pytest.mark.parametrize("patch, hour, vote_status, result_status", [
    (ZERO_PERIODS[0], 0, 200, 403),
    (ZERO_PERIODS[1], 1, 403, 200),
    (ZERO_PERIODS[2], 0, 403, 200),
])
def test_empty_periods_allow_no_operations_inside_them(
    client, admin_case, fixed_time, patch, hour, vote_status, result_status,
):
    response = client.post("/api/admin/contests", json=dict(BASE, **patch))
    assert response.status_code == 201
    contest_id = response.get_json()["id"]
    fixed_time(datetime(2026, 1, 1, hour, tzinfo=timezone.utc))
    assert client.post(f"/api/contests/{contest_id}/posts", data={"content": "Entry"}).status_code == 403
    assert client.post(f"/api/contests/{contest_id}/vote", json={"votes": {}}).status_code == vote_status
    assert client.get(f"/api/contests/{contest_id}/results").status_code == result_status


@pytest.mark.parametrize("patch", [
    {"qualifierEndTime": "2025-12-31T23:59:59Z"},
    {"qualifierVotingEndTime": "2026-01-01T00:59:59Z"},
])
def test_reversed_qualifier_periods_still_fail_without_side_effects(client, admin_case, patch):
    response = client.post("/api/admin/contests", json=dict(BASE, hasQualifier=True, **patch))
    assert response.status_code == 400
    assert Contest.query.count() == 0
    admin_case.assert_not_called()
