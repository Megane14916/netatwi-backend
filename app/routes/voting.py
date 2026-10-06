"""Bulk voting routes."""

from flask import jsonify, request, session

from app.models import db
from app.services import voting as voting_service
from app.runtime_dependencies import route_logger as logger
from flask import Blueprint


bp = Blueprint("voting", __name__)


@bp.route("/api/contests/<int:id>/vote", methods=["POST"])
def submit_votes(id):
    import time

    start_time = time.time()
    logger.info(f"==> [submit_votes] START for contest {id}")
    if "user_id" not in session:
        return jsonify({"error": "Login required"}), 401

    user_id = session["user_id"]
    data = request.get_json()
    votes_to_submit = data.get("votes")  # { "postId": count }
    judge_award = data.get("judgeAward")  # { "postId": 123, "comment": "..." } or null
    content = request.form.get("content", "")

    error = voting_service.validate_votes(content, votes_to_submit)
    if error is not None:
        return jsonify(error[0]), error[1]

    try:
        is_judge = id in session.get("judge_for_contest_ids", [])
        judge_contest_ids = session.get("judge_for_contest_ids", [])
        is_judge_voting_now = id in judge_contest_ids

        result, status = voting_service.submit_votes(
            id, user_id, votes_to_submit, judge_award, is_judge, is_judge_voting_now,
            start_time,
        )
        return jsonify(result), status
    except Exception as e:
        db.session.rollback()
        logger.error(
            f"==> [submit_votes] ERROR in {time.time() - start_time:.4f}s: {e}"
        )
        print(f"Error: {e}")
        return jsonify({"error": "Error"}), 500
