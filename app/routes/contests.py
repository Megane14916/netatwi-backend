"""Contest listing and details routes."""

from werkzeug.exceptions import HTTPException
from app.diagnostics import log_failure
from app.extensions import db

from flask import jsonify, session

from app.services import contests as contest_service
from flask import Blueprint


bp = Blueprint("contests", __name__)


@bp.route("/api/contests")
def get_contests():
    import time

    cache_hit, cached = contest_service.get_cached_contests(time)
    if cache_hit:
        return jsonify(cached)

    try:
        return jsonify(contest_service.get_contests(time))
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        log_failure("contests.get_contests", e)
        return jsonify({"error": "Failed"}), 500


@bp.route("/api/contests/<int:id>")
def get_contest_details(id):
    import time

    start_time = time.time()
    try:
        contest = contest_service.get_contest_for_details(id, start_time, time)
        user_id = session.get("user_id")
        return jsonify(contest_service.get_contest_details(contest, user_id, start_time, time))
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        log_failure("contests.get_contest_details", e)
        return jsonify({"error": "Internal server error"}), 500
