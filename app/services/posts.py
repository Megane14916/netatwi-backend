"""Post validation, database updates and image operation coordination.

CRUD returns a post (on create/update success) or a payload, plus its status.
The route retains response serialization and the original exception boundary.
"""

from datetime import datetime, timezone
from contextlib import contextmanager
import json

from flask import current_app
from itsdangerous import URLSafeSerializer

from app.integrations import images
from app.services.text import calculate_weighted_length
from app.models import Bookmark, Comment, Contest, ContestResult, Notification, Post, Vote, db


def _cleanup_signer():
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt="netatwi-image-cleanup")


def cleanup_images(urls):
    """Best-effort compensation; retain a signed proof for failed deletions."""
    failures = []
    for url in dict.fromkeys(urls):
        try:
            if _image_is_referenced(url):
                raise ValueError("Image still referenced")
            images.delete_file(url)
        except Exception:
            failures.append(url)
            current_app.logger.error("IMAGE_CLEANUP_PENDING %s", json.dumps({"url": url, "token": _cleanup_signer().dumps(url)}))
    return failures


def retry_image_cleanup(token):
    url = _cleanup_signer().loads(token)
    if not isinstance(url, str) or not url:
        raise ValueError("Invalid cleanup URL")
    return not cleanup_images([url])


def _image_is_referenced(url):
    return any(isinstance(post.images, list) and url in post.images
               for post in Post.query.filter(Post.image_urls.isnot(None)).all())


@contextmanager
def _compensate_uploads():
    urls = []
    try:
        yield urls
    except Exception as error:
        failed_url = getattr(error, "uploaded_image_url", None)
        if failed_url:
            urls.append(failed_url)
        try:
            db.session.rollback()
        finally:
            cleanup_images(urls)
        raise


def _other_image_references(post):
    references = set()
    for other in Post.query.filter(Post.id != post.id, Post.image_urls.isnot(None)).all():
        if isinstance(other.images, list):
            references.update(url for url in other.images if isinstance(url, str))
    return references


def owned_image_deletions(post, urls):
    """Only delete proven uploads that no other post still references."""
    if not urls:
        return []
    owned = set(post.owned_images)
    shared = _other_image_references(post)
    deletions = []
    for url in dict.fromkeys(urls):
        if url in owned and url not in shared:
            deletions.append(url)
        else:
            current_app.logger.warning("Image deletion skipped without exclusive upload ownership; post_id=%s; url=%s", post.id, url)
    return deletions


def validate_submission(content, files):
    valid_files = _valid_image_files(files)
    if any(f and f.filename and not images.allowed_file(f.filename) for f in files):
        return {"error": "Unsupported image extension"}, 400
    if not content and not valid_files:
        return ({"error": "Content or images required"}), 400

    # 画像枚数制限
    if len(valid_files) > 4:
        return ({"error": "Max 4 images allowed"}), 400

    if content and calculate_weighted_length(content) > 280:
        return {"error": "Text too long (max 280)"}, 400

    return None


def prepare_update(new_content, kept_images, files):
    if not isinstance(kept_images, list) or any(not isinstance(url, str) for url in kept_images):
        return new_content, (({"error": "Invalid kept images"}), 400)
    # Image-only edits store an empty string because Post.content is NOT NULL.
    if new_content is None:
        new_content = ""
    if not isinstance(new_content, str):
        return new_content, ({"error": "Invalid content"}, 400)
    if any(f and f.filename and not images.allowed_file(f.filename) for f in files):
        return new_content, ({"error": "Unsupported image extension"}, 400)
    valid_files = _valid_image_files(files)
    if len(kept_images) + len(valid_files) > 4:
        return new_content, ({"error": "Max 4 images allowed"}, 400)
    if new_content:
        new_content = new_content.replace("\r\n", "\n").replace("\r", "\n")

    # テキストも画像もなければエラー（ただし画像全削除＆テキストありはOK）
    if not new_content and not kept_images and not valid_files:
        return new_content, (({"error": "No content"}), 400)

    if new_content and calculate_weighted_length(new_content) > 280:
        return new_content, (({"error": "Text too long (max 280)"}), 400)

    return new_content, None


def _valid_image_files(files):
    return [file for file in files if file and file.filename and images.allowed_file(file.filename)]


def _upload_images(files, urls):
    for file in files:
        url = images.save_file(file)
        if not isinstance(url, str) or not url:
            raise ValueError("Image storage returned no URL")
        urls.append(url)


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
    valid_files = _valid_image_files(files)
    if c.image_rule == "required" and len(valid_files) == 0:
        return ({"error": "画像を最低1枚添付してください"}), 400
    if c.image_rule == "none" and valid_files:
        return {"error": "Images are not allowed in this contest"}, 400

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
    with _compensate_uploads() as image_urls:
        _upload_images(valid_files, image_urls)
        new_post = Post(content=content, contest_id=id, user_id=user_id)
        new_post.images = image_urls
        new_post.record_image_uploads(image_urls)
        Contest.query.filter_by(id=id).update({"post_count": Contest.post_count + 1})
        db.session.add(new_post)
        db.session.commit()

    return new_post, 201


def update_post(contest_id, post_id, user_id, new_content, kept_images, files):
    post_to_edit = Post.query.filter_by(
        id=post_id, user_id=user_id, contest_id=contest_id
    ).with_for_update().first()
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
    if (not isinstance(kept_images, list)
            or any(not isinstance(url, str) for url in kept_images)
            or len(set(kept_images)) != len(kept_images)
            or any(url not in old_images for url in kept_images)
            or (kept_images and set(kept_images) & _other_image_references(post_to_edit))):
        return ({"error": "Invalid kept images"}), 400

    valid_files = _valid_image_files(files)
    if c.image_rule == "required" and not kept_images and not valid_files:
        return {"error": "画像を最低1枚添付してください"}, 400
    if c.image_rule == "none" and (kept_images or valid_files):
        return {"error": "Images are not allowed in this contest"}, 400

    deletions = owned_image_deletions(post_to_edit, [url for url in old_images if url not in kept_images])
    with _compensate_uploads() as uploaded_images:
        _upload_images(valid_files, uploaded_images)
        post_to_edit.content = new_content
        post_to_edit.images = kept_images + uploaded_images
        post_to_edit.record_image_uploads(uploaded_images)
        post_to_edit.updated_at = datetime.now(timezone.utc)
        db.session.commit()
    cleanup_images(deletions)
    return post_to_edit, 200


def delete_post(contest_id, post_id, user_id):
    post_to_delete = Post.query.filter_by(
        id=post_id, user_id=user_id, contest_id=contest_id
    ).with_for_update().first()
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

    deletions = owned_image_deletions(post_to_delete, post_to_delete.images)

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
    cleanup_images(deletions)
    return ({"message": "Deleted successfully"}), 200
