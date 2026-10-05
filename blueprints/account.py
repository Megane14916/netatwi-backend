"""Current session, logout and withdrawal routes."""

import os

from flask import jsonify, session
from services import users as user_service
from .legacy import LegacyEndpointBlueprint


bp = LegacyEndpointBlueprint("account", __name__)


@bp.route("/api/me")
def get_current_user():
    user_data = {"logged_in": False}
    if "user_id" in session:
        user_data["logged_in"] = True
        user_data["user"] = {
            "id": session["user_id"],
            "screen_name": session["screen_name"],
            "name": session.get("name"),
            "profile_image_url": session.get("profile_image_url"),
            "isAdmin": session["screen_name"]
            in [
                s.strip()
                for s in os.environ.get(
                    "ADMIN_SCREEN_NAMES", "dummy_admin1,dummy_admin2"
                ).split(",")
                if s.strip()
            ],
        }
        # --- ▼▼▼ set ではなく list を使うように修正 ▼▼▼ ---
        # セッションから 'judge_for_contest_ids' をリストとして取得 (なければ空のリスト)
        judge_contest_ids = session.get("judge_for_contest_ids", [])
        user_data["judge_contests"] = judge_contest_ids  # リストをそのまま返す
        # --- ▲▲▲ ここまで ▲▲▲ ---
    return jsonify(user_data)


@bp.route("/api/logout")
def logout():
    session.clear()
    return jsonify({"message": "Logged out successfully"})


@bp.route("/api/users/me", methods=["DELETE"])
def withdraw_user():
    if "user_id" not in session:
        return jsonify({"error": "Login required"}), 401

    user_id = session["user_id"]
    error = user_service.withdraw_user(user_id)
    if error is not None:
        return jsonify(error[0]), error[1]

    session.clear()
    return jsonify({"message": "退会処理が完了しました"})
