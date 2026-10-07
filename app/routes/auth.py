"""HTTP input/output for X OAuth and judge authentication."""

import traceback

from flask import current_app, jsonify, redirect, request, session

from app.extensions import limiter
from app.extensions import db
from app.services import auth as auth_service
from app.services import policies
from flask import Blueprint


bp = Blueprint("auth", __name__)


@bp.route("/api/login/twitter")
def twitter_login():
    try:
        authorization_url = auth_service.start_twitter_login()
        return jsonify({"authorization_url": authorization_url})
    except Exception as e:
        current_app.logger.error("X authorization failed; exception_type=%s", type(e).__name__)
        return jsonify({"error": "Failed to connect to Twitter"}), 500


@bp.route("/api/callback/twitter")
def twitter_callback():
    session_state, code_verifier = auth_service.begin_twitter_callback()

    url_state = request.args.get("state")
    code = request.args.get("code")
    error = request.args.get("error")

    failure_reason = auth_service.validate_twitter_callback(
        session_state, code_verifier, url_state, code, error
    )
    if failure_reason is not None:
        return redirect(f"{current_app.config['FRONTEND_URL']}?login_error={failure_reason}")

    try:
        failure_reason = auth_service.complete_twitter_login(session_state, code_verifier, code)
        if failure_reason is not None:
            return redirect(f"{current_app.config['FRONTEND_URL']}?login_error={failure_reason}")
    except Exception as e:
        current_app.logger.error("X callback failed; exception_type=%s", type(e).__name__)
        db.session.rollback()
        return redirect(f"{current_app.config['FRONTEND_URL']}?login_error=callback_failed")

    return redirect(current_app.config["FRONTEND_URL"])


@bp.route("/api/contests/<int:id>/judge/login", methods=["POST"])
@limiter.limit("5 per minute")
def judge_login(id):
    if not policies.is_authenticated(session):
        return jsonify({"error": "ログインが必要です。"}), 401

    data = request.get_json()
    password = data.get("password")

    if not password:
        return jsonify({"error": "パスワードを入力してください。"}), 400

    try:
        result = auth_service.authenticate_judge(id, password)
        if result == "user_only":
            return jsonify(
                {"error": "この大会は一般投票のみのため、審査員として参加できません。"}
            ), 400
        if result == "authenticated":
            return jsonify({"redirectUrl": f"/venue/{id}"}), 200
        return jsonify({"error": "パスワードが正しくありません。"}), 401
    except Exception as e:
        print(f"!!! ERROR at POST /api/contests/{id}/judge/login: {e}")
        traceback.print_exc()
        return jsonify({"error": "審査員認証中にエラーが発生しました。"}), 500
