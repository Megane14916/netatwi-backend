"""Bookmark and like routes."""

import traceback
from datetime import datetime, timezone

from flask import jsonify, request, session
from sqlalchemy.exc import IntegrityError

from models import Bookmark, Notification, Post, Vote, db
from .legacy import LegacyEndpointBlueprint


bp = LegacyEndpointBlueprint("interactions", __name__)


@bp.route("/api/posts/<int:post_id>/bookmark", methods=["PUT", "DELETE"])
def set_bookmark(post_id):
    if "user_id" not in session:
        return jsonify({"error": "ログインが必要です。"}), 401
    user_id = session["user_id"]
    try:
        post = Post.query.get(post_id)
        if not post:
            return jsonify({"error": "投稿が見つかりません。"}), 404
        is_bookmarked = request.method == "PUT"
        existing_bookmark = Bookmark.query.filter_by(
            user_id=user_id, post_id=post_id
        ).first()

        if is_bookmarked and not existing_bookmark:
            new_bookmark = Bookmark(user_id=user_id, post_id=post_id)
            db.session.add(new_bookmark)
        elif not is_bookmarked and existing_bookmark:
            db.session.delete(existing_bookmark)

        db.session.commit()

        # Recalculate from the source rows instead of blindly incrementing or
        # decrementing a cached counter. This keeps repeated PUT/DELETE calls
        # idempotent and prevents the counter from becoming negative.
        post.bookmark_count = Bookmark.query.filter_by(post_id=post_id).count()
        db.session.commit()
        db.session.refresh(post)

        return jsonify(
            {
                "message": "ブックマークを更新しました。",
                "isBookmarked": is_bookmarked,
                "bookmarkCount": post.bookmark_count,
            }
        ), 200
    except IntegrityError:
        db.session.rollback()
        # A concurrent PUT may have inserted the bookmark. Treat that as the
        # requested final state rather than returning a 500 error.
        if request.method == "PUT":
            post = Post.query.get(post_id)
            if post:
                return jsonify({
                    "message": "ブックマークを更新しました。",
                    "isBookmarked": True,
                    "bookmarkCount": Bookmark.query.filter_by(post_id=post_id).count(),
                }), 200
        return jsonify({"error": "ブックマーク処理中にエラーが発生しました。"}), 500
    except Exception as e:
        db.session.rollback()
        print(f"!!! ERROR at POST /api/posts/{post_id}/bookmark: {e}")
        traceback.print_exc()
        return jsonify({"error": "ブックマーク処理中にエラーが発生しました。"}), 500


@bp.route("/api/posts/<int:post_id>/like", methods=["PUT", "DELETE"])
def set_like(post_id):
    if "user_id" not in session:
        return jsonify({"error": "Login required"}), 401
    user_id = session["user_id"]

    try:
        post = Post.query.get_or_404(post_id)

        if post.user_id == user_id:
            return jsonify({"error": "Cannot like your own post."}), 403

        c = post.contest
        now = datetime.now(timezone.utc)

        # 投票期間中の一般投票は一括APIを使用するため禁止
        if now < c.voting_end_time.replace(tzinfo=timezone.utc):
            return jsonify({"error": "Voting is ongoing, use the bulk vote API."}), 403

        # 審査員のみの大会以外は結果発表後のいいねを禁止（スコアと混同するため）
        if c.scoring_method != "judge":
            return jsonify(
                {"error": "Cannot like during results when user voting is enabled."}
            ), 403

        is_liked = request.method == "PUT"
        existing_vote = Vote.query.filter_by(user_id=user_id, post_id=post_id).first()

        if is_liked and existing_vote:
            if existing_vote.is_judge_vote:
                return jsonify(
                    {"error": "審査員として採点済みのため、いいねは追加できません。"}
                ), 400
            # The requested state is already true; do not create a duplicate
            # notification or mutate the vote on an idempotent PUT.
            is_liked = True
        elif not is_liked and existing_vote:
            if existing_vote.is_judge_vote:
                return jsonify(
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
            if user_id != post.user_id:
                notification = Notification(
                    user_id=post.user_id,
                    sender_id=user_id,
                    type="like",
                    post_id=post_id,
                    contest_id=c.id,
                )
                db.session.add(notification)

        db.session.commit()

        # 最新のいいね数
        like_count = Vote.query.filter_by(
            post_id=post_id, is_judge_vote=False, count=1
        ).count()
        return jsonify({"isLiked": is_liked, "likeCount": like_count}), 200
    except IntegrityError:
        db.session.rollback()
        # Another concurrent PUT won the unique (user_id, post_id) race.
        # Return the resulting state instead of exposing a 500 to the client.
        existing_vote = Vote.query.filter_by(user_id=user_id, post_id=post_id).first()
        like_count = Vote.query.filter_by(
            post_id=post_id, is_judge_vote=False, count=1
        ).count()
        return jsonify({
            "isLiked": existing_vote is not None and not existing_vote.is_judge_vote,
            "likeCount": like_count,
        }), 200
    except Exception as e:
        db.session.rollback()
        print(f"Error toggling like: {e}")
        return jsonify({"error": "いいね処理中にエラーが発生しました。"}), 500
