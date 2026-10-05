"""Image storage operations; settings and helper seams remain owned by app.py."""

import os
import uuid
from urllib.parse import urlparse

import boto3
from werkzeug.utils import secure_filename


def get_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("R2_ENDPOINT_URL"),
        aws_access_key_id=os.environ.get("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
    )


def allowed_file(filename, *, ALLOWED_EXTENSIONS):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# Keyword names preserve the original helper bodies. app.py passes its current
# settings and callbacks on each invocation, including patched test doubles.
def save_file(
    file, *, UPLOAD_FOLDER, USE_R2, R2_BUCKET_NAME, R2_PUBLIC_URL, get_r2_client, logger
):
    """ファイルを保存し、パブリックURLを返す"""
    filename = secure_filename(file.filename)
    # ユニークなファイル名にする
    ext = filename.rsplit(".", 1)[1].lower()
    unique_filename = f"{uuid.uuid4().hex}.{ext}"

    if USE_R2:
        try:
            s3 = get_r2_client()
            s3.upload_fileobj(
                file,
                R2_BUCKET_NAME,
                unique_filename,
                ExtraArgs={"ContentType": file.content_type},
            )
            return f"{R2_PUBLIC_URL}/{unique_filename}"
        except Exception as e:
            logger.error(f"R2 Upload Error: {e}")
            raise e
    else:
        # ローカル保存
        file_path = os.path.join(UPLOAD_FOLDER, unique_filename)
        file.save(file_path)
        # FlaskのstaticファイルとしてのURLを返す (本番ではFRONTEND_URL経由でアクセスできる前提)
        # ここではバックエンドのURLを返す必要がある (CORS等注意)
        # 開発環境では http://localhost:5001/static/uploads/... となる
        return f"/static/uploads/{unique_filename}"


def delete_file(
    file_url, *, UPLOAD_FOLDER, USE_R2, R2_BUCKET_NAME, get_r2_client, logger
):
    """URLからファイルを特定して削除する"""
    try:
        if not file_url:
            return

        # ファイル名の抽出
        parsed_url = urlparse(file_url)
        filename = os.path.basename(parsed_url.path)

        if USE_R2:
            # R2から削除
            try:
                s3 = get_r2_client()
                logger.info(f"Deleting from R2: {filename}")
                s3.delete_object(Bucket=R2_BUCKET_NAME, Key=filename)
            except Exception as e:
                logger.error(f"Failed to delete from R2: {e}")
        else:
            # ローカルから削除
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Deleted local file: {file_path}")
    except Exception as e:
        logger.error(f"Error deleting file {file_url}: {e}")


def initialize_image_settings():
    UPLOAD_FOLDER = "static/uploads"
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    # R2設定
    USE_R2 = os.environ.get("USE_R2", "False").lower() == "true"
    R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME")
    R2_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL", "").rstrip("/")
    return UPLOAD_FOLDER, ALLOWED_EXTENSIONS, USE_R2, R2_BUCKET_NAME, R2_PUBLIC_URL
