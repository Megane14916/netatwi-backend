"""Contest post listing and CRUD routes."""

import json
import logging
from datetime import datetime, timedelta, timezone

from flask import jsonify, request, session

from models import Bookmark, Comment, Contest, ContestResult, Notification, Post, Vote, db
from .dependencies import (
    allowed_file,
    calculate_weighted_length,
    delete_file,
    save_file,
)
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
    if not content and not files:
        return jsonify({"error": "Content or images required"}), 400

    # 画像枚数制限
    if len(files) > 4:
        return jsonify({"error": "Max 4 images allowed"}), 400

    try:
        c = Contest.query.get_or_404(id)
        now = datetime.now(timezone.utc)
        if not (
            c.start_time.replace(tzinfo=timezone.utc)
            <= now
            < c.end_time.replace(tzinfo=timezone.utc)
        ):
            return jsonify({"error": "Outside period"}), 403

        # 画像必須のバリデーション
        valid_files = [f for f in files if f and f.filename]
        if c.image_rule == "required" and len(valid_files) == 0:
            return jsonify({"error": "画像を最低1枚添付してください"}), 400

        # 決勝コンテストの場合の進出者チェック
        if c.parent_contest_id:
            qualifier_result = ContestResult.query.filter_by(
                contest_id=c.parent_contest_id, user_id=user_id
            ).first()
            if not qualifier_result or not qualifier_result.is_advanced:
                return jsonify(
                    {"error": "予選を通過していないため、この大会には投稿できません"}
                ), 403

        if Post.query.filter_by(user_id=user_id, contest_id=id).first():
            return jsonify({"error": "Already posted"}), 409

        # 画像アップロード処理
        image_urls = []
        for file in valid_files:
            if allowed_file(file.filename):
                url = save_file(file)
                image_urls.append(url)

        # Post作成 (images setter経由で保存)
        new_post = Post(content=content, contest_id=id, user_id=user_id)
        new_post.images = image_urls  # JSON化して保存される

        # カウンタのアトミックなインクリメント（レースコンディション対策）
        Contest.query.filter_by(id=id).update({"post_count": Contest.post_count + 1})

        db.session.add(new_post)
        db.session.commit()

        # レスポンス用データ
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

    if new_content:
        new_content = new_content.replace("\r\n", "\n").replace("\r", "\n")

    # テキストも画像もなければエラー（ただし画像全削除＆テキストありはOK）
    if not new_content and not kept_images and not files:
        return jsonify({"error": "No content"}), 400

    if new_content and calculate_weighted_length(new_content) > 280:
        return jsonify({"error": "Text too long (max 280)"}), 400

    try:
        post_to_edit = Post.query.filter_by(
            id=post_id, user_id=user_id, contest_id=contest_id
        ).first()
        if not post_to_edit:
            return jsonify({"error": "Not found"}), 404
        c = Contest.query.get(contest_id)
        now = datetime.now(timezone.utc)
        if not (
            c.start_time.replace(tzinfo=timezone.utc)
            <= now
            < c.end_time.replace(tzinfo=timezone.utc)
        ):
            return jsonify({"error": "Outside period"}), 403

        # 1. 既存画像 (old_images) の取得
        old_images = post_to_edit.images or []

        # 2. 新しい画像リスト (final_images) の構築
        final_images = []
        # 維持する画像 (kept_images) を追加
        if kept_images:
            final_images.extend(kept_images)

        # 新規アップロード画像を追加
        if files:
            for file in files:
                if file and allowed_file(file.filename):
                    url = save_file(file)
                    final_images.append(url)

        # 3. 削除された画像を特定してストレージから削除
        # old_images にはあるが、final_images にはないもの
        for old_url in old_images:
            if old_url not in final_images:
                delete_file(old_url)

        # 4. DB更新
        post_to_edit.content = new_content
        post_to_edit.images = final_images
        post_to_edit.updated_at = datetime.now(timezone.utc)

        db.session.commit()
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
        post_to_delete = Post.query.filter_by(
            id=post_id, user_id=user_id, contest_id=contest_id
        ).first()
        if not post_to_delete:
            return jsonify({"error": "Not found"}), 404

        c = Contest.query.get(contest_id)
        now = datetime.now(timezone.utc)
        if not (
            c.start_time.replace(tzinfo=timezone.utc)
            <= now
            < c.end_time.replace(tzinfo=timezone.utc)
        ):
            return jsonify({"error": "Outside period"}), 403

        if post_to_delete.images:
            for url in post_to_delete.images:
                try:
                    delete_file(url)
                except:
                    pass

        Vote.query.filter_by(post_id=post_id).delete()
        Comment.query.filter_by(post_id=post_id).delete()
        Notification.query.filter_by(post_id=post_id).delete()
        Bookmark.query.filter_by(post_id=post_id).delete()
        ContestResult.query.filter_by(post_id=post_id).delete()

        db.session.delete(post_to_delete)

        # 投稿数カウンタのアトミックなデクリメント
        Contest.query.filter(Contest.id == contest_id, Contest.post_count > 0).update(
            {"post_count": Contest.post_count - 1}
        )

        db.session.commit()
        return jsonify({"message": "Deleted successfully"}), 200
    except Exception as e:
        db.session.rollback()
        print(e)
        return jsonify({"error": "Error"}), 500
