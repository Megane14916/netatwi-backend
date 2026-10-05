"""Notification creation, listing and read-state services."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import joinedload

from app.models import Comment, Notification, db


JST = timezone(timedelta(hours=9), "JST")


def create_comment_notification(post, post_id, user_id):
    # 結果期間中であれば通知作成
    contest = post.contest
    now = datetime.now(timezone.utc)
    if (
        now >= contest.voting_end_time.replace(tzinfo=timezone.utc)
        and user_id != post.user_id
    ):
        notification = Notification(
            user_id=post.user_id,
            sender_id=user_id,
            type="comment",
            post_id=post_id,
            contest_id=post.contest_id,
        )
        db.session.add(notification)


def create_like_notification(post, post_id, user_id, c):
    # 通知生成
    if user_id != post.user_id:
        notification = Notification(
            user_id=post.user_id,
            sender_id=user_id,
            type="like",
            post_id=post_id,
            contest_id=c.id,
        )
        db.session.add(notification)


def get_notifications(user_id):
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

    return (
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


def get_unread_notifications_count(user_id):
    count = Notification.query.filter_by(user_id=user_id, is_read=False).count()
    return ({"unread_count": count})


def mark_notifications_read(user_id):
    Notification.query.filter_by(user_id=user_id, is_read=False).update(
        {"is_read": True}
    )
    db.session.commit()
    return ({"message": "All notifications marked as read"})
