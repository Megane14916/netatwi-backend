"""Persisted contest results used by both the task handler and CLI batch."""

from datetime import datetime, timezone

import pytest

from app import db, generate_contest_results, get_cached_contest_results
from models import ContestResult, Post, Vote


PAST = datetime(2025, 1, 1, tzinfo=timezone.utc)


def add_post(contest, user, position):
    post = Post(
        contest_id=contest.id,
        user_id=user.id,
        content=f"Post {position}",
        created_at=PAST.replace(minute=position),
    )
    db.session.add(post)
    db.session.commit()
    return post


@pytest.mark.parametrize(
    ("scoring_method", "expected_score"),
    [("user", 1.0), ("judge", 3.0), ("both", 53.0)],
)
def test_scoring_method_selects_persisted_score(
    app, contest_factory, user_factory, scoring_method, expected_score
):
    contest = contest_factory(
        PAST, PAST, PAST, scoring_method=scoring_method, general_vote_weight=50
    )
    winner = add_post(contest, user_factory("winner"), 1)
    other = add_post(contest, user_factory("other"), 2)
    general_voter = user_factory("general_voter")
    judge = user_factory("judge")
    db.session.add_all(
        [
            Vote(
                contest_id=contest.id,
                post_id=winner.id,
                user_id=general_voter.id,
                count=1,
                is_judge_vote=False,
            ),
            Vote(
                contest_id=contest.id,
                post_id=winner.id,
                user_id=judge.id,
                count=3,
                is_judge_vote=True,
            ),
        ]
    )
    db.session.commit()

    generate_contest_results(contest.id)
    results = get_cached_contest_results(contest.id)

    assert results[winner.id]["score"] == expected_score
    assert results[winner.id]["rank"] == 1
    assert results[other.id]["score"] == 0
    assert results[other.id]["rank"] == 2
    assert ContestResult.query.filter_by(contest_id=contest.id).count() == 2


def test_general_weight_uses_unique_voters_and_rounds(
    app, contest_factory, user_factory
):
    contest = contest_factory(PAST, PAST, PAST, general_vote_weight=50)
    first = add_post(contest, user_factory("first"), 1)
    second = add_post(contest, user_factory("second"), 2)
    voters = [user_factory(f"voter_{index}") for index in range(3)]
    for voter, post in zip(voters, [first, second, second]):
        db.session.add(
            Vote(
                contest_id=contest.id,
                post_id=post.id,
                user_id=voter.id,
                count=1,
                is_judge_vote=False,
            )
        )
    db.session.commit()

    generate_contest_results(contest.id)
    results = get_cached_contest_results(contest.id)

    assert results[first.id]["score"] == 16.67
    assert results[second.id]["score"] == 33.33


@pytest.mark.parametrize("award_advances", [False, True])
def test_tied_ranks_cutoff_judge_award_and_rerun(
    app, contest_factory, user_factory, award_advances
):
    contest = contest_factory(
        PAST,
        PAST,
        PAST,
        scoring_method="user",
        advancement_numerator=1,
        advancement_denominator=2,
        judge_award_advancement=award_advances,
    )
    posts = [
        add_post(contest, user_factory(f"author_{index}"), index)
        for index in range(1, 5)
    ]
    voters = [user_factory("voter_one"), user_factory("voter_two")]
    judge = user_factory("award_judge")
    db.session.add_all(
        [
            Vote(
                contest_id=contest.id,
                post_id=posts[index].id,
                user_id=voters[index].id,
                count=1,
                is_judge_vote=False,
            )
            for index in range(2)
        ]
        + [
            Vote(
                contest_id=contest.id,
                post_id=posts[2].id,
                user_id=judge.id,
                count=0,
                is_judge_vote=True,
                is_judge_award=True,
            )
        ]
    )
    db.session.commit()

    generate_contest_results(contest.id)
    original = get_cached_contest_results(contest.id)
    generate_contest_results(contest.id)

    assert [original[post.id]["rank"] for post in posts] == [1, 1, 3, 3]
    assert [original[post.id]["is_advanced"] for post in posts] == [
        True,
        True,
        award_advances,
        False,
    ]
    assert original[posts[2].id]["is_judge_award"] is True
    assert get_cached_contest_results(contest.id) == original
    assert ContestResult.query.filter_by(contest_id=contest.id).count() == 4
