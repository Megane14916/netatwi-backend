"""Freeze result generation boundaries and read-only result presentation."""

from datetime import datetime, timedelta, timezone

import pytest

import app as app_module
from app.models import ContestResult, Notification, Post, Vote, db


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


@pytest.fixture
def finished(contest_factory, user_factory, fixed_time):
    contest = contest_factory(NOW - timedelta(hours=2), NOW - timedelta(hours=1), NOW,
                              notified_post_start=True, notified_voting_start=True)
    author = user_factory("author")
    post = Post(contest_id=contest.id, user_id=author.id, content="Entry", created_at=NOW)
    db.session.add(post)
    db.session.commit()
    fixed_time(NOW)
    return contest, author, post


def observe_writes(monkeypatch, failure=None):
    events = []
    original_bulk = db.session.bulk_save_objects
    original_commit, original_rollback = db.session.commit, db.session.rollback

    def bulk(rows):
        events.append(("results", len(rows)))
        if failure == "bulk":
            raise RuntimeError("bulk failed")
        return original_bulk(rows)

    def commit():
        events.append("commit")
        if failure == "commit" and events.count("commit") == 1:
            raise RuntimeError("commit failed")
        return original_commit()

    def rollback():
        events.append("rollback")
        return original_rollback()

    monkeypatch.setattr(db.session, "bulk_save_objects", bulk)
    monkeypatch.setattr(db.session, "commit", commit)
    monkeypatch.setattr(db.session, "rollback", rollback)
    return events


def test_missing_contest_and_partial_saved_results_skip_all_writes(finished, monkeypatch):
    contest, author, post = finished
    extra = Post(contest_id=contest.id, user_id=author.id, content="Not ranked")
    db.session.add(extra)
    db.session.add(ContestResult(contest_id=contest.id, post_id=post.id, user_id=author.id,
                                score=12.5, rank=7, is_advanced=True, is_judge_award=True))
    db.session.commit()
    events = observe_writes(monkeypatch)
    assert app_module.generate_contest_results(999) is None
    assert app_module.generate_contest_results(contest.id) is None
    assert events == []
    assert app_module.get_cached_contest_results(999) == {}
    assert app_module.get_cached_contest_results(contest.id) == {
        post.id: {"post_id": post.id, "rank": 7, "score": 12.5,
                  "is_advanced": True, "is_judge_award": True},
    }


def test_empty_generation_still_bulk_saves_and_commits_on_every_run(contest_factory, monkeypatch):
    contest = contest_factory(NOW, NOW, NOW)
    events = observe_writes(monkeypatch)
    for _ in range(2):
        assert app_module.generate_contest_results(contest.id) is None
        assert app_module.get_cached_contest_results(contest.id) == {}
    assert events == [("results", 0), "commit", ("results", 0), "commit"]


@pytest.mark.parametrize("failure", ["bulk", "commit"])
def test_generation_persistence_failure_rolls_back_and_propagates(
    finished, monkeypatch, capsys, failure
):
    contest, _, _ = finished
    events = observe_writes(monkeypatch, failure)
    with pytest.raises(RuntimeError, match=f"{failure} failed"):
        app_module.generate_contest_results(contest.id)
    assert events == [("results", 1)] + (["commit"] if failure == "commit" else []) + ["rollback"]
    assert capsys.readouterr().out == ""
    assert ContestResult.query.count() == 0


@pytest.mark.parametrize("entry_point", ["task", "app.cli"])
def test_result_commit_failure_prevents_notification_commit(
    client, runner, finished, monkeypatch, entry_point
):
    contest, author, _ = finished
    events = observe_writes(monkeypatch, "commit")
    if entry_point == "task":
        with pytest.raises(RuntimeError, match="commit failed"):
            client.post(f"/api/tasks/contest/{contest.id}/result_announce")
    else:
        result = runner.invoke(args=["process-contests"])
        assert result.exit_code == 1
        assert str(result.exception) == "commit failed"
    assert events == [("results", 1), "commit", "rollback"]
    assert ContestResult.query.count() == 0
    assert Notification.query.count() == 0
    assert contest.notified_result_announce is False


def test_rounded_scores_define_tied_rank_and_advancement_cutoff(finished, user_factory):
    contest, author, first = finished
    contest.scoring_method = "judge"
    contest.advancement_numerator, contest.advancement_denominator = 1, 3
    second = Post(contest_id=contest.id, user_id=author.id, content="Second",
                  created_at=NOW + timedelta(seconds=1))
    third = Post(contest_id=contest.id, user_id=author.id, content="Third",
                 created_at=NOW + timedelta(seconds=2))
    judge = user_factory("judge")
    db.session.add_all([second, third])
    db.session.flush()
    db.session.add_all([
        Vote(contest_id=contest.id, post_id=first.id, user_id=judge.id, count=1.003, is_judge_vote=True),
        Vote(contest_id=contest.id, post_id=second.id, user_id=judge.id, count=1.004, is_judge_vote=True),
    ])
    db.session.commit()
    app_module.generate_contest_results(contest.id)
    rows = ContestResult.query.order_by(ContestResult.id).all()
    assert [(r.post_id, r.score, r.rank, r.is_advanced) for r in rows] == [
        (second.id, 1.0, 1, True), (first.id, 1.0, 1, True), (third.id, 0.0, 3, False),
    ]


@pytest.mark.parametrize("numerator,denominator,advanced", [(0, 2, False), (1, 0, False), (1, 2, False), (2, 2, True)])
def test_advancement_uses_integer_cutoff(finished, numerator, denominator, advanced):
    contest, _, post = finished
    contest.advancement_numerator, contest.advancement_denominator = numerator, denominator
    db.session.commit()
    app_module.generate_contest_results(contest.id)
    assert app_module.get_cached_contest_results(contest.id)[post.id]["is_advanced"] is advanced


@pytest.mark.parametrize("offset,status", [(timedelta(microseconds=-1), 403), (timedelta(0), 200)])
def test_empty_result_visibility_and_response_shape(client, contest_factory, fixed_time, monkeypatch, offset, status):
    contest = contest_factory(NOW, NOW, NOW, post_count=7, total_voters=8, total_judges=9)
    fixed_time(NOW + offset)
    events = observe_writes(monkeypatch)
    response = client.get(f"/api/contests/{contest.id}/results")
    assert response.status_code == status
    assert response.get_json() == ({"error": "Voting ongoing"} if status == 403 else {
        "contest": {"id": contest.id, "name": contest.name, "theme": None},
        "results": [], "judgeAwards": [], "totalPosters": 0, "totalVoters": 0,
    })
    assert events == []


def test_result_reads_saved_rank_and_score_and_keeps_unranked_posts_without_generating(
    client, finished, monkeypatch
):
    contest, author, first = finished
    second = Post(contest_id=contest.id, user_id=author.id, content="Second", created_at=NOW)
    third = Post(contest_id=contest.id, user_id=author.id, content="Third", created_at=NOW)
    db.session.add_all([second, third])
    db.session.flush()
    db.session.add(ContestResult(contest_id=contest.id, post_id=second.id, user_id=author.id,
                                score=42.5, rank=2, is_advanced=True))
    contest.post_count, contest.total_voters, contest.total_judges = 7, 8, 9
    db.session.commit()
    events = observe_writes(monkeypatch)
    response = client.get(f"/api/contests/{contest.id}/results")
    assert response.status_code == 200
    data = response.get_json()
    assert [r["post_id"] for r in data["results"]] == [second.id, first.id, third.id]
    assert [(r["rank"], r["score"], r["is_advanced"]) for r in data["results"]] == [
        (2, 42.5, True), (None, 0, False), (None, 0, False),
    ]
    assert (data["totalPosters"], data["totalVoters"], data["totalJudges"]) == (7, 8, 9)
    assert data["judgeAwards"] == []
    for row in data["results"]:
        assert row["created_at"] == "2026-01-01T21:00:00+09:00"
        assert row["images"] == row["voters"] == row["awards"] == []
        assert row["hasCommented"] is row["isBookmarked"] is False
    assert ContestResult.query.count() == 1
    assert events == []


def test_award_tab_keeps_foreign_contest_post_and_does_not_filter_judge_flag(
    client, finished, contest_factory, user_factory
):
    contest, author, local_post = finished
    foreign = contest_factory(NOW, NOW, NOW)
    foreign_post = Post(contest_id=foreign.id, user_id=author.id, content="Foreign", created_at=NOW)
    foreign_post.images = ["/static/uploads/foreign.png"]
    judge = user_factory("judge")
    db.session.add(foreign_post)
    db.session.flush()
    db.session.add(Vote(contest_id=contest.id, post_id=foreign_post.id, user_id=judge.id,
                        count=0, is_judge_vote=False, is_judge_award=True, judge_comment=" Award "))
    db.session.commit()
    response = client.get(f"/api/contests/{contest.id}/results")
    assert response.status_code == 200
    data = response.get_json()
    assert [r["post_id"] for r in data["results"]] == [local_post.id]
    assert data["results"][0]["awards"] == []
    assert data["judgeAwards"] == [{
        "judge": {"screen_name": "judge", "name": "judge", "profile_image_url": None},
        "comment": " Award ",
        "post": {"post_id": foreign_post.id, "content": "Foreign",
                 "images": ["/static/uploads/foreign.png"],
                 "user": {"screen_name": "author", "name": "author", "profile_image_url": None},
                 "created_at": "2026-01-01T21:00:00+09:00"},
    }]


def test_missing_result_contest_remains_generic_500_with_traceback(client, monkeypatch, capsys):
    events = observe_writes(monkeypatch)
    response = client.get("/api/contests/999/results")
    assert response.status_code == 500
    assert response.get_json() == {"error": "Error"}
    captured = capsys.readouterr()
    assert "404 Not Found" in captured.out
    assert "Traceback (most recent call last)" in captured.err
    assert events == []
