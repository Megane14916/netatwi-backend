"""Contest listing and details routes."""

from flask import jsonify, session

from services import contests as contest_service
from .legacy import LegacyEndpointBlueprint


bp = LegacyEndpointBlueprint("contests", __name__)


@bp.route("/api/contests")
def get_contests():
    import time

    cache_hit, cached = contest_service.get_cached_contests(time)
    if cache_hit:
        return jsonify(cached)

    try:
        return jsonify(contest_service.get_contests(time))
    except Exception as e:
        return jsonify({"error": "Failed"}), 500


@bp.route("/api/contests/<int:id>")
def get_contest_details(id):
    import time

    start_time = time.time()
    try:
        contest = contest_service.get_contest_for_details(id, start_time, time)
        user_id = session.get("user_id")
        return jsonify(contest_service.get_contest_details(contest, user_id, start_time, time))
    except Exception as e:
        print(f"!!! ERROR at /api/contests/{id}: {e}")
        return jsonify({"error": "Contest not found"}), 404
