import json
from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models import Post, Vote


@pytest.fixture
def vote_case(user_factory, contest_factory, login, fixed_time):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fixed_time(now)
    author, voter = user_factory("author"), user_factory("voter")
    contest = contest_factory(now - timedelta(hours=2), now - timedelta(hours=1), now + timedelta(hours=1))
    post = Post(user_id=author.id, contest_id=contest.id, content="Entry")
    db.session.add(post)
    db.session.flush()
    db.session.add(Vote(user_id=voter.id, contest_id=contest.id, post_id=post.id, count=1))
    contest.total_voters = contest.total_judges = 1
    db.session.commit()
    login(voter, judge_contests=[contest.id])
    return contest, post


@pytest.mark.parametrize("body", [None, [], "text", True, 42])
def test_vote_json_shape_is_validated(client, vote_case, body):
    contest, post = vote_case
    response = client.post(f"/api/contests/{contest.id}/vote", data=json.dumps(body), content_type="application/json")
    assert response.status_code == 400
    assert response.get_json() == {"error": "Expected a JSON object"}
    assert Vote.query.one().count == 1
    assert (contest.total_voters, contest.total_judges) == (1, 1)


@pytest.mark.parametrize("value", [True, False, None, [], {}, "", "nan", "inf"])
def test_invalid_score_types_do_not_replace_votes(client, vote_case, value):
    contest, post = vote_case
    response = client.post(f"/api/contests/{contest.id}/vote", json={"votes": {str(post.id): value}})
    assert response.status_code == 400
    assert Vote.query.one().count == 1
    assert (contest.total_voters, contest.total_judges) == (1, 1)


@pytest.mark.parametrize("comment", [123, [], {}, True])
def test_award_comment_type_validated_before_deleting_votes(client, vote_case, comment):
    contest, post = vote_case
    response = client.post(f"/api/contests/{contest.id}/vote", json={"votes": {}, "judgeAward": {"postId": post.id, "comment": comment}})
    assert response.status_code == 400
    assert Vote.query.one().count == 1
    assert (contest.total_voters, contest.total_judges) == (1, 1)
