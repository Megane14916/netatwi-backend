"""Notification listing and read-state routes."""

from flask import jsonify, session
from app.services import notifications as notifications_service
from .legacy import LegacyEndpointBlueprint


bp = LegacyEndpointBlueprint("notifications", __name__)


@bp.route("/api/notifications", methods=["GET"])
def get_notifications():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    return jsonify(notifications_service.get_notifications(user_id))


@bp.route("/api/notifications/unread-count", methods=["GET"])
def get_unread_notifications_count():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    return jsonify(notifications_service.get_unread_notifications_count(user_id))


@bp.route("/api/notifications/read", methods=["POST"])
def mark_notifications_read():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user_id = session["user_id"]

    return jsonify(notifications_service.mark_notifications_read(user_id))
