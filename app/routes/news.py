"""Public and administrative news routes."""

import os

from flask import jsonify, request, session

from app.models import db
from app.services import news as news_service
from .legacy import LegacyEndpointBlueprint


bp = LegacyEndpointBlueprint("news", __name__)


@bp.route("/api/news", methods=["GET"])
def get_news():
    try:
        payload, status = news_service.get_news()
        return jsonify(payload), status
    except Exception as e:
        print(f"!!! ERROR at GET /api/news: {e}")
        return jsonify({"error": "ニュースの取得に失敗しました。"}), 500


@bp.route("/api/admin/news", methods=["GET"])
def get_admin_news():
    if "user_id" not in session:
        return jsonify({"error": "Login required"}), 401
    allowed_admins = [
        s.strip()
        for s in os.environ.get(
            "ADMIN_SCREEN_NAMES", "dummy_admin1,dummy_admin2"
        ).split(",")
        if s.strip()
    ]
    if session.get("screen_name") not in allowed_admins:
        return jsonify({"error": "Forbidden: Admins only"}), 403
    try:
        payload, status = news_service.get_admin_news()
        return jsonify(payload), status
    except Exception as e:
        print(f"!!! ERROR at GET /api/admin/news: {e}")
        return jsonify({"error": "ニュースの取得に失敗しました。"}), 500


@bp.route("/api/admin/news", methods=["POST"])
def add_news():
    if "user_id" not in session:
        return jsonify({"error": "Login required"}), 401
    allowed_admins = [
        s.strip()
        for s in os.environ.get(
            "ADMIN_SCREEN_NAMES", "dummy_admin1,dummy_admin2"
        ).split(",")
        if s.strip()
    ]
    if session.get("screen_name") not in allowed_admins:
        return jsonify({"error": "Forbidden: Admins only"}), 403
    try:
        data = request.json
        tweet_id = data.get("tweet_id")
        payload, status = news_service.add_news(tweet_id)
        return jsonify(payload), status
    except Exception as e:
        db.session.rollback()
        print(f"!!! ERROR at POST /api/admin/news: {e}")
        return jsonify({"error": "ニュースの追加に失敗しました。"}), 500


@bp.route("/api/admin/news/<int:id>", methods=["DELETE"])
def delete_news(id):
    if "user_id" not in session:
        return jsonify({"error": "Login required"}), 401
    allowed_admins = [
        s.strip()
        for s in os.environ.get(
            "ADMIN_SCREEN_NAMES", "dummy_admin1,dummy_admin2"
        ).split(",")
        if s.strip()
    ]
    if session.get("screen_name") not in allowed_admins:
        return jsonify({"error": "Forbidden: Admins only"}), 403
    try:
        payload, status = news_service.delete_news(id)
        return jsonify(payload), status
    except Exception as e:
        db.session.rollback()
        print(f"!!! ERROR at DELETE /api/admin/news/{id}: {e}")
        return jsonify({"error": "ニュースの削除に失敗しました。"}), 500
