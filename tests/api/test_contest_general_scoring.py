"""The legacy general label must retain judge plus weighted user scoring."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from app.extensions import db
from app.integrations import cloud_tasks
from app.models import Contest, ContestResult, Post, Vote
from app.services.results import generate_contest_results


@pytest.mark.parametrize("operation", ["create", "qualifier", "update"])
def test_general_input_preserves_combined_score(
    client, user_factory, contest_factory, login, monkeypatch, operation,
):
    login(user_factory("test_admin"))
    monkeypatch.setattr(cloud_tasks, "schedule_contest_task", Mock())
    payload = {
        "name": "Combined", "scoringMethod": "general",
        "startTime": "2026-01-01T00:00:00Z",
        "endTime": "2026-01-01T01:00:00Z",
        "votingEndTime": "2026-01-01T02:00:00Z",
    }
    if operation == "update":
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        contest = contest_factory(now, now + timedelta(hours=1),
                                  now + timedelta(hours=2), scoring_method="general")
        response = client.put(f"/api/admin/contests/{contest.id}",
                              json={"scoringMethod": "general"})
        assert response.status_code == 200
    else:
        if operation == "qualifier":
            payload.update(hasQualifier=True, qualifierScoringMethod="general")
        response = client.post("/api/admin/contests", json=payload)
        assert response.status_code == 201
        body = response.get_json()
        assert db.session.get(Contest, body["id"]).scoring_method == "both"
        contest = db.session.get(Contest, body["qualifier_id"] if operation == "qualifier" else body["id"])

    assert contest.scoring_method == "both"
    author, voter, judge = [user_factory(name) for name in ("author", "voter", "judge")]
    post = Post(user_id=author.id, contest_id=contest.id, content="Entry")
    db.session.add(post)
    db.session.flush()
    db.session.add_all([
        Vote(user_id=voter.id, post_id=post.id, contest_id=contest.id, count=1, is_judge_vote=False),
        Vote(user_id=judge.id, post_id=post.id, contest_id=contest.id, count=2, is_judge_vote=True),
    ])
    db.session.commit()
    generate_contest_results(contest.id)
    assert ContestResult.query.filter_by(post_id=post.id).one().score == 52.0
