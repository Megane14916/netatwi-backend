"""Public and administrative news routes."""

import os

from flask import jsonify, request, session

from models import News, db
from .legacy import LegacyEndpointBlueprint


bp = LegacyEndpointBlueprint("news", __name__)


@bp.route("/api/news", methods=["GET"])
def get_news():
    try:
        news_items = News.query.order_by(News.created_at.desc()).limit(20).all()
        return jsonify(
            [
                {
                    "id": item.id,
                    "tweet_id": item.tweet_id,
                    "created_at": item.created_at.isoformat(),
                }
                for item in news_items
            ]
        ), 200
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
        news_items = News.query.order_by(News.created_at.desc()).all()
        return jsonify(
            [
                {
                    "id": item.id,
                    "tweet_id": item.tweet_id,
                    "created_at": item.created_at.isoformat(),
                }
                for item in news_items
            ]
        ), 200
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
        if not tweet_id:
            return jsonify({"error": "ツイートIDまたはURLは必須です。"}), 400

        import re

        match = re.search(r"status/(\d+)", tweet_id)
        if match:
            tweet_id = match.group(1)

        new_news = News(tweet_id=tweet_id)
        db.session.add(new_news)
        db.session.commit()
        return jsonify({"message": "ニュースを追加しました。", "id": new_news.id}), 201
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
        news_item = News.query.get(id)
        if not news_item:
            return jsonify({"error": "ニュースが見つかりません。"}), 404
        db.session.delete(news_item)
        db.session.commit()
        return jsonify({"message": "ニュースを削除しました。"}), 200
    except Exception as e:
        db.session.rollback()
        print(f"!!! ERROR at DELETE /api/admin/news/{id}: {e}")
        return jsonify({"error": "ニュースの削除に失敗しました。"}), 500
