"""Shared request hooks and error responses."""

from flask import current_app


from flask import jsonify, request, session

from app.extensions import db
from app.models import User
from app.services.validation import InputError




def invalidate_stale_user_session():
    """Validate signed user sessions against current persisted account state."""
    if "user_id" not in session:
        return
    user_id = session["user_id"]
    user = db.session.get(User, user_id) if type(user_id) is int and 0 < user_id < 2**63 else None
    if user is None or user.deleted_at is not None:
        session.clear()


def request_entity_too_large(_error):
    """容量超過をフロントエンドが解釈できる JSON で返す。"""
    return (
        jsonify(
            {
                "error": "画像の合計サイズが上限を超えています（最大16 MiB）",
                "code": "PAYLOAD_TOO_LARGE",
                "maxBytes": 16 * 1024 * 1024,
            }
        ),
        413,
    )


def log_request_info():
    if request.path.startswith("/api/login") or request.path.startswith(
        "/api/callback"
    ):
        current_app.logger.info("OAuth request started; endpoint=%s; secure=%s",
                    request.endpoint, request.is_secure)


def add_cache_control_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    # Cookieごとにレスポンスを分けさせる。CDN/リバースプロキシがCookieを無視して
    # URLだけでキャッシュし、別ユーザーに他人のレスポンスを返す事故を防ぐ。
    response.headers["Vary"] = "Cookie"
    return response


def invalid_input(error):
    return jsonify({"error": str(error)}), 400


def register_hooks(app):
    app.register_error_handler(InputError, invalid_input)
    app.register_error_handler(413, request_entity_too_large)
    app.before_request(invalidate_stale_user_session)
    app.before_request(log_request_info)
    app.after_request(add_cache_control_headers)
