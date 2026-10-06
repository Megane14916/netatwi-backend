"""Bookmark and like routes."""

import traceback

from flask import jsonify, request, session
from sqlalchemy.exc import IntegrityError

from app.models import db
from app.services import interactions as interaction_service
from flask import Blueprint


bp = Blueprint("interactions", __name__)


@bp.route("/api/posts/<int:post_id>/bookmark", methods=["PUT", "DELETE"])
def set_bookmark(post_id):
    if "user_id" not in session:
        return jsonify({"error": "ログインが必要です。"}), 401
    user_id = session["user_id"]
    try:
        post, status = interaction_service.get_bookmark_post(post_id)
        if status != 200:
            return jsonify(post), status
        is_bookmarked = request.method == "PUT"
        result, status = interaction_service.set_bookmark(post_id, user_id, post, is_bookmarked)
        return jsonify(result), status
    except IntegrityError:
        db.session.rollback()
        # A concurrent PUT may have inserted the bookmark. Treat that as the
        # requested final state rather than returning a 500 error.
        if request.method == "PUT":
            recovered = interaction_service.recover_bookmark(post_id)
            if recovered is not None:
                return jsonify(recovered[0]), recovered[1]
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
        post, c, status = interaction_service.prepare_like(post_id, user_id)
        if status != 200:
            return jsonify(post), status
        is_liked = request.method == "PUT"
        result, status = interaction_service.set_like(post_id, user_id, post, c, is_liked)
        return jsonify(result), status
    except IntegrityError:
        db.session.rollback()
        # Another concurrent PUT won the unique (user_id, post_id) race.
        # Return the resulting state instead of exposing a 500 to the client.
        result, status = interaction_service.recover_like(post_id, user_id)
        return jsonify(result), status
    except Exception as e:
        db.session.rollback()
        print(f"Error toggling like: {e}")
        return jsonify({"error": "いいね処理中にエラーが発生しました。"}), 500
