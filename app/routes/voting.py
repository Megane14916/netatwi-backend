"""Bulk voting routes."""

from flask import jsonify, request, session

from app.extensions import db
from app.services import voting as voting_service
from flask import current_app
from app.services import policies
from app.services.validation import json_object
from flask import Blueprint


bp = Blueprint("voting", __name__)


@bp.route("/api/contests/<int:id>/vote", methods=["POST"])
def submit_votes(id):
    import time

    start_time = time.time()
    current_app.logger.info(f"==> [submit_votes] START for contest {id}")
    if not policies.is_authenticated(session):
        return jsonify({"error": "Login required"}), 401

    user_id = session["user_id"]
    data = json_object()
    votes_to_submit = data.get("votes")  # { "postId": count }
    judge_award = data.get("judgeAward")  # { "postId": 123, "comment": "..." } or null
    content = request.form.get("content", "")

    error = voting_service.validate_votes(content, votes_to_submit)
    if error is not None:
        return jsonify(error[0]), error[1]

    try:
        is_judge = policies.is_judge(id, session.get("judge_for_contest_ids", []))
        judge_contest_ids = session.get("judge_for_contest_ids", [])
        is_judge_voting_now = policies.is_judge(id, judge_contest_ids)

        result, status = voting_service.submit_votes(
            id, user_id, votes_to_submit, judge_award, is_judge, is_judge_voting_now,
            start_time,
        )
        return jsonify(result), status
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(
            f"==> [submit_votes] ERROR in {time.time() - start_time:.4f}s: {e}"
        )
        print(f"Error: {e}")
        return jsonify({"error": "Error"}), 500
