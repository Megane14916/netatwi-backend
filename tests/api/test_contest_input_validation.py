import json
from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import Mock

from app.extensions import db
from app.models import Contest
from app.integrations import cloud_tasks


BASE = {"name": "Contest", "startTime": "2026-01-01T00:00:00Z", "endTime": "2026-01-01T01:00:00Z", "votingEndTime": "2026-01-01T02:00:00Z"}


@pytest.fixture
def admin_case(user_factory, login, contest_factory, monkeypatch):
    login(user_factory("test_admin"))
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    contest = contest_factory(now, now + timedelta(hours=1), now + timedelta(hours=2))
    schedule = Mock()
    monkeypatch.setattr(cloud_tasks, "schedule_contest_task", schedule)
    return contest, schedule


@pytest.mark.parametrize("method", ["POST", "PUT"])
@pytest.mark.parametrize("patch", [
    {"name": None}, {"name": []}, {"name": " "}, {"name": "x" * 121},
    {"hasTheme": "false"}, {"hasQualifier": 1}, {"isVotingVisible": None},
    {"judgeAwardAdvancement": []}, {"generalVoteWeight": True}, {"generalVoteWeight": 1.5},
    {"generalVoteWeight": -1}, {"generalVoteWeight": 2**31}, {"judgeMaxScore": 0},
    {"judgePassword": {}}, {"judgePassword": "s" * 121}, {"theme": []}, {"resultCommentTop": []},
    {"startTime": None}, {"endTime": "bad"}, {"votingEndTime": 123},
    {"endTime": "2025-12-31T23:59:59Z"}, {"votingEndTime": "2026-01-01T00:59:59Z"},
    {"type": "invalid"}, {"scoringMethod": []}, {"imageRule": "invalid"},
    {"advancementDenominator": 0}, {"advancementNumerator": 3, "advancementDenominator": 2},
])
def test_admin_validates_all_fields_before_side_effects(client, admin_case, method, patch):
    contest, schedule = admin_case
    path = "/api/admin/contests" + (f"/{contest.id}" if method == "PUT" else "")
    data = dict(BASE, **patch)
    response = client.open(path, method=method, json=data)
    assert response.status_code == 400
    assert isinstance(response.get_json()["error"], str)
    assert Contest.query.count() == 1
    assert db.session.get(Contest, contest.id).name == "Test contest"
    schedule.assert_not_called()


@pytest.mark.parametrize("body", ["null", "[]", "42", "true", "{", ""])
def test_invalid_admin_json_returns_400(client, admin_case, body):
    response = client.post("/api/admin/contests", data=body, content_type="application/json")
    assert response.status_code == 400
    assert "error" in response.get_json()
    assert Contest.query.count() == 1
    admin_case[1].assert_not_called()


def test_timezone_offsets_are_normalized_before_storage(client, admin_case):
    data = dict(BASE, startTime="2026-01-01T09:00:00+09:00", endTime="2026-01-01T10:00:00+09:00", votingEndTime="2026-01-01T11:00:00+09:00")
    response = client.post("/api/admin/contests", json=data)
    assert response.status_code == 201
    contest = db.session.get(Contest, response.get_json()["id"])
    assert contest.start_time == datetime(2026, 1, 1)
    assert contest.end_time == datetime(2026, 1, 1, 1)


def test_valid_partial_update_uses_stored_period(client, admin_case):
    contest, schedule = admin_case
    response = client.put(f"/api/admin/contests/{contest.id}", json={"name": "Updated", "generalVoteWeight": "0"})
    assert response.status_code == 200
    assert contest.name == "Updated" and contest.general_vote_weight == 0
