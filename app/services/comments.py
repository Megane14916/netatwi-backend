"""Comment queries, validation and mutations with the original write order."""

from datetime import timedelta, timezone

from app.services import policies
from app.extensions import db
from app.models import Comment, Post
from app.services import notifications as notifications_service


JST = timezone(timedelta(hours=9), "JST")


def get_comments(post_id):
    post = Post.query.get_or_404(post_id)
    comments = (
        Comment.query.filter_by(post_id=post_id)
        .order_by(Comment.created_at.asc())
        .all()
    )
    return (
        [
            {
                "id": c.id,
                "user_id": c.user_id,
                "post_id": c.post_id,
                "content": c.content,
                "is_judge": c.is_judge,
                "created_at": c.created_at.replace(tzinfo=timezone.utc)
                .astimezone(JST)
                .isoformat(),
                "updated_at": c.updated_at.replace(tzinfo=timezone.utc)
                .astimezone(JST)
                .isoformat(),
                "user": {
                    "name": c.user.name,
                    "screen_name": c.user.screen_name,
                    "profile_image_url": c.user.profile_image_url,
                },
            }
            for c in comments
        ]
    )


def get_multiple_comments(post_ids):
    comments = (
        Comment.query.filter(Comment.post_id.in_(post_ids))
        .order_by(Comment.created_at.asc())
        .all()
    )

    result = {}
    for c in comments:
        if c.post_id not in result:
            result[c.post_id] = []
        result[c.post_id].append(
            {
                "id": c.id,
                "user_id": c.user_id,
                "post_id": c.post_id,
                "content": c.content,
                "is_judge": c.is_judge,
                "created_at": c.created_at.replace(tzinfo=timezone.utc)
                .astimezone(JST)
                .isoformat(),
                "updated_at": c.updated_at.replace(tzinfo=timezone.utc)
                .astimezone(JST)
                .isoformat(),
                "user": {
                    "name": c.user.name,
                    "screen_name": c.user.screen_name,
                    "profile_image_url": c.user.profile_image_url,
                },
            }
        )
    return (result)


def get_post(post_id):
    return Post.query.get_or_404(post_id)


def add_comment(post_id, user_id, post, raw_content, judge_contests):
    is_judge = policies.is_judge(post.contest_id, judge_contests)

    if not isinstance(raw_content, str) or not raw_content.strip() or (len(raw_content) > 140 and not is_judge):
        return ({"error": "Comment must be between 1 and 140 characters"}), 400
    content = raw_content

    existing_comment = Comment.query.filter_by(post_id=post_id, user_id=user_id).first()
    if existing_comment:
        return ({"error": "You have already commented on this post"}), 409

    new_comment = Comment(
        user_id=user_id, post_id=post_id, content=content, is_judge=is_judge
    )
    db.session.add(new_comment)

    # アトミックにコメント数を増やす
    Post.query.filter_by(id=post_id).update({"comment_count": Post.comment_count + 1})

    # 結果期間中であれば通知作成
    notifications_service.create_comment_notification(post, post_id, user_id)

    db.session.commit()
    return ({"message": "Comment added successfully", "id": new_comment.id}), 201


def get_comment_for_modification(comment_id, user_id):
    comment = Comment.query.get_or_404(comment_id)

    if not policies.is_owner(comment, user_id):
        return ({"error": "Forbidden"}), 403
    return comment, 200


def delete_comment(comment):
    post_id = comment.post_id
    db.session.delete(comment)
    # アトミックにコメント数を減らす
    Post.query.filter_by(id=post_id).update(
        {"comment_count": Post.comment_count - 1}
    )
    db.session.commit()
    return ({"message": "Comment deleted"}), 200


def update_comment(comment, raw_content):
    if not isinstance(raw_content, str) or not raw_content.strip() or (len(raw_content) > 140 and not comment.is_judge):
        return ({"error": "Invalid content length"}), 400

    comment.content = raw_content
    db.session.commit()
    return ({"message": "Comment updated"}), 200
