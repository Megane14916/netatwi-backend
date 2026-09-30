"""Notification listing and read-state routes."""

from datetime import timedelta, timezone

from flask import jsonify, session
from sqlalchemy.orm import joinedload

from models import Comment, Notification, db
from .legacy import LegacyEndpointBlueprint


bp = LegacyEndpointBlueprint("notifications", __name__)
JST = timezone(timedelta(hours=9), "JST")


@bp.route("/api/notifications", methods=["GET"])
def get_notifications():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    notifications = (
        Notification.query.filter_by(user_id=user_id)
        .options(
            joinedload(Notification.sender),
            joinedload(Notification.post),
            joinedload(Notification.contest),
        )
        .order_by(Notification.created_at.desc())
        .all()
    )

    # コメント取得のN+1問題解消（対象のpost_idを一括取得してマッピング）
    comment_pairs = [
        (n.post_id, n.sender_id) for n in notifications if n.type == "comment"
    ]
    comment_map = {}
    if comment_pairs:
        post_ids = list(set([p[0] for p in comment_pairs]))
        comments = (
            Comment.query.filter(Comment.post_id.in_(post_ids))
            .order_by(Comment.created_at.desc())
            .all()
        )
        for c in comments:
            key = (c.post_id, c.user_id)
            if key not in comment_map:  # order_by desc なので最初に見つかったものが最新
                comment_map[key] = (
                    c.content[:40] + "..." if len(c.content) > 40 else c.content
                )

    def get_comment_content(n):
        if n.type == "comment":
            return comment_map.get((n.post_id, n.sender_id))
        return None

    return jsonify(
        [
            {
                "id": n.id,
                "type": n.type,
                "is_read": n.is_read,
                "post_id": n.post_id,
                "contest_id": n.contest_id,
                "created_at": n.created_at.replace(tzinfo=timezone.utc)
                .astimezone(JST)
                .isoformat(),
                "sender": {
                    "name": n.sender.name,
                    "screen_name": n.sender.screen_name,
                    "profile_image_url": n.sender.profile_image_url,
                }
                if n.sender
                else None,
                "post": {
                    "content": n.post.content[:40] + "..."
                    if len(n.post.content) > 40
                    else n.post.content
                }
                if n.post
                else None,
                "comment": {"content": get_comment_content(n)}
                if n.type == "comment"
                else None,
                "contest": {"name": n.contest.name, "type": n.contest.type}
                if n.contest
                else None,
            }
            for n in notifications
        ]
    )


@bp.route("/api/notifications/unread-count", methods=["GET"])
def get_unread_notifications_count():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    count = Notification.query.filter_by(user_id=user_id, is_read=False).count()
    return jsonify({"unread_count": count})


@bp.route("/api/notifications/read", methods=["POST"])
def mark_notifications_read():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user_id = session["user_id"]

    Notification.query.filter_by(user_id=user_id, is_read=False).update(
        {"is_read": True}
    )
    db.session.commit()
    return jsonify({"message": "All notifications marked as read"})
