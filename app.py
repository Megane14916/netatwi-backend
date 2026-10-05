import logging
import os
import re
import traceback
from datetime import datetime, timedelta, timezone

from flask import jsonify, redirect, request, session, url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app_factory import create_base_app
import runtime_dependencies
from services import results as results_service
from integrations import images as image_storage
from integrations import cloud_tasks
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

(UPLOAD_FOLDER, ALLOWED_EXTENSIONS, USE_R2, R2_BUCKET_NAME, R2_PUBLIC_URL) = image_storage.initialize_image_settings()


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
from services.text import calculate_weighted_length












# --- Cloud Tasks Integration ---


def schedule_contest_task(contest_id, event_type, schedule_time):
    return cloud_tasks.schedule_contest_task(contest_id, event_type, schedule_time)


from blueprints import BLUEPRINTS
from blueprints.account import get_current_user, logout, withdraw_user
from blueprints.core import index
from blueprints.tasks import handle_contest_task
from cli import process_contests_command, register_cli, update_user_stats


def _register_extracted_routes(application):
    # Resolve the scheduler from this module when a request runs. Existing
    # integrations and test fakes can continue replacing it on app.py.
    runtime_dependencies.register_helper_bindings(application, globals())
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
