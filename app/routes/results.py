"""Contest result presentation routes."""

from werkzeug.exceptions import HTTPException
from app.diagnostics import log_failure
from app.extensions import db


from flask import jsonify, session

from app.services import results as results_service
from flask import Blueprint


bp = Blueprint("results", __name__)


@bp.route("/api/contests/<int:id>/results")
def get_contest_results(id):
    try:
        user_id = session.get("user_id")
        result, status = results_service.get_contest_results(id, user_id)
        return jsonify(result), status
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        log_failure("results.get_contest_results", e)
        return jsonify({"error": "Error"}), 500
