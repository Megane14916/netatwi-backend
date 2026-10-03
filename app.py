import logging
import os
import re
import traceback
from datetime import datetime, timedelta, timezone

from flask import jsonify, redirect, request, session, url_for
from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app_factory import create_base_app
from services import results as results_service
from integrations import images as image_storage
from app_extensions import migrate
from models import (
    Bookmark,
    Comment,
    Contest,
    ContestResult,
    Notification,
    Post,
    User,
    Vote,
    db,
)

app, runtime_settings = create_base_app()
frontend_url = runtime_settings.frontend_url
backend_url = runtime_settings.backend_url
is_local_dev = runtime_settings.is_local_dev
logger = logging.getLogger(__name__)
JST = timezone(timedelta(hours=9), "JST")

UPLOAD_FOLDER = "static/uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# R2設定
USE_R2 = os.environ.get("USE_R2", "False").lower() == "true"
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME")
R2_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL", "").rstrip("/")


def get_r2_client():
    return image_storage.get_r2_client()


def allowed_file(filename):
    return image_storage.allowed_file(filename, ALLOWED_EXTENSIONS=ALLOWED_EXTENSIONS)


def save_file(file):
    """ファイルを保存し、パブリックURLを返す"""
    return image_storage.save_file(
        file,
        UPLOAD_FOLDER=UPLOAD_FOLDER,
        USE_R2=USE_R2,
        R2_BUCKET_NAME=R2_BUCKET_NAME,
        R2_PUBLIC_URL=R2_PUBLIC_URL,
        get_r2_client=get_r2_client,
        logger=logger,
    )


def delete_file(file_url):
    """URLからファイルを特定して削除する"""
    return image_storage.delete_file(
        file_url,
        UPLOAD_FOLDER=UPLOAD_FOLDER,
        USE_R2=USE_R2,
        R2_BUCKET_NAME=R2_BUCKET_NAME,
        get_r2_client=get_r2_client,
        logger=logger,
    )






# (以降のコードは変更ありません)
# ...


def generate_contest_results(contest_id):
    """
    定期バッチ専用：結果を集計し、ContestResult に保存する。
    """
    return results_service.generate_contest_results(contest_id)


def get_cached_contest_results(contest_id):
    """
    API呼び出し用：DBに保存済みの ContestResult から結果を取得して返す。
    バッチが未実行でデータがない場合は空の辞書を返す。
    """
    return results_service.get_cached_contest_results(contest_id)


# --- 文字数カウントロジック (追加) ---
def calculate_weighted_length(text):
    if not text:
        return 0

    # 改行コードの正規化: \r\n -> \n, \r -> \n
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    url_pattern = re.compile(r"https?://[\w/:%#\$&\?\(\)~\.=\+\-]+")
    processed_text = url_pattern.sub("x" * 23, text)

    length = 0
    for char in processed_text:
        code = ord(char)
        if (0x00 <= code <= 0x80) or (code == 0xF8F0) or (0xFF61 <= code <= 0xFF9F):
            length += 1
        else:
            length += 2

    return length


@app.route("/api/me")
def get_current_user():
    user_data = {"logged_in": False}
    if "user_id" in session:
        user_data["logged_in"] = True
        user_data["user"] = {
            "id": session["user_id"],
            "screen_name": session["screen_name"],
            "name": session.get("name"),
            "profile_image_url": session.get("profile_image_url"),
            "isAdmin": session["screen_name"]
            in [
                s.strip()
                for s in os.environ.get(
                    "ADMIN_SCREEN_NAMES", "dummy_admin1,dummy_admin2"
                ).split(",")
                if s.strip()
            ],
        }
        # --- ▼▼▼ set ではなく list を使うように修正 ▼▼▼ ---
        # セッションから 'judge_for_contest_ids' をリストとして取得 (なければ空のリスト)
        judge_contest_ids = session.get("judge_for_contest_ids", [])
        user_data["judge_contests"] = judge_contest_ids  # リストをそのまま返す
        # --- ▲▲▲ ここまで ▲▲▲ ---
    return jsonify(user_data)


@app.route("/api/logout")
def logout():
    session.clear()
    return jsonify({"message": "Logged out successfully"})


@app.route("/api/users/me", methods=["DELETE"])
def withdraw_user():
    if "user_id" not in session:
        return jsonify({"error": "Login required"}), 401

    user_id = session["user_id"]
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    user.deleted_at = datetime.now(timezone.utc)
    db.session.commit()

    session.clear()
    return jsonify({"message": "退会処理が完了しました"})




# --- Mock API Endpoints ---
@app.route("/")
def index():
    return "ネタツイ大会バックエンド"


# --- Cloud Tasks Integration ---
_cloud_tasks_client = None


def schedule_contest_task(contest_id, event_type, schedule_time):
    global _cloud_tasks_client
    project = os.environ.get("GCP_PROJECT_ID")
    location = os.environ.get("GCP_LOCATION")
    queue = os.environ.get("GCP_QUEUE_NAME")
    handler_url = os.environ.get("TASK_HANDLER_URL") or os.environ.get("GCR_URL")

    if not all([project, location, queue, handler_url]):
        print(f"Skipping task scheduling for {event_type} - GCP configuration missing.")
        return

    if _cloud_tasks_client is None:
        _cloud_tasks_client = tasks_v2.CloudTasksClient()
    client = _cloud_tasks_client
    parent = client.queue_path(project, location, queue)

    url = f"{handler_url}/api/tasks/contest/{contest_id}/{event_type}"

    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": url,
            "headers": {"Content-type": "application/json"},
        }
    }

    # 要件: 各イベントの「10秒後」にタスクを実行する（ギリギリの書き込み遅延等を考慮）
    if schedule_time.tzinfo is None:
        schedule_time = schedule_time.replace(tzinfo=timezone.utc)
    schedule_time = schedule_time + timedelta(seconds=10)

    # Ensure schedule time is at least a few seconds in the future
    now = datetime.now(timezone.utc)
    if schedule_time < now:
        schedule_time = now + timedelta(seconds=10)

    timestamp = timestamp_pb2.Timestamp()
    timestamp.FromDatetime(schedule_time)
    task["schedule_time"] = timestamp

    try:
        response = client.create_task(request={"parent": parent, "task": task})
        print(f"Created task {response.name} for {event_type} at {schedule_time}")
    except Exception as e:
        print(f"Failed to create task for {event_type}: {e}")


from blueprints import BLUEPRINTS
from blueprints.tasks import handle_contest_task
from cli import process_contests_command, register_cli, update_user_stats


def _register_extracted_routes(application):
    # Resolve the scheduler from this module when a request runs. Existing
    # integrations and test fakes can continue replacing it on app.py.
    application.extensions["schedule_contest_task"] = (
        lambda *args: schedule_contest_task(*args)
    )
    application.extensions["legacy_route_helpers"] = {
        "get_route_logger": lambda: logger,
        "allowed_file": lambda *args: allowed_file(*args),
        "calculate_weighted_length": lambda *args: calculate_weighted_length(*args),
        "save_file": lambda *args: save_file(*args),
        "delete_file": lambda *args: delete_file(*args),
        "get_cached_contest_results": lambda *args: get_cached_contest_results(*args),
        "generate_contest_results": lambda *args: generate_contest_results(*args),
    }
    for blueprint in BLUEPRINTS:
        application.register_blueprint(blueprint)


_register_extracted_routes(app)
register_cli(app)


def create_app(config=None):
    """Create an independently configured app with the same routes and CLI."""
    application, _settings = create_base_app(config)
    _register_extracted_routes(application)
    register_cli(application)
    registered_endpoints = set(application.view_functions)
    for rule in app.url_map.iter_rules():
        if rule.endpoint in registered_endpoints:
            continue
        application.add_url_rule(
            rule.rule,
            endpoint=rule.endpoint,
            view_func=app.view_functions[rule.endpoint],
            methods=rule.methods,
            defaults=rule.defaults,
            subdomain=rule.subdomain,
            strict_slashes=rule.strict_slashes,
            provide_automatic_options=rule.provide_automatic_options,
        )
    for name, command in app.cli.commands.items():
        if name not in application.cli.commands:
            application.cli.add_command(command, name)
    return application


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        print("Database tables created (if not existed).")

    # 環境変数PORTを取得（Cloud Runでは必須）、なければローカル用の5001を使う
    port = int(os.environ.get("PORT", 5001))

    # host='0.0.0.0' を指定してコンテナ外からのアクセスを許可する
    # 本番環境では debug=False にする
    app.run(host="0.0.0.0", port=port, debug=False)
