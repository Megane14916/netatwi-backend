import pytest
from app import calculate_contest_results, db
from models import Contest, Post, User, Vote
from datetime import datetime, timezone

def test_calculate_contest_results_empty(app):
    with app.app_context():
        # 大会作成
        contest = Contest(
            name="Test Contest",
            start_time=datetime.now(timezone.utc),
            end_time=datetime.now(timezone.utc),
            voting_end_time=datetime.now(timezone.utc),
            scoring_method="general"
        )
        db.session.add(contest)
        db.session.commit()
        
        # 投稿ゼロの場合
        results = calculate_contest_results(contest.id)
        
        assert results is not None
        assert len(results) == 0

def test_calculate_contest_results_basic(app):
    with app.app_context():
        contest = Contest(
            name="Test Contest 2",
            start_time=datetime.now(timezone.utc),
            end_time=datetime.now(timezone.utc),
            voting_end_time=datetime.now(timezone.utc),
            scoring_method="general"
        )
        user1 = User(twitter_id="111", screen_name="user1", name="User 1")
        user2 = User(twitter_id="222", screen_name="user2", name="User 2")
        db.session.add_all([contest, user1, user2])
        db.session.commit()
        
        post1 = Post(content="Hello", user_id=user1.id, contest_id=contest.id)
        post2 = Post(content="World", user_id=user2.id, contest_id=contest.id)
        db.session.add_all([post1, post2])
        db.session.commit()
        
        vote = Vote(post_id=post1.id, user_id=user2.id, contest_id=contest.id, count=1, is_judge_vote=False)
        db.session.add(vote)
        db.session.commit()
        
        results = calculate_contest_results(contest.id)
        
        assert post1.id in results
        assert post2.id in results
        assert results[post1.id]['score'] == 50.0
        assert results[post2.id]['score'] == 0
        assert results[post1.id]['rank'] == 1
        assert results[post2.id]['rank'] == 2
