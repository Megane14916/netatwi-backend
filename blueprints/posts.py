"""Contest post listing and CRUD routes."""

import json
import logging
from datetime import timedelta, timezone

from flask import jsonify, request, session

from models import Contest, Post, Vote, db
from services import posts as post_service
from .legacy import LegacyEndpointBlueprint


bp = LegacyEndpointBlueprint("posts", __name__)
logger = logging.getLogger("app")
JST = timezone(timedelta(hours=9), "JST")


@bp.route("/api/contests/<int:id>/posts")
def get_posts_for_contest(id):
    import time

    start_time = time.time()
    try:
        c = Contest.query.get_or_404(id)
        t1 = time.time()
        logger.info(f"[get_posts] get_or_404: {t1 - start_time:.4f}s")
        posts = (
            Post.query.filter_by(contest_id=id).order_by(Post.created_at.desc()).all()
        )
        t2 = time.time()
        logger.info(f"[get_posts] posts query: {t2 - t1:.4f}s")

        user_id = session.get("user_id")
        user_votes = {}
        user_has_voted = False
        user_votes_map = {}

        if user_id:
            votes = Vote.query.filter_by(user_id=user_id, contest_id=id).all()
            t3 = time.time()
            logger.info(f"[get_posts] votes query: {t3 - t2:.4f}s")
            user_votes = {vote.post_id: vote.count for vote in votes}
            if votes:
                user_has_voted = True
            for v in votes:
                user_votes_map[v.post_id] = {
                    "count": v.count,
                    "is_judge_award": v.is_judge_award,
                    "judge_comment": v.judge_comment,
                }
            from models import Comment

            user_comments = Comment.query.filter(
                Comment.user_id == user_id, Comment.post_id.in_([p.id for p in posts])
            ).all()
            user_commented_post_ids = {c.post_id for c in user_comments}
            t4 = time.time()
            logger.info(f"[get_posts] comments query: {t4 - t3:.4f}s")
        else:
            user_commented_post_ids = set()
            t4 = time.time()

        total_posters = c.post_count
        t5 = time.time()
        logger.info(f"[get_posts] total_posters query: {t5 - t4:.4f}s")

        posts_data = []
        for post in posts:
            my_vote = user_votes_map.get(post.id, {})
            posts_data.append(
                {
                    "id": post.id,
                    "content": post.content,
                    "created_at": post.created_at.replace(tzinfo=timezone.utc)
                    .astimezone(JST)
                    .isoformat(),
                    "user_id": post.user_id,
                    "myVotes": user_votes.get(post.id, None),
                    "images": post.images,
                    "myJudgeAward": my_vote.get("is_judge_award", False),
                    "myJudgeComment": my_vote.get("judge_comment", None),
                    "hasCommented": post.id in user_commented_post_ids,
                    "comment_count": post.comment_count,
                }
            )

        t6 = time.time()
        logger.info(f"[get_posts] loop formatting: {t6 - t5:.4f}s")
        logger.info(f"[get_posts] TOTAL TIME: {t6 - start_time:.4f}s")
        return jsonify(
            {
                "posts": posts_data,
                "userHasVotedInContest": user_has_voted,
                "totalPosters": total_posters,
            }
        )
        # --- ▲▲▲ ここまで ▲▲▲ ---
    except Exception as e:
        print(f"!!! ERROR at GET /api/contests/{id}/posts: {e}")
        return jsonify({"error": "Failed to fetch posts"}), 500


@bp.route("/api/contests/<int:id>/posts", methods=["POST"])
def submit_post(id):
    if "user_id" not in session:
        return jsonify({"error": "Login required"}), 401
    user_id = session["user_id"]

    # FormDataで来るため request.form と request.files を使う
    content = request.form.get("content", "")
    files = request.files.getlist("images")  # 複数ファイル

    # バリデーション: テキストも画像もなければエラー
    error = post_service.validate_submission(content, files)
    if error is not None:
        return jsonify(error[0]), error[1]

    try:
        result, status = post_service.submit_post(id, user_id, content, files)
        if status != 201:
            return jsonify(result), status
        new_post = result

        return jsonify(
            {
                "id": new_post.id,
                "content": new_post.content,
                "images": new_post.images,
                "created_at": new_post.created_at.replace(tzinfo=timezone.utc)
                .astimezone(JST)
                .isoformat(),
                "user_id": new_post.user_id,
            }
        ), 201

    except Exception as e:
        db.session.rollback()
        print(f"Error: {e}")
        return jsonify({"error": "Error"}), 500


@bp.route("/api/contests/<int:contest_id>/posts/<int:post_id>", methods=["PUT"])
def update_post(contest_id, post_id):
    if "user_id" not in session:
        return jsonify({"error": "Login required"}), 401
    user_id = session["user_id"]

    new_content = None

    # JSONとFormDataの判別
    if request.content_type and request.content_type.startswith("application/json"):
        data = request.get_json()
        new_content = data.get("content")
        kept_images = data.get("kept_images", [])
        files = []
    else:
        new_content = request.form.get("content")
        kept_images_str = request.form.get("kept_images", "[]")
        try:
            kept_images = json.loads(kept_images_str)
        except:
            kept_images = []
        files = request.files.getlist("images")

    new_content, error = post_service.prepare_update(new_content, kept_images, files)
    if error is not None:
        return jsonify(error[0]), error[1]

    try:
        result, status = post_service.update_post(
            contest_id, post_id, user_id, new_content, kept_images, files
        )
        if status != 200:
            return jsonify(result), status
        post_to_edit = result

        return jsonify(
            {
                "id": post_to_edit.id,
                "content": post_to_edit.content,
                "images": post_to_edit.images,
                "created_at": post_to_edit.created_at.replace(tzinfo=timezone.utc)
                .astimezone(JST)
                .isoformat(),
                "user_id": post_to_edit.user_id,
                "myVotes": None,
            }
        ), 200
    except Exception as e:
        db.session.rollback()
        print(e)
        return jsonify({"error": "Error"}), 500


@bp.route("/api/contests/<int:contest_id>/posts/<int:post_id>", methods=["DELETE"])
def delete_post(contest_id, post_id):
    if "user_id" not in session:
        return jsonify({"error": "Login required"}), 401
    user_id = session["user_id"]
    try:
        result, status = post_service.delete_post(contest_id, post_id, user_id)
        return jsonify(result), status
    except Exception as e:
        db.session.rollback()
        print(e)
        return jsonify({"error": "Error"}), 500
