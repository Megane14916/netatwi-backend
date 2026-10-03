"""Cloud Tasks HTTP handler."""

from flask import jsonify

from services import contest_lifecycle
from .legacy import LegacyEndpointBlueprint


bp = LegacyEndpointBlueprint("tasks", __name__)


@bp.route("/api/tasks/contest/<int:id>/<event_type>", methods=["POST"])
def handle_contest_task(id, event_type):
    # Security note: In a real app, verify the request comes from Cloud Tasks (e.g. OIDC token)
    result, status = contest_lifecycle.handle_contest_task(id, event_type)
    return jsonify(result), status
