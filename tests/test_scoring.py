from datetime import datetime, timezone

from app import db, generate_contest_results, get_cached_contest_results
from models import Contest, ContestResult, Post, User, Vote


def make_contest(name):
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return Contest(
        name=name,
        start_time=now,
        end_time=now,
        voting_end_time=now,
        scoring_method="both",
        general_vote_weight=50,
    )


def test_generate_contest_results_empty(app):
    contest = make_contest("Empty contest")
    db.session.add(contest)
    db.session.commit()

    generate_contest_results(contest.id)

    assert get_cached_contest_results(contest.id) == {}
    assert ContestResult.query.filter_by(contest_id=contest.id).count() == 0


def test_generate_contest_results_basic(app):
    contest = make_contest("Two posts")
    user1 = User(twitter_id="111", screen_name="user1", name="User 1")
    user2 = User(twitter_id="222", screen_name="user2", name="User 2")
    db.session.add_all([contest, user1, user2])
    db.session.commit()

    post1 = Post(content="Hello", user_id=user1.id, contest_id=contest.id)
    post2 = Post(content="World", user_id=user2.id, contest_id=contest.id)
    db.session.add_all([post1, post2])
    db.session.commit()
    db.session.add(
        Vote(
            post_id=post1.id,
            user_id=user2.id,
            contest_id=contest.id,
            count=1,
            is_judge_vote=False,
        )
    )
    db.session.commit()

    generate_contest_results(contest.id)
    results = get_cached_contest_results(contest.id)

    assert set(results) == {post1.id, post2.id}
    assert results[post1.id]["score"] == 50.0
    assert results[post2.id]["score"] == 0
    assert results[post1.id]["rank"] == 1
    assert results[post2.id]["rank"] == 2
