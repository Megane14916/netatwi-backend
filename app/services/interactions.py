"""Bookmark and like queries, validation, mutations and conflict recovery."""

from datetime import datetime, timezone

from app.services import policies
from app.extensions import db
from app.models import Bookmark, Post, Vote
from app.services import notifications as notifications_service


def get_bookmark_post(post_id):
    post = Post.query.get(post_id)
    if not post:
        return ({"error": "投稿が見つかりません。"}), 404
    return post, 200


def set_bookmark(post_id, user_id, post, is_bookmarked):
    existing_bookmark = Bookmark.query.filter_by(
        user_id=user_id, post_id=post_id
    ).first()

    if is_bookmarked and not existing_bookmark:
        new_bookmark = Bookmark(user_id=user_id, post_id=post_id)
        db.session.add(new_bookmark)
    elif not is_bookmarked and existing_bookmark:
        db.session.delete(existing_bookmark)

    db.session.flush()

    # Recalculate from the source rows instead of blindly incrementing or
    # decrementing a cached counter. This keeps repeated PUT/DELETE calls
    # idempotent and prevents the counter from becoming negative.
    bookmark_count = Bookmark.query.filter_by(post_id=post_id).count()
    post.bookmark_count = bookmark_count
    db.session.commit()

    return (
        {
            "message": "ブックマークを更新しました。",
            "isBookmarked": is_bookmarked,
            "bookmarkCount": bookmark_count,
        }
    ), 200


def recover_bookmark(post_id):
    post = Post.query.get(post_id)
    if post:
        return ({
            "message": "ブックマークを更新しました。",
            "isBookmarked": True,
            "bookmarkCount": Bookmark.query.filter_by(post_id=post_id).count(),
        }), 200


def prepare_like(post_id, user_id):
    post = Post.query.get_or_404(post_id)

    if policies.is_owner(post, user_id):
        return ({"error": "Cannot like your own post."}), None, 403

    c = post.contest
    now = datetime.now(timezone.utc)

    # 投票期間中の一般投票は一括APIを使用するため禁止
    if not policies.has_reached(now, c.voting_end_time):
        return ({"error": "Voting is ongoing, use the bulk vote API."}), None, 403

    # 審査員のみの大会以外は結果発表後のいいねを禁止（スコアと混同するため）
    if c.scoring_method != "judge":
        return (
            {"error": "Cannot like during results when user voting is enabled."}
        ), None, 403
    return post, c, 200


def set_like(post_id, user_id, post, c, is_liked):
    existing_vote = Vote.query.filter_by(user_id=user_id, post_id=post_id).first()

    if is_liked and existing_vote:
        if existing_vote.is_judge_vote:
            return (
                {"error": "審査員として採点済みのため、いいねは追加できません。"}
            ), 400
        # The requested state is already true; do not create a duplicate
        # notification or mutate the vote on an idempotent PUT.
        is_liked = True
    elif not is_liked and existing_vote:
        if existing_vote.is_judge_vote:
            return (
                {"error": "審査員として採点済みのため、いいねは追加できません。"}
            ), 400
        db.session.delete(existing_vote)
        is_liked = False
    elif is_liked:
        new_vote = Vote(
            user_id=user_id,
            post_id=post_id,
            contest_id=c.id,
            count=1,
            is_judge_vote=False,
            is_judge_award=False,
        )
        db.session.add(new_vote)
        # 通知生成
        notifications_service.create_like_notification(post, post_id, user_id, c)

    db.session.flush()

    # 最新のいいね数
    like_count = Vote.query.filter_by(
        post_id=post_id, is_judge_vote=False, count=1
    ).count()
    db.session.commit()
    return ({"isLiked": is_liked, "likeCount": like_count}), 200


def recover_like(post_id, user_id):
    existing_vote = Vote.query.filter_by(user_id=user_id, post_id=post_id).first()
    like_count = Vote.query.filter_by(
        post_id=post_id, is_judge_vote=False, count=1
    ).count()
    return ({
        "isLiked": existing_vote is not None and not existing_vote.is_judge_vote,
        "likeCount": like_count,
    }), 200
