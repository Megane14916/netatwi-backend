"""Public profile route."""

from werkzeug.exceptions import HTTPException
from app.diagnostics import log_failure
from app.extensions import db


from flask import jsonify, session

from app.services import profile as profile_service
from flask import Blueprint


bp = Blueprint("profile", __name__)


@bp.route("/api/profile/<string:screen_name>")
def get_user_profile_updated(screen_name):
    try:
        import time

        log_step = profile_service.prepare_profile_timing(time)
        viewer_id = session.get("user_id")
        payload, status = profile_service.get_user_profile(screen_name, viewer_id, log_step)
        return jsonify(payload), status

    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        log_failure("profile.get_user_profile_updated", e)
        return jsonify({"error": "Error"}), 500
