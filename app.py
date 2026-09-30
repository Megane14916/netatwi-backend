import boto3  # R2用
import logging
import os
import re
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from flask import jsonify, redirect, request, session, url_for
from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2
from sqlalchemy import case, distinct, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename

from app_factory import create_base_app
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
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("R2_ENDPOINT_URL"),
        aws_access_key_id=os.environ.get("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
    )


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_file(file):
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


def delete_file(file_url):
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






# (以降のコードは変更ありません)
# ...


def generate_contest_results(contest_id):
    """
    定期バッチ専用：結果を集計し、ContestResult に保存する。
    """
    contest = Contest.query.get(contest_id)
    if not contest:
        return None

    # すでに集計済みの場合はスキップ
    existing_results = ContestResult.query.filter_by(contest_id=contest_id).first()
    if existing_results:
        return

    # 一般投票者の総数（ユニーク）を取得
    total_general_voters = (
        db.session.query(func.count(distinct(Vote.user_id)))
        .filter(Vote.contest_id == contest_id, Vote.is_judge_vote == False)
        .scalar()
    )

    if total_general_voters is None or total_general_voters == 0:
        total_general_voters = 1

    judge_score_col = func.sum(case((Vote.is_judge_vote == True, Vote.count), else_=0))
    general_votes_col = func.sum(
        case((Vote.is_judge_vote == False, Vote.count), else_=0)
    )

    results_query = (
        db.session.query(
            Vote.post_id,
            judge_score_col.label("judge_score"),
            general_votes_col.label("general_votes"),
        )
        .filter(Vote.contest_id == contest_id)
        .group_by(Vote.post_id)
        .subquery()
    )

    judge_score_val = func.coalesce(results_query.c.judge_score, 0)
    general_votes_val = func.coalesce(results_query.c.general_votes, 0)

    # 採点方法に基づく計算式
    if contest.scoring_method == "user":
        final_score_expr = general_votes_val
    elif contest.scoring_method == "judge":
        final_score_expr = judge_score_val
    else:  # 'both' or None
        final_score_expr = (
            judge_score_val
            + (general_votes_val / total_general_voters) * contest.general_vote_weight
        )

    ranked_posts_query = (
        db.session.query(Post, final_score_expr.label("total_score"))
        .outerjoin(results_query, Post.id == results_query.c.post_id)
        .filter(Post.contest_id == contest_id)
        .order_by(
            final_score_expr.desc(),
            Post.created_at.asc(),  # 同点時の順序用
        )
    )

    ranked_results = []
    current_rank = 1
    last_score = -1
    skip = 0
    ranked_posts = ranked_posts_query.all()
    total_participants = len(ranked_posts)
    advancement_cutoff = 0
    if contest.advancement_numerator is not None and contest.advancement_denominator:
        advancement_cutoff = (
            total_participants * contest.advancement_numerator
        ) // contest.advancement_denominator

    # 審査員賞の取得
    judge_awards_query = (
        db.session.query(Vote.post_id)
        .filter(Vote.contest_id == contest_id, Vote.is_judge_award == True)
        .all()
    )
    judge_awarded_post_ids = {row[0] for row in judge_awards_query}

    results_to_insert = []
    for idx, (post, total_score) in enumerate(ranked_posts):
        current_score_val = round(total_score, 2) if total_score is not None else 0
        if idx == 0:
            last_score = current_score_val

        if current_score_val != last_score:
            current_rank += 1 + skip
            skip = 0
            last_score = current_score_val
        elif idx > 0:
            skip += 1

        is_advanced = (
            current_rank <= advancement_cutoff if advancement_cutoff > 0 else False
        )
        is_judge_award = post.id in judge_awarded_post_ids
        if contest.judge_award_advancement and is_judge_award:
            is_advanced = True

        cr = ContestResult(
            contest_id=contest_id,
            post_id=post.id,
            user_id=post.user_id,
            score=current_score_val,
            rank=current_rank,
            is_advanced=is_advanced,
            is_judge_award=is_judge_award,
        )
        results_to_insert.append(cr)

    db.session.bulk_save_objects(results_to_insert)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Failed to save ContestResult: {e}")


def get_cached_contest_results(contest_id):
    """
    API呼び出し用：DBに保存済みの ContestResult から結果を取得して返す。
    バッチが未実行でデータがない場合は空の辞書を返す。
    """
    existing_results = ContestResult.query.filter_by(contest_id=contest_id).all()
    results_dict = {}
    for r in existing_results:
        results_dict[r.post_id] = {
            "post_id": r.post_id,
            "rank": r.rank,
            "score": r.score,
            "is_advanced": r.is_advanced,
            "is_judge_award": r.is_judge_award,
        }
    return results_dict


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


@app.route("/api/tasks/contest/<int:id>/<event_type>", methods=["POST"])
def handle_contest_task(id, event_type):
    # Security note: In a real app, verify the request comes from Cloud Tasks (e.g. OIDC token)
    contest = Contest.query.get(id)
    if not contest:
        return jsonify({"error": "Contest not found"}), 404

    now = datetime.now(timezone.utc)
    changed = False

    if event_type == "post_start":
        if (
            contest.start_time
            and now >= contest.start_time.replace(tzinfo=timezone.utc)
            and not contest.notified_post_start
        ):
            print(f"[{contest.id}] Post start notification (Cloud Tasks)")
            user_ids = db.session.query(User.id).all()
            notifications = [
                {
                    "user_id": uid[0],
                    "type": "contest_post_start",
                    "contest_id": contest.id,
                }
                for uid in user_ids
            ]
            db.session.bulk_insert_mappings(Notification, notifications)
            contest.notified_post_start = True
            changed = True

    elif event_type == "voting_start":
        if (
            contest.end_time
            and now >= contest.end_time.replace(tzinfo=timezone.utc)
            and not contest.notified_voting_start
        ):
            print(f"[{contest.id}] Voting start notification (Cloud Tasks)")
            user_ids = db.session.query(User.id).all()
            notifications = [
                {
                    "user_id": uid[0],
                    "type": "contest_voting_start",
                    "contest_id": contest.id,
                }
                for uid in user_ids
            ]
            db.session.bulk_insert_mappings(Notification, notifications)
            contest.notified_voting_start = True
            changed = True

    elif event_type == "result_announce":
        if (
            contest.voting_end_time
            and now >= contest.voting_end_time.replace(tzinfo=timezone.utc)
            and not contest.notified_result_announce
        ):
            print(
                f"[{contest.id}] Result announce notification & calculation (Cloud Tasks)"
            )
            generate_contest_results(contest.id)
            user_ids = db.session.query(User.id).all()
            notifications = [
                {
                    "user_id": uid[0],
                    "type": "contest_result_announce",
                    "contest_id": contest.id,
                }
                for uid in user_ids
            ]
            db.session.bulk_insert_mappings(Notification, notifications)
            contest.notified_result_announce = True
            changed = True

    if changed:
        db.session.commit()
        return jsonify({"message": f"Processed {event_type}"}), 200

    return jsonify(
        {"message": "Task skipped (time not reached or already processed)"}
    ), 200


@app.cli.command("process-contests")
def process_contests_command():
    """定期実行バッチ: 大会の状態変化を検知して通知送信や結果集計を行う"""
    print("--- process-contests batch started ---")
    now = datetime.now(timezone.utc)
    contests = Contest.query.all()
    all_users = None

    for contest in contests:
        changed = False

        # 投稿開始
        if (
            contest.start_time
            and contest.start_time.replace(tzinfo=timezone.utc) <= now
            and not contest.notified_post_start
        ):
            print(f"[{contest.id}] Post start notification")
            if all_users is None:
                all_users = User.query.all()
            for u in all_users:
                db.session.add(
                    Notification(
                        user_id=u.id, type="contest_post_start", contest_id=contest.id
                    )
                )
            contest.notified_post_start = True
            changed = True

        # 投票開始
        if (
            contest.end_time
            and contest.end_time.replace(tzinfo=timezone.utc) <= now
            and not contest.notified_voting_start
        ):
            print(f"[{contest.id}] Voting start notification")
            if all_users is None:
                all_users = User.query.all()
            for u in all_users:
                db.session.add(
                    Notification(
                        user_id=u.id, type="contest_voting_start", contest_id=contest.id
                    )
                )
            contest.notified_voting_start = True
            changed = True

        # 結果発表
        if (
            contest.voting_end_time
            and contest.voting_end_time.replace(tzinfo=timezone.utc) <= now
            and not contest.notified_result_announce
        ):
            print(f"[{contest.id}] Result announce notification & calculation")
            generate_contest_results(contest.id)
            if all_users is None:
                all_users = User.query.all()
            for u in all_users:
                db.session.add(
                    Notification(
                        user_id=u.id,
                        type="contest_result_announce",
                        contest_id=contest.id,
                    )
                )
            contest.notified_result_announce = True
            changed = True

        if changed:
            db.session.commit()
            print(f"[{contest.id}] Committed changes")

    # --- 古い通知の自動削除 (30日経過) ---
    cutoff_date = now - timedelta(days=30)
    try:
        deleted_count = Notification.query.filter(
            Notification.created_at < cutoff_date
        ).delete(synchronize_session=False)
        if deleted_count > 0:
            db.session.commit()
            print(f"Deleted {deleted_count} old notifications (older than 30 days)")
    except Exception as e:
        db.session.rollback()
        print(f"Failed to delete old notifications: {e}")

    print("--- process-contests batch completed ---")


@app.cli.command("update-user-stats")
def update_user_stats():
    """Update UserStats table by aggregating ContestResult data"""
    from models import Contest, ContestResult, User, UserStats, db
    from sqlalchemy import case, func

    print("--- update-user-stats batch started ---")

    gp_1st = func.sum(
        case(((Contest.type == "grandprix") & (ContestResult.rank == 1), 1), else_=0)
    ).label("gp_1st")
    gp_2nd = func.sum(
        case(((Contest.type == "grandprix") & (ContestResult.rank == 2), 1), else_=0)
    ).label("gp_2nd")
    gp_3rd = func.sum(
        case(((Contest.type == "grandprix") & (ContestResult.rank == 3), 1), else_=0)
    ).label("gp_3rd")
    daily_1st = func.sum(
        case(((Contest.type == "daily") & (ContestResult.rank == 1), 1), else_=0)
    ).label("daily_1st")
    daily_2nd = func.sum(
        case(((Contest.type == "daily") & (ContestResult.rank == 2), 1), else_=0)
    ).label("daily_2nd")
    daily_3rd = func.sum(
        case(((Contest.type == "daily") & (ContestResult.rank == 3), 1), else_=0)
    ).label("daily_3rd")
    judge_awards = func.sum(
        case((ContestResult.is_judge_award == True, 1), else_=0)
    ).label("judge_awards")

    results = (
        db.session.query(
            User.id,
            User.name,
            gp_1st,
            gp_2nd,
            gp_3rd,
            daily_1st,
            daily_2nd,
            daily_3rd,
            judge_awards,
        )
        .outerjoin(ContestResult, User.id == ContestResult.user_id)
        .outerjoin(Contest, ContestResult.contest_id == Contest.id)
        .group_by(User.id, User.name)
        .all()
    )

    def sort_key(row):
        return (
            -(row.gp_1st or 0),
            -(row.gp_2nd or 0),
            -(row.gp_3rd or 0),
            -(row.judge_awards or 0),
            -(row.daily_1st or 0),
            -(row.daily_2nd or 0),
            -(row.daily_3rd or 0),
            row.name or "",
        )

    results.sort(key=sort_key)

    existing_stats = {s.user_id: s for s in UserStats.query.all()}

    current_rank = 1
    tie_count = 0
    prev_score = None

    for row in results:
        user_id = row.id

        score = (
            row.gp_1st or 0,
            row.gp_2nd or 0,
            row.gp_3rd or 0,
            row.judge_awards or 0,
            row.daily_1st or 0,
            row.daily_2nd or 0,
            row.daily_3rd or 0,
        )

        if prev_score is None:
            rank = current_rank
        elif score == prev_score:
            rank = current_rank
            tie_count += 1
        else:
            current_rank += tie_count + 1
            rank = current_rank
            tie_count = 0

        prev_score = score

        stats = existing_stats.get(user_id)
        if not stats:
            stats = UserStats(user_id=user_id)
            db.session.add(stats)

        stats.rank = rank
        stats.gp_1st = row.gp_1st or 0
        stats.gp_2nd = row.gp_2nd or 0
        stats.gp_3rd = row.gp_3rd or 0
        stats.daily_1st = row.daily_1st or 0
        stats.daily_2nd = row.daily_2nd or 0
        stats.daily_3rd = row.daily_3rd or 0
        stats.judge_awards = row.judge_awards or 0

    db.session.commit()
    print("--- update-user-stats batch completed ---")


from blueprints import BLUEPRINTS


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
    }
    for blueprint in BLUEPRINTS:
        application.register_blueprint(blueprint)


_register_extracted_routes(app)


def create_app(config=None):
    """Create an independently configured app with the same routes and CLI."""
    application, _settings = create_base_app(config)
    _register_extracted_routes(application)
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
