"""Post validation, database updates and image operation coordination.

CRUD returns a post (on create/update success) or a payload, plus its status.
The route retains response serialization and the original exception boundary.
"""

from datetime import datetime, timezone

from app.runtime_dependencies import (
    allowed_file,
    calculate_weighted_length,
    delete_file,
    save_file,
)
from app.models import Bookmark, Comment, Contest, ContestResult, Notification, Post, Vote, db


def validate_submission(content, files):
    if not content and not files:
        return ({"error": "Content or images required"}), 400

    # 画像枚数制限
    if len(files) > 4:
        return ({"error": "Max 4 images allowed"}), 400

    return None


def prepare_update(new_content, kept_images, files):
    if new_content:
        new_content = new_content.replace("\r\n", "\n").replace("\r", "\n")

    # テキストも画像もなければエラー（ただし画像全削除＆テキストありはOK）
    if not new_content and not kept_images and not files:
        return new_content, (({"error": "No content"}), 400)

    if new_content and calculate_weighted_length(new_content) > 280:
        return new_content, (({"error": "Text too long (max 280)"}), 400)

    return new_content, None


def submit_post(id, user_id, content, files):
    c = Contest.query.get_or_404(id)
    now = datetime.now(timezone.utc)
    if not (
        c.start_time.replace(tzinfo=timezone.utc)
        <= now
        < c.end_time.replace(tzinfo=timezone.utc)
    ):
        return ({"error": "Outside period"}), 403

    # 画像必須のバリデーション
    valid_files = [f for f in files if f and f.filename]
    if c.image_rule == "required" and len(valid_files) == 0:
        return ({"error": "画像を最低1枚添付してください"}), 400

    # 決勝コンテストの場合の進出者チェック
    if c.parent_contest_id:
        qualifier_result = ContestResult.query.filter_by(
            contest_id=c.parent_contest_id, user_id=user_id
        ).first()
        if not qualifier_result or not qualifier_result.is_advanced:
            return (
                {"error": "予選を通過していないため、この大会には投稿できません"}
            ), 403

    if Post.query.filter_by(user_id=user_id, contest_id=id).first():
        return ({"error": "Already posted"}), 409

    # 画像アップロード処理
    image_urls = []
    for file in valid_files:
        if allowed_file(file.filename):
            url = save_file(file)
            image_urls.append(url)

    # Post作成 (images setter経由で保存)
    new_post = Post(content=content, contest_id=id, user_id=user_id)
    new_post.images = image_urls  # JSON化して保存される

    # カウンタのアトミックなインクリメント（レースコンディション対策）
    Contest.query.filter_by(id=id).update({"post_count": Contest.post_count + 1})

    db.session.add(new_post)
    db.session.commit()

    return new_post, 201


def update_post(contest_id, post_id, user_id, new_content, kept_images, files):
    post_to_edit = Post.query.filter_by(
        id=post_id, user_id=user_id, contest_id=contest_id
    ).first()
    if not post_to_edit:
        return ({"error": "Not found"}), 404
    c = Contest.query.get(contest_id)
    now = datetime.now(timezone.utc)
    if not (
        c.start_time.replace(tzinfo=timezone.utc)
        <= now
        < c.end_time.replace(tzinfo=timezone.utc)
    ):
        return ({"error": "Outside period"}), 403

    # 1. 既存画像 (old_images) の取得
    old_images = post_to_edit.images or []

    # 2. 新しい画像リスト (final_images) の構築
    final_images = []
    # 維持する画像 (kept_images) を追加
    if kept_images:
        final_images.extend(kept_images)

    # 新規アップロード画像を追加
    if files:
        for file in files:
            if file and allowed_file(file.filename):
                url = save_file(file)
                final_images.append(url)

    # 3. 削除された画像を特定してストレージから削除
    # old_images にはあるが、final_images にはないもの
    for old_url in old_images:
        if old_url not in final_images:
            delete_file(old_url)

    # 4. DB更新
    post_to_edit.content = new_content
    post_to_edit.images = final_images
    post_to_edit.updated_at = datetime.now(timezone.utc)

    db.session.commit()
    return post_to_edit, 200


def delete_post(contest_id, post_id, user_id):
    post_to_delete = Post.query.filter_by(
        id=post_id, user_id=user_id, contest_id=contest_id
    ).first()
    if not post_to_delete:
        return ({"error": "Not found"}), 404

    c = Contest.query.get(contest_id)
    now = datetime.now(timezone.utc)
    if not (
        c.start_time.replace(tzinfo=timezone.utc)
        <= now
        < c.end_time.replace(tzinfo=timezone.utc)
    ):
        return ({"error": "Outside period"}), 403

    if post_to_delete.images:
        for url in post_to_delete.images:
            try:
                delete_file(url)
            except:
                pass

    Vote.query.filter_by(post_id=post_id).delete()
    Comment.query.filter_by(post_id=post_id).delete()
    Notification.query.filter_by(post_id=post_id).delete()
    Bookmark.query.filter_by(post_id=post_id).delete()
    ContestResult.query.filter_by(post_id=post_id).delete()

    db.session.delete(post_to_delete)

    # 投稿数カウンタのアトミックなデクリメント
    Contest.query.filter(Contest.id == contest_id, Contest.post_count > 0).update(
        {"post_count": Contest.post_count - 1}
    )

    db.session.commit()
    return ({"message": "Deleted successfully"}), 200
