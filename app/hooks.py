"""Shared request hooks and error responses."""

import logging

from flask import jsonify, request


logger = logging.getLogger("app")


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
        logger.info("OAuth request started; endpoint=%s; secure=%s",
                    request.endpoint, request.is_secure)


def add_cache_control_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    # Cookieごとにレスポンスを分けさせる。CDN/リバースプロキシがCookieを無視して
    # URLだけでキャッシュし、別ユーザーに他人のレスポンスを返す事故を防ぐ。
    response.headers["Vary"] = "Cookie"
    return response


def register_hooks(app):
    app.register_error_handler(413, request_entity_too_large)
    app.before_request(log_request_info)
    app.after_request(add_cache_control_headers)
