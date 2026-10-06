"""Comment listing and mutation routes."""

from flask import jsonify, request, session

from app.services import comments as comments_service
from flask import Blueprint


bp = Blueprint("comments", __name__)


@bp.route("/api/posts/<int:post_id>/comments", methods=["GET"])
def get_comments(post_id):
    return jsonify(comments_service.get_comments(post_id))


@bp.route("/api/comments", methods=["GET"])
def get_multiple_comments():
    post_ids_param = request.args.get("postIds", "")
    if not post_ids_param:
        return jsonify({})

    try:
        post_ids = [int(pid) for pid in post_ids_param.split(",")]
    except ValueError:
        return jsonify({"error": "Invalid postIds format"}), 400
    return jsonify(comments_service.get_multiple_comments(post_ids))


@bp.route("/api/posts/<int:post_id>/comments", methods=["POST"])
def add_comment(post_id):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    post = comments_service.get_post(post_id)
    data = request.get_json()
    raw_content = data.get("content", "")

    judge_contests = session.get("judge_for_contest_ids", [])
    result, status = comments_service.add_comment(
        post_id, user_id, post, raw_content, judge_contests
    )
    return jsonify(result), status


@bp.route("/api/comments/<int:comment_id>", methods=["PUT", "DELETE"])
def modify_comment(comment_id):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    comment, status = comments_service.get_comment_for_modification(comment_id, user_id)
    if status != 200:
        return jsonify(comment), status

    if request.method == "DELETE":
        result, status = comments_service.delete_comment(comment)
        return jsonify(result), status

    data = request.get_json()
    raw_content = data.get("content", "")
    result, status = comments_service.update_comment(comment, raw_content)
    return jsonify(result), status
