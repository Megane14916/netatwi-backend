"""Contest post listing and CRUD routes."""

from werkzeug.exceptions import HTTPException
from app.diagnostics import log_failure

import json
from datetime import timedelta, timezone

from flask import jsonify, request, session

from app.extensions import db
from app.services import posts as post_service
from app.services import contest_posts as contest_post_service
from app.services import policies
from app.services.validation import json_object
from flask import Blueprint


bp = Blueprint("posts", __name__)
JST = timezone(timedelta(hours=9), "JST")


@bp.route("/api/contests/<int:id>/posts")
def get_posts_for_contest(id):
    import time

    start_time = time.time()
    try:
        c, posts, t2 = contest_post_service.get_posts_for_listing(id, start_time, time)
        user_id = session.get("user_id")
        return jsonify(
            contest_post_service.get_posts_for_contest(id, c, posts, user_id, t2, start_time, time)
        )
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        log_failure("posts.get_posts_for_contest", e)
        return jsonify({"error": "Failed to fetch posts"}), 500


@bp.route("/api/contests/<int:id>/posts", methods=["POST"])
def submit_post(id):
    if not policies.is_authenticated(session):
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

    except HTTPException:
        raise
    except Exception as e:
        log_failure("posts.submit_post", e)
        db.session.rollback()
        return jsonify({"error": "Error"}), 500


@bp.route("/api/contests/<int:contest_id>/posts/<int:post_id>", methods=["PUT"])
def update_post(contest_id, post_id):
    if not policies.is_authenticated(session):
        return jsonify({"error": "Login required"}), 401
    user_id = session["user_id"]

    new_content = None

    # JSONとFormDataの判別
    if request.is_json:
        data = json_object()
        new_content = data.get("content")
        kept_images = data.get("kept_images", [])
        files = []
    else:
        new_content = request.form.get("content")
        kept_images_str = request.form.get("kept_images", "[]")
        try:
            kept_images = json.loads(kept_images_str)
        except json.JSONDecodeError:
            return jsonify({"error": "Invalid kept images"}), 400
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
    except HTTPException:
        raise
    except Exception as e:
        log_failure("posts.update_post", e)
        db.session.rollback()
        return jsonify({"error": "Error"}), 500


@bp.route("/api/contests/<int:contest_id>/posts/<int:post_id>", methods=["DELETE"])
def delete_post(contest_id, post_id):
    if not policies.is_authenticated(session):
        return jsonify({"error": "Login required"}), 401
    user_id = session["user_id"]
    try:
        result, status = post_service.delete_post(contest_id, post_id, user_id)
        return jsonify(result), status
    except HTTPException:
        raise
    except Exception as e:
        log_failure("posts.delete_post", e)
        db.session.rollback()
        return jsonify({"error": "Error"}), 500
