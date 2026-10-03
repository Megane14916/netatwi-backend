"""Freeze vote replacement, score/award handling and transaction boundaries."""

from datetime import datetime, timedelta, timezone
import logging

import pytest
from sqlalchemy import event
from werkzeug.datastructures import ImmutableMultiDict

import app as app_module
from models import Contest, Post, Vote, db


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


@pytest.fixture
def voting(client, contest_factory, user_factory, login, fixed_time):
    contest = contest_factory(NOW - timedelta(hours=1), NOW, NOW + timedelta(hours=1),
                              judge_max_score=5)
    author, voter = user_factory("author"), user_factory("voter")
    post = Post(contest_id=contest.id, user_id=author.id, content="Entry")
    own_post = Post(contest_id=contest.id, user_id=voter.id, content="Own")
    db.session.add_all([post, own_post])
    db.session.commit()
    login(voter)
    fixed_time(NOW)
    return contest, voter, post, own_post, f"/api/contests/{contest.id}/vote"


def counts(contest):
    db.session.expire_all()
    current = db.session.get(Contest, contest.id)
    return current.total_voters, current.total_judges


def seed_vote(contest, voter, post, judge=False):
    vote = Vote(contest_id=contest.id, user_id=voter.id, post_id=post.id, count=1,
                is_judge_vote=judge)
    db.session.add(vote)
    contest.total_voters, contest.total_judges = 1, int(judge)
    db.session.commit()
    return vote


@pytest.mark.parametrize("judge,score,expected", [
    (False, 0, None), (False, 1, 1.0), (False, "1", 1.0), (False, True, 1.0),
    (False, 0.5, None), (False, 2, None), (False, -1, None), (False, None, None),
    (False, "invalid", None), (True, 0, 0.0), (True, 2.5, 2.5),
    (True, 5, 5.0), (True, 5.01, None), (True, -1, None), (True, "NaN", None),
])
def test_score_conversion_range_and_zero(client, voting, login, judge, score, expected):
    contest, voter, post, _, path = voting
    login(voter, judge_contests=[contest.id] if judge else [])
    response = client.post(path, json={"votes": {str(post.id): score}})
    assert response.status_code == 200
    assert response.get_json() == {"message": "Voted"}
    rows = Vote.query.all()
    if expected is None:
        assert rows == []
        assert counts(contest) == (0, 0)
    else:
        assert len(rows) == 1
        vote = rows[0]
        assert (vote.user_id, vote.post_id, vote.contest_id, vote.count,
                vote.is_judge_vote, vote.is_judge_award, vote.judge_comment) == (
                    voter.id, post.id, contest.id, expected, judge, False, None)
        assert counts(contest) == (1, int(judge))


@pytest.mark.parametrize("offset,allowed", [
    (timedelta(microseconds=-1), False), (timedelta(0), True),
    (timedelta(hours=1, microseconds=-1), True), (timedelta(hours=1), False),
])
def test_period_checked_before_replacing_existing_votes(client, voting, fixed_time, offset, allowed):
    contest, voter, post, _, path = voting
    seed_vote(contest, voter, post)
    fixed_time(NOW + offset)
    response = client.post(path, json={"votes": {}})
    assert response.status_code == (200 if allowed else 403)
    assert response.get_json() == ({"message": "Voted"} if allowed else {"error": "Outside period"})
    assert Vote.query.count() == (0 if allowed else 1)
    assert counts(contest) == ((0, 0) if allowed else (1, 0))


def test_invalid_ids_missing_posts_and_own_posts_are_skipped_while_foreign_contest_post_is_kept(
    client, voting, contest_factory, user_factory
):
    contest, voter, post, own, path = voting
    foreign = contest_factory(NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2))
    foreign_post = Post(contest_id=foreign.id, user_id=user_factory("foreign_author").id, content="Foreign")
    db.session.add(foreign_post)
    db.session.commit()
    response = client.post(path, json={"votes": {
        "invalid": 1, "999": 1, str(own.id): 1, str(post.id): 1, str(foreign_post.id): 1,
    }})
    assert response.status_code == 200
    rows = Vote.query.order_by(Vote.post_id).all()
    assert [(v.post_id, v.contest_id, v.count) for v in rows] == [
        (post.id, contest.id, 1.0), (foreign_post.id, contest.id, 1.0),
    ]
    assert counts(contest) == (1, 0)
    assert counts(foreign) == (0, 0)


@pytest.mark.parametrize("score,target", [(None, "post"), (0, "post"), (3, "post"),
                                         (6, "post"), (None, "own")])
def test_award_fallback_preserves_zero_invalid_score_and_own_target(client, voting, login, score, target):
    contest, voter, post, own, path = voting
    selected = post if target == "post" else own
    login(voter, judge_contests=[contest.id])
    response = client.post(path, json={
        "votes": {} if score is None else {str(selected.id): score},
        "judgeAward": {"postId": selected.id, "comment": " Award\r\n"},
    })
    assert response.status_code == 200
    assert response.get_json() == {"message": "Voted"}
    vote = Vote.query.one()
    assert (vote.post_id, vote.count, vote.is_judge_vote, vote.is_judge_award, vote.judge_comment) == (
        selected.id, 3.0 if score == 3 else 0.0, True, True, " Award\r\n")
    assert counts(contest) == (1, 1)


def test_ordinary_voter_ignores_award_and_string_judge_session_id(client, voting, login):
    contest, voter, post, _, path = voting
    login(voter, judge_contests=[str(contest.id)])
    response = client.post(path, json={"votes": {str(post.id): 0}, "judgeAward": "invalid award"})
    assert response.status_code == 200
    assert Vote.query.count() == 0
    assert counts(contest) == (0, 0)


def test_judge_session_still_applies_in_general_scoring_contest(client, voting, login):
    contest, voter, post, _, path = voting
    contest.scoring_method = "user"
    db.session.commit()
    login(voter, judge_contests=[contest.id])
    response = client.post(path, json={"votes": {str(post.id): 5}})
    assert response.status_code == 200
    assert Vote.query.one().is_judge_vote is True
    assert counts(contest) == (1, 1)


def test_replacement_judge_transitions_and_empty_submission_counters(client, voting, login):
    contest, voter, post, _, path = voting
    seed_vote(contest, voter, post)
    for judge, scores, expected in [
        (True, {str(post.id): 0}, (1, 1)), (True, {str(post.id): 0}, (1, 1)),
        (False, {str(post.id): 1}, (1, 0)), (False, {}, (0, 0)),
    ]:
        login(voter, judge_contests=[contest.id] if judge else [])
        response = client.post(path, json={"votes": scores})
        assert response.status_code == 200
        assert counts(contest) == expected
        assert Vote.query.count() == bool(scores)


def test_counters_do_not_decrement_below_zero(client, voting):
    contest, voter, post, _, path = voting
    seed_vote(contest, voter, post, judge=True)
    contest.total_voters = contest.total_judges = 0
    db.session.commit()
    assert client.post(path, json={"votes": {}}).status_code == 200
    assert counts(contest) == (0, 0)


@pytest.mark.parametrize("payload", [{}, {"votes": []}, {"votes": None}])
def test_invalid_vote_data_precedes_missing_contest(client, voting, payload):
    response = client.post("/api/contests/999/vote", json=payload)
    assert response.status_code == 400
    assert response.get_json() == {"error": "Invalid vote data"}


def test_text_validation_normalizes_form_and_ignores_json_content(client, app, voting, monkeypatch):
    from flask import request

    _, _, _, _, path = voting
    seen = []
    form_content = [None]
    monkeypatch.setattr(app_module, "calculate_weighted_length", lambda text: seen.append(text) or len(text))

    @app.before_request
    def provide_form_content():
        if form_content[0] is not None:
            request.__dict__["form"] = ImmutableMultiDict({"content": form_content[0]})

    assert client.post(path, json={"votes": {}, "content": "x" * 281}).status_code == 200
    assert seen == [""]
    form_content[0] = "a\r\nb\rc"
    assert client.post(path, json={"votes": {}}).status_code == 200
    assert seen[-1] == "a\nb\nc"
    form_content[0] = "x" * 281
    rejected = client.post("/api/contests/999/vote", json={"votes": {}})
    assert rejected.status_code == 400
    assert rejected.get_json() == {"error": "Text too long (max 280)"}


def test_null_json_and_validation_exception_remain_outside_handler(client, voting, monkeypatch):
    _, _, _, _, path = voting
    with pytest.raises(AttributeError):
        client.post(path, data="null", content_type="application/json")

    def fail_length(_text):
        raise RuntimeError("length failed")

    monkeypatch.setattr(app_module, "calculate_weighted_length", fail_length)
    with pytest.raises(RuntimeError, match="length failed"):
        client.post(path, json={"votes": {}})


@pytest.mark.parametrize("failure", ["missing", "award_type", "award_string_id", "commit"])
def test_failure_rolls_back_replacement_and_preserves_counters(
    client, voting, login, monkeypatch, failure, caplog, capsys
):
    contest, voter, post, _, path = voting
    seed_vote(contest, voter, post)
    login(voter, judge_contests=[contest.id])
    original_commit, original_rollback = db.session.commit, db.session.rollback
    events = []

    def commit():
        events.append("commit")
        if failure == "commit":
            raise RuntimeError("commit failed")
        original_commit()

    def rollback():
        events.append("rollback")
        original_rollback()

    monkeypatch.setattr(db.session, "commit", commit)
    monkeypatch.setattr(db.session, "rollback", rollback)
    payload = {"votes": {str(post.id): 5}}
    if failure == "missing":
        path = "/api/contests/999/vote"
    elif failure == "award_type":
        payload["judgeAward"] = "invalid award"
    elif failure == "award_string_id":
        payload["judgeAward"] = {"postId": str(post.id), "comment": "award"}
    with caplog.at_level(logging.INFO, logger="app"):
        response = client.post(path, json=payload)
    assert response.status_code == 500
    assert response.get_json() == {"error": "Error"}
    assert events == (["commit", "rollback"] if failure == "commit" else ["rollback"])
    vote = Vote.query.one()
    assert (vote.count, vote.is_judge_vote, vote.is_judge_award, vote.judge_comment) == (1, False, False, None)
    assert counts(contest) == (1, 0)
    assert "==> [submit_votes] ERROR in " in caplog.messages[-1]
    assert capsys.readouterr().out.startswith("Error: ")


def test_database_operation_order_and_log_messages(client, voting, login, monkeypatch, caplog):
    contest, voter, post, _, path = voting
    contest_id, post_id = contest.id, post.id
    operations = []
    original_commit = db.session.commit

    def record_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.startswith("DELETE FROM vote"):
            operations.append("delete old votes")
        elif statement.startswith("SELECT post."):
            operations.append("fetch posts")
        elif statement.startswith("INSERT INTO vote"):
            operations.append("insert vote")
        elif statement.startswith("UPDATE contest SET total_voters"):
            operations.append("update voters")
        elif statement.startswith("UPDATE contest SET total_judges"):
            operations.append("update judges")

    def commit():
        operations.append("commit")
        original_commit()

    import time
    monkeypatch.setattr(time, "time", lambda: 100.0)
    # Sign the session cookie with the same clock used to validate it.
    login(voter, judge_contests=[contest_id])
    monkeypatch.setattr(db.session, "commit", commit)
    event.listen(db.engine, "before_cursor_execute", record_sql)
    try:
        with caplog.at_level(logging.INFO, logger="app"):
            response = client.post(path, json={"votes": {str(post_id): 2}})
    finally:
        event.remove(db.engine, "before_cursor_execute", record_sql)
    assert response.status_code == 200
    assert operations == ["delete old votes", "fetch posts", "insert vote", "update voters", "update judges", "commit"]
    assert caplog.messages == [
        f"==> [submit_votes] START for contest {contest.id}",
        "==> [submit_votes] get_or_404 took: 0.0000s",
        "==> [submit_votes] delete took: 0.0000s",
        "==> [submit_votes] loop took: 0.0000s",
        "==> [submit_votes] commit took: 0.0000s",
        "==> [submit_votes] FINISHED in 0.0000s",
    ]
