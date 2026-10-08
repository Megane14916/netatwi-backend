"""Hidden qualifier settings must not block ordinary contests or updates."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from app.extensions import db
from app.integrations import cloud_tasks
from app.models import Contest


BASE = {"name": "Ordinary", "startTime": "2026-01-01T00:00:00Z",
        "endTime": "2026-01-01T01:00:00Z", "votingEndTime": "2026-01-01T02:00:00Z"}
UNUSED_FIELDS = [
    ("qualifierJudgeMaxScore", None), ("qualifierGeneralVoteWeight", []),
    ("qualifierScoringMethod", "invalid"), ("qualifierImageRule", []),
    ("qualifierHasTheme", 1), ("qualifierTheme", []),
    ("qualifierJudgePassword", {}), ("qualifierIsVotingVisible", None),
    ("qualifierStartTime", "bad"), ("qualifierEndTime", "bad"),
    ("qualifierVotingEndTime", "bad"),
]


@pytest.fixture
def admin_case(user_factory, contest_factory, login, monkeypatch):
    login(user_factory("test_admin"))
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    contest = contest_factory(now, now + timedelta(hours=1), now + timedelta(hours=2),
                              has_qualifier=True, judge_award_advancement=False)
    scheduler = Mock()
    monkeypatch.setattr(cloud_tasks, "schedule_contest_task", scheduler)
    return contest, scheduler


@pytest.mark.parametrize("operation", ["create", "create_default", "update"])
@pytest.mark.parametrize("field, value", UNUSED_FIELDS)
def test_unused_qualifier_fields_are_ignored(client, admin_case, operation, field, value):
    contest, scheduler = admin_case
    payload = dict(BASE, **{field: value})
    if operation == "create":
        payload["hasQualifier"] = False
    if operation == "update":
        # The existing final has has_qualifier=True, but this endpoint does not
        # create or modify its qualifier: those fields are still unused here.
        payload["hasQualifier"] = True
        response = client.put(f"/api/admin/contests/{contest.id}", json=payload)
        assert response.status_code == 200
        target = db.session.get(Contest, contest.id)
        assert Contest.query.count() == 1
        assert target.has_qualifier is True
    else:
        response = client.post("/api/admin/contests", json=payload)
        assert response.status_code == 201
        target = db.session.get(Contest, response.get_json()["id"])
        assert Contest.query.count() == 2
        assert target.has_qualifier is False
    assert target.name == BASE["name"]
    assert target.judge_max_score == 10 and target.scoring_method == "both"
    assert target.judge_award_advancement is False
    assert scheduler.call_count == 3


@pytest.mark.parametrize("field, value", UNUSED_FIELDS + [("qualifierJudgeAwardAdvancement", [])])
def test_used_qualifier_fields_still_reject_invalid_input(client, admin_case, field, value):
    response = client.post("/api/admin/contests", json=dict(BASE, hasQualifier=True, **{field: value}))
    assert response.status_code == 400
    assert Contest.query.count() == 1
    admin_case[1].assert_not_called()


def test_unused_create_award_alias_is_ignored(client, admin_case):
    response = client.post("/api/admin/contests", json=dict(BASE, hasQualifier=False,
                                                            qualifierJudgeAwardAdvancement=[]))
    assert response.status_code == 201
    assert db.session.get(Contest, response.get_json()["id"]).judge_award_advancement is False


@pytest.mark.parametrize("value, expected_status", [(True, 200), (False, 200), ([], 400), (1, 400)])
def test_update_award_alias_is_used_and_validated(client, admin_case, value, expected_status):
    contest, scheduler = admin_case
    response = client.put(f"/api/admin/contests/{contest.id}",
                          json={"qualifierJudgeAwardAdvancement": value})
    assert response.status_code == expected_status
    assert contest.judge_award_advancement is (value if expected_status == 200 else False)
    assert scheduler.call_count == (3 if expected_status == 200 else 0)
