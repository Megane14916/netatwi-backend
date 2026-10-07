"""News queries, tweet ID parsing and database writes with original boundaries."""

from app.extensions import db
from app.models import News


def get_news():
    news_items = News.query.order_by(News.created_at.desc()).limit(20).all()
    return (
        [
            {
                "id": item.id,
                "tweet_id": item.tweet_id,
                "created_at": item.created_at.isoformat(),
            }
            for item in news_items
        ]
    ), 200


def get_admin_news():
    news_items = News.query.order_by(News.created_at.desc()).all()
    return (
        [
            {
                "id": item.id,
                "tweet_id": item.tweet_id,
                "created_at": item.created_at.isoformat(),
            }
            for item in news_items
        ]
    ), 200


def add_news(tweet_id):
    if not isinstance(tweet_id, str) or not tweet_id:
        return ({"error": "ツイートIDまたはURLは必須です。"}), 400

    import re

    match = re.search(r"status/(\d+)", tweet_id)
    if match:
        tweet_id = match.group(1)
    if len(tweet_id) > 80:
        return {"error": "ツイートIDは80文字以内で入力してください。"}, 400

    new_news = News(tweet_id=tweet_id)
    db.session.add(new_news)
    db.session.commit()
    return ({"message": "ニュースを追加しました。", "id": new_news.id}), 201


def delete_news(id):
    news_item = News.query.get(id)
    if not news_item:
        return ({"error": "ニュースが見つかりません。"}), 404
    db.session.delete(news_item)
    db.session.commit()
    return ({"message": "ニュースを削除しました。"}), 200
