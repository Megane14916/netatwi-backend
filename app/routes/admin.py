"""Contest administration routes."""

from werkzeug.exceptions import HTTPException
from app.diagnostics import log_failure

import os

from flask import current_app, jsonify, request, session

from app.extensions import db
from app.integrations import cloud_tasks
from app.services import contest_lifecycle
from app.services import contests as contest_service
from app.services import policies
from app.services.validation import InputError, json_object
from flask import Blueprint


bp = Blueprint("admin", __name__)


def schedule_contest_task(*args):
    return cloud_tasks.schedule_contest_task(*args)


@bp.route("/api/admin/contests", methods=["POST"])
def create_contest():
    if not policies.is_authenticated(session):
        return jsonify({"error": "Login required"}), 401
    if not policies.is_admin(session):
        return jsonify({"error": "Forbidden: Admins only"}), 403

    data = json_object()
    try:
        result, status = contest_lifecycle.create_contest(data)
        return jsonify(result), status
    except InputError as error:
        return jsonify({"error": str(error)}), 400
    except HTTPException:
        raise
    except Exception as e:
        log_failure("admin.create_contest", e)
        db.session.rollback()
        return jsonify({"error": "Failed to create contest"}), 500


@bp.route("/api/admin/contests/management")
def get_management_contests():
    if not policies.is_authenticated(session):
        return jsonify({"error": "Login required"}), 401
    if not policies.is_admin(session):
        return jsonify({"error": "Forbidden: Admins only"}), 403

    try:
        return jsonify(contest_service.get_management_contests())
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        log_failure("admin.get_management_contests", e)
        return jsonify({"error": "Failed to fetch contests for management"}), 500


@bp.route("/api/admin/contests/<int:id>", methods=["PUT"])
def update_contest(id):
    if not policies.is_authenticated(session):
        return jsonify({"error": "Login required"}), 401
    if not policies.is_admin(session):
        return jsonify({"error": "Forbidden: Admins only"}), 403

    contest = contest_lifecycle.get_contest(id)
    if not contest:
        return jsonify({"error": "Contest not found"}), 404

    data = json_object()
    try:
        # 更新可能なフィールドの更新
        result, status = contest_lifecycle.update_contest(contest, data)
        return jsonify(result), status
    except InputError as error:
        return jsonify({"error": str(error)}), 400
    except HTTPException:
        raise
    except Exception as e:
        log_failure("admin.update_contest", e)
        db.session.rollback()
        return jsonify({"error": "Failed to update contest"}), 500


@bp.route("/api/admin/contests/<int:id>", methods=["DELETE"])
def delete_contest(id):
    if not policies.is_authenticated(session):
        return jsonify({"error": "Login required"}), 401
    if not policies.is_admin(session):
        return jsonify({"error": "Forbidden: Admins only"}), 403

    try:
        result, status = contest_lifecycle.delete_contest(id)
        return jsonify(result), status
    except HTTPException:
        raise
    except Exception as e:
        log_failure("admin.delete_contest", e)
        db.session.rollback()  # エラー時はロールバック
        return jsonify({"error": "大会の削除中にエラーが発生しました。"}), 500
