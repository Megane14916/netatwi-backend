"""Comment listing and mutation routes."""

from datetime import datetime, timedelta, timezone

from flask import jsonify, request, session

from models import Comment, Notification, Post, db
from .legacy import LegacyEndpointBlueprint


bp = LegacyEndpointBlueprint("comments", __name__)
JST = timezone(timedelta(hours=9), "JST")


@bp.route("/api/posts/<int:post_id>/comments", methods=["GET"])
def get_comments(post_id):
    post = Post.query.get_or_404(post_id)
    comments = (
        Comment.query.filter_by(post_id=post_id)
        .order_by(Comment.created_at.asc())
        .all()
    )
    return jsonify(
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


@bp.route("/api/comments", methods=["GET"])
def get_multiple_comments():
    post_ids_param = request.args.get("postIds", "")
    if not post_ids_param:
        return jsonify({})

    try:
        post_ids = [int(pid) for pid in post_ids_param.split(",")]
    except ValueError:
        return jsonify({"error": "Invalid postIds format"}), 400

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
    return jsonify(result)


@bp.route("/api/posts/<int:post_id>/comments", methods=["POST"])
def add_comment(post_id):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    post = Post.query.get_or_404(post_id)
    data = request.get_json()
    raw_content = data.get("content", "")

    judge_contests = session.get("judge_for_contest_ids", [])
    is_judge = post.contest_id in judge_contests

    if not raw_content.strip() or (len(raw_content) > 140 and not is_judge):
        return jsonify({"error": "Comment must be between 1 and 140 characters"}), 400
    content = raw_content

    existing_comment = Comment.query.filter_by(post_id=post_id, user_id=user_id).first()
    if existing_comment:
        return jsonify({"error": "You have already commented on this post"}), 409

    new_comment = Comment(
        user_id=user_id, post_id=post_id, content=content, is_judge=is_judge
    )
    db.session.add(new_comment)

    # アトミックにコメント数を増やす
    Post.query.filter_by(id=post_id).update({"comment_count": Post.comment_count + 1})

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

    db.session.commit()
    return jsonify({"message": "Comment added successfully", "id": new_comment.id}), 201


@bp.route("/api/comments/<int:comment_id>", methods=["PUT", "DELETE"])
def modify_comment(comment_id):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    comment = Comment.query.get_or_404(comment_id)

    if comment.user_id != user_id:
        return jsonify({"error": "Forbidden"}), 403

    if request.method == "DELETE":
        post_id = comment.post_id
        db.session.delete(comment)
        # アトミックにコメント数を減らす
        Post.query.filter_by(id=post_id).update(
            {"comment_count": Post.comment_count - 1}
        )
        db.session.commit()
        return jsonify({"message": "Comment deleted"})

    data = request.get_json()
    raw_content = data.get("content", "")
    if not raw_content.strip() or (len(raw_content) > 140 and not comment.is_judge):
        return jsonify({"error": "Invalid content length"}), 400

    comment.content = raw_content
    db.session.commit()
    return jsonify({"message": "Comment updated"})
