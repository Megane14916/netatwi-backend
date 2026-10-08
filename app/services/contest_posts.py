"""Contest post queries and viewer display data with original read ordering."""

from app.services.serialization import post_submission

from flask import current_app


from app.models import Contest, Post, Vote




def get_posts_for_listing(id, start_time, time):
    c = Contest.query.get_or_404(id)
    t1 = time.time()
    current_app.logger.info(f"[get_posts] get_or_404: {t1 - start_time:.4f}s")
    posts = (
        Post.query.filter_by(contest_id=id).order_by(Post.created_at.desc()).all()
    )
    t2 = time.time()
    current_app.logger.info(f"[get_posts] posts query: {t2 - t1:.4f}s")
    return c, posts, t2


def get_posts_for_contest(id, c, posts, user_id, t2, start_time, time):
    user_votes = {}
    user_has_voted = False
    user_votes_map = {}

    if user_id:
        votes = Vote.query.filter_by(user_id=user_id, contest_id=id).all()
        t3 = time.time()
        current_app.logger.info(f"[get_posts] votes query: {t3 - t2:.4f}s")
        user_votes = {vote.post_id: vote.count for vote in votes}
        if votes:
            user_has_voted = True
        for v in votes:
            user_votes_map[v.post_id] = {
                "count": v.count,
                "is_judge_award": v.is_judge_award,
                "judge_comment": v.judge_comment,
            }
        from app.models import Comment

        user_comments = Comment.query.filter(
            Comment.user_id == user_id, Comment.post_id.in_([p.id for p in posts])
        ).all()
        user_commented_post_ids = {c.post_id for c in user_comments}
        t4 = time.time()
        current_app.logger.info(f"[get_posts] comments query: {t4 - t3:.4f}s")
    else:
        user_commented_post_ids = set()
        t4 = time.time()

    total_posters = c.post_count
    t5 = time.time()
    current_app.logger.info(f"[get_posts] total_posters query: {t5 - t4:.4f}s")

    posts_data = []
    for post in posts:
        my_vote = user_votes_map.get(post.id, {})
        posts_data.append(
            {
                **post_submission(post),
                "myVotes": user_votes.get(post.id, None),
                "myJudgeAward": my_vote.get("is_judge_award", False),
                "myJudgeComment": my_vote.get("judge_comment", None),
                "hasCommented": post.id in user_commented_post_ids,
                "comment_count": post.comment_count,
            }
        )

    t6 = time.time()
    current_app.logger.info(f"[get_posts] loop formatting: {t6 - t5:.4f}s")
    current_app.logger.info(f"[get_posts] TOTAL TIME: {t6 - start_time:.4f}s")
    return (
        {
            "posts": posts_data,
            "userHasVotedInContest": user_has_voted,
            "totalPosters": total_posters,
        }
    )
    # --- ▲▲▲ ここまで ▲▲▲ ---
