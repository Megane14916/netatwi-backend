"""Public user directory routes."""

from flask import jsonify, request

from app.services import users as user_service
from .legacy import LegacyEndpointBlueprint


bp = LegacyEndpointBlueprint("users", __name__)


@bp.route("/api/users", methods=["GET"])
def get_users_list():
    User, UserStats, asc = user_service.get_directory_dependencies()

    search_query = request.args.get("q", "")
    page = request.args.get("page", 1, type=int)
    payload, status = user_service.get_users_list(search_query, page, User, UserStats, asc)
    return jsonify(payload), status
