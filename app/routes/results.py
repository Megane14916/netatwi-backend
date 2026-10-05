"""Contest result presentation routes."""

import traceback

from flask import jsonify, session

from app.services import results as results_service
from .legacy import LegacyEndpointBlueprint


bp = LegacyEndpointBlueprint("results", __name__)


@bp.route("/api/contests/<int:id>/results")
def get_contest_results(id):
    try:
        user_id = session.get("user_id")
        result, status = results_service.get_contest_results(id, user_id)
        return jsonify(result), status
    except Exception as e:
        print(e)
        traceback.print_exc()
        return jsonify({"error": "Error"}), 500
