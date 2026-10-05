"""Public profile route."""

import traceback

from flask import jsonify, session

from app.services import profile as profile_service
from .legacy import LegacyEndpointBlueprint


bp = LegacyEndpointBlueprint("profile", __name__)


@bp.route("/api/profile/<string:screen_name>")
def get_user_profile_updated(screen_name):
    try:
        import time

        log_step = profile_service.prepare_profile_timing(time)
        viewer_id = session.get("user_id")
        payload, status = profile_service.get_user_profile(screen_name, viewer_id, log_step)
        return jsonify(payload), status

    except Exception as e:
        print(e)
        traceback.print_exc()
        return jsonify({"error": "Error"}), 500
