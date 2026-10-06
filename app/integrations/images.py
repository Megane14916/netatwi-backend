"""Image storage using the active application settings and lazy client."""

import os
import uuid
from urllib.parse import urlparse

import boto3
from werkzeug.utils import secure_filename
from flask import current_app


def get_r2_client():
    if "r2_client" not in current_app.extensions:
        current_app.extensions["r2_client"] = _create_r2_client()
    return current_app.extensions["r2_client"]


def _create_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=current_app.config.get("R2_ENDPOINT_URL"),
        aws_access_key_id=current_app.config.get("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=current_app.config.get("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
    )


def allowed_file(filename):
    ALLOWED_EXTENSIONS = current_app.config["ALLOWED_EXTENSIONS"]
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# Keyword names preserve the original helper bodies. app.py passes its current
# settings and callbacks on each invocation, including patched test doubles.
def _save_file(
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
            e.uploaded_image_url = f"{R2_PUBLIC_URL}/{unique_filename}"
            raise e
    else:
        # ローカル保存
        file_path = os.path.join(UPLOAD_FOLDER, unique_filename)
        try:
            file.save(file_path)
        except Exception as e:
            e.uploaded_image_url = f"/static/uploads/{unique_filename}"
            raise
        # FlaskのstaticファイルとしてのURLを返す (本番ではFRONTEND_URL経由でアクセスできる前提)
        # ここではバックエンドのURLを返す必要がある (CORS等注意)
        # 開発環境では http://localhost:5001/static/uploads/... となる
        return f"/static/uploads/{unique_filename}"


def _delete_file(
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
                raise
        else:
            # ローカルから削除
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Deleted local file: {file_path}")
    except Exception as e:
        logger.error(f"Error deleting file {file_url}: {e}")
        raise


def save_file(file):
    config = current_app.config
    return _save_file(file, UPLOAD_FOLDER=config["UPLOAD_FOLDER"], USE_R2=config["USE_R2"],
                      R2_BUCKET_NAME=config["R2_BUCKET_NAME"], R2_PUBLIC_URL=config["R2_PUBLIC_URL"],
                      get_r2_client=get_r2_client, logger=current_app.logger)


def delete_file(file_url):
    config = current_app.config
    return _delete_file(file_url, UPLOAD_FOLDER=config["UPLOAD_FOLDER"], USE_R2=config["USE_R2"],
                        R2_BUCKET_NAME=config["R2_BUCKET_NAME"], get_r2_client=get_r2_client,
                        logger=current_app.logger)


def initialize_image_settings(application):
    os.makedirs(application.config["UPLOAD_FOLDER"], exist_ok=True)
