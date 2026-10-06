"""Cloud Tasks HTTP handler."""

from flask import jsonify

from app.services import contest_lifecycle
from app.integrations.cloud_tasks import authenticate_task_request
from flask import Blueprint


bp = Blueprint("tasks", __name__)


@bp.route("/api/tasks/contest/<int:id>/<event_type>", methods=["POST"])
def handle_contest_task(id, event_type):
    error = authenticate_task_request()
    if error is not None:
        return jsonify(error[0]), error[1]
    result, status = contest_lifecycle.handle_contest_task(id, event_type)
    return jsonify(result), status
