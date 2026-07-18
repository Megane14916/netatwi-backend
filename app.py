import os
import traceback
import logging
import uuid
import json
import boto3 # R2用
import re
from werkzeug.utils import secure_filename
from flask import Flask, jsonify, session, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS
from requests_oauthlib import OAuth1Session
from dotenv import load_dotenv
from models import db, User, Contest, Post, Vote, Bookmark, ContestResult, Comment, Notification, News
from datetime import datetime, timezone, timedelta
from sqlalchemy import func, case, distinct
from sqlalchemy.orm import joinedload
from werkzeug.middleware.proxy_fix import ProxyFix
from urllib.parse import urlparse
import time
from sqlalchemy import event
from sqlalchemy.engine import Engine

@event.listens_for(Engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    conn.info.setdefault('query_start_time', []).append(time.time())

@event.listens_for(Engine, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    total = time.time() - conn.info['query_start_time'].pop(-1)
    if total > 0.05:
        logger.info(f"[SQL_SLOW] {total:.4f}s: {statement[:100]}...")


import secrets
import hashlib
import base64
from requests.auth import HTTPBasicAuth
from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2
from requests_oauthlib import OAuth2Session

load_dotenv()

# --- 環境変数の読み込みと検証 ---
db_uri = os.environ.get('SQLALCHEMY_DATABASE_URI')
secret_key = os.environ.get('SECRET_KEY')
frontend_url = os.environ.get('FRONTEND_URL', '').rstrip('/')
gcp_backend_url = os.environ.get('GCR_URL') # GCPで設定したCloud RunのURL

# FLASK_DEBUGがTrueの場合 (ローカルの.envファイル) のみローカル開発とみなす
is_local_dev = os.environ.get('FLASK_DEBUG') == 'True' 
backend_url = 'http://127.0.0.1:5001' # ローカルのFlask URL

if is_local_dev:
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    db_uri = db_uri or 'sqlite:///project.db'
    secret_key = secret_key or 'a-very-secret-key-for-local-dev'
    frontend_url = frontend_url or 'http://localhost:3000'
else:
    # 本番環境(GCP)では、GCR_URLを使用
    backend_url = gcp_backend_url

if not db_uri:
    raise ValueError("FATAL_ERROR: SQLALCHEMY_DATABASE_URI environment variable is not set.")
if not secret_key:
    raise ValueError("FATAL_ERROR: SECRET_KEY environment variable is not set.")
if not frontend_url:
    raise ValueError("FATAL_ERROR: FRONTEND_URL environment variable is not set.")

app = Flask(__name__)

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0, x_prefix=0)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- アプリケーション設定 ---
# 環境に応じたセッションCookie設定
if is_local_dev:
    # ローカル開発環境: HTTP対応設定
    session_cookie_config = {
        'SESSION_COOKIE_SAMESITE': 'Lax',
        'SESSION_COOKIE_SECURE': False,
        'SESSION_COOKIE_DOMAIN': 'localhost',
    }
else:
    # 本番環境: HTTPS対応設定 (Cross-Origin)
    session_cookie_config = {
        'SESSION_COOKIE_SAMESITE': 'None',
        'SESSION_COOKIE_SECURE': True,
    }

app.config.update(
    SECRET_KEY=secret_key,
    SQLALCHEMY_DATABASE_URI=db_uri,

    SQLALCHEMY_ENGINE_OPTIONS={
        "pool_pre_ping": True,
        "pool_recycle": 300, # 5分ごとに接続をリサイクル
    },
    
    SESSION_COOKIE_HTTPONLY=True,
    PERMANENT_SESSION_LIFETIME=timedelta(days=31),
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,
    
    **session_cookie_config  # 環境に応じた設定を展開
)

JST = timezone(timedelta(hours=9), 'JST')

# --- CORS設定 (最重要) ---
# 環境変数から読み取ったフロントエンドのURLを許可する
CORS(app, supports_credentials=True, origins=[frontend_url])
# ---
db.init_app(app)
migrate = Migrate(app, db)

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# R2設定
USE_R2 = os.environ.get('USE_R2', 'False').lower() == 'true'
R2_BUCKET_NAME = os.environ.get('R2_BUCKET_NAME')
R2_PUBLIC_URL = os.environ.get('R2_PUBLIC_URL', '').rstrip('/')

def get_r2_client():
    return boto3.client(
        's3',
        endpoint_url=os.environ.get('R2_ENDPOINT_URL'),
        aws_access_key_id=os.environ.get('R2_ACCESS_KEY_ID'),
        aws_secret_access_key=os.environ.get('R2_SECRET_ACCESS_KEY'),
        region_name='auto'
    )

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_file(file):
    """ファイルを保存し、パブリックURLを返す"""
    filename = secure_filename(file.filename)
    # ユニークなファイル名にする
    ext = filename.rsplit('.', 1)[1].lower()
    unique_filename = f"{uuid.uuid4().hex}.{ext}"

    if USE_R2:
        try:
            s3 = get_r2_client()
            s3.upload_fileobj(
                file, 
                R2_BUCKET_NAME, 
                unique_filename,
                ExtraArgs={'ContentType': file.content_type}
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
        if not file_url: return

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



# --- X OAuth 2.0 設定 (古い1.0aの設定2箇所は削除してこれに差し替え) ---
X_CLIENT_ID = os.environ.get("X_CONSUMER_KEY") # "X_CLIENT_ID" としても良いが、既存の環境変数を流用
X_CLIENT_SECRET = os.environ.get("X_CONSUMER_SECRET") #"X_CLIENT_SECRET" としても良いが、既存の環境変数を流用
AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
TOKEN_URL = "https://api.x.com/2/oauth2/token"
USER_INFO_URL = "https://api.x.com/2/users/me"
X_SCOPES = ["tweet.read", "users.read"]

@app.before_request
def log_request_info():
    if request.path.startswith("/api/login") or request.path.startswith("/api/callback"):
        logger.info(f"=== REQUEST START: {request.path} ===")
        logger.info(f"Headers: {dict(request.headers)}")
        logger.info(f"Cookies sent from browser: {request.cookies}")
        logger.info(f"Session (before processing): {dict(session)}")
        logger.info(f"X-Forwarded-Proto: {request.headers.get('X-Forwarded-Proto')}")
        logger.info(f"Is Secure (Flask detected): {request.is_secure}")

@app.after_request
def add_cache_control_headers(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route("/api/login/twitter")
def twitter_login():
    try:
        # コールバックURLを生成（ローカル環境ではHTTPを使用）
        callback_url = f"{frontend_url}/api/callback/twitter"
        logger.info(f"Generated Callback URL: {callback_url}")

        # OAuth 2.0 (PKCE) に必要な安全なランダム文字列を生成
        code_verifier = secrets.token_urlsafe(48)
        hashed = hashlib.sha256(code_verifier.encode('utf-8')).digest()
        
        # パディング（=）を除去し、確実にURLセーフなBase64にする
        code_challenge = base64.urlsafe_b64encode(hashed).decode('utf-8').rstrip('=')

        # OAuth2Session の構築
        twitter = OAuth2Session(X_CLIENT_ID, redirect_uri=callback_url, scope=X_SCOPES)
        authorization_url, state = twitter.authorization_url(
            AUTHORIZE_URL, 
            code_challenge=code_challenge, 
            code_challenge_method="s256"  # 👈 ★大文字 "S256" から 小文字 "s256" に修正
        )
        
        # 👈 ★Xの厳格な仕様対策：スコープの区切り文字「+」を「%20」に強制置換
        authorization_url = authorization_url.replace('+', '%20')
        
        # セッションに検証用の値を保存
        session['oauth_state'] = state
        session['code_verifier'] = code_verifier
        session.modified = True
        
        logger.info(f"Saved to session - State: {state}")
        
        return jsonify({'authorization_url': authorization_url})
    except Exception as e:
        logger.error(f"!!! ERROR at /api/login/twitter: {e}")
        traceback.print_exc()
        return jsonify({"error": "Failed to connect to Twitter"}), 500

@app.route('/api/callback/twitter')
def twitter_callback():
    logger.info(f"=== CALLBACK START ===")
    logger.info(f"Session keys present: {list(session.keys())}")

    # セッションから検証用データを取得・削除
    state = session.pop('oauth_state', None)
    code_verifier = session.pop('code_verifier', None)
    
    # Xから返ってきた認可コードを取得
    code = request.args.get('code')
    error = request.args.get('error')

    if error:
        logger.error(f"X Login Error from URL: {error}")
        return redirect(f"{frontend_url}?login_error={error}")

    if not all([state, code_verifier, code]):
        logger.error("Missing state, code_verifier, or code in callback.")
        reason = "session_token_missing" if not state else "verifier_missing"
        return redirect(f"{frontend_url}?login_error={reason}")

    try:
        callback_url = f"{frontend_url}/api/callback/twitter"
        
        # 1. アクセストークンの取得
        twitter = OAuth2Session(X_CLIENT_ID, redirect_uri=callback_url, state=state)
        auth = HTTPBasicAuth(X_CLIENT_ID, X_CLIENT_SECRET)
        
        # token の中身を明示的に取得する
        token_response = twitter.fetch_token(
            token_url=TOKEN_URL,
            client_secret=X_CLIENT_SECRET,
            code=code,
            auth=auth,
            code_verifier=code_verifier
        )
        
        # 返ってきたデータからアクセストークンを直接取り出す
        access_token = token_response.get('access_token')
        if not access_token:
            raise ValueError("Token response did not contain access_token")
            
        logger.info(f"Access Token successfully fetched (starts with: {access_token[:10]}...)")
        
        # 2. ユーザー情報の取得 (★ライブラリのバグを回避するため、通常の requests で直接ヘッダーを指定)
        import requests
        headers = {
            "Authorization": f"Bearer {access_token}" # 👈 ここで確実にトークンを付与
        }
        
        # 無料プランでも安全に動くよう、まずはフィールド指定なしでリクエスト
        response = requests.get(f"{USER_INFO_URL}?user.fields=profile_image_url", headers=headers)
        
        # もしエラーなら、Xから返ってきたエラー内容の詳細をログに出す
        if response.status_code != 200:
            logger.error(f"X API Error Response Body: {response.text}")
            
        response.raise_for_status()
        res_json = response.json()
        
        # API v2 のデータ構造からユーザー情報を抽出
        user_data = res_json.get('data', {})
        
        twitter_id = user_data.get('id')
        screen_name = user_data.get('username') 
        name = user_data.get('name')
        
        # 画像URLは、この基本リクエストが成功した後に次のステップで取得するため、一旦空文字にします
        profile_image_url = user_data.get('profile_image_url', '').replace('_normal', '') 

        if not twitter_id:
            raise ValueError("Failed to retrieve user ID from X API v2 json")

        # 3. データベースの更新・保存処理 (ここから下は元のコードのままで大丈夫です)
        user = User.query.filter_by(twitter_id=twitter_id).first()
        if not user:
            user = User(
                twitter_id=twitter_id, 
                screen_name=screen_name,
                name=name,
                profile_image_url=profile_image_url
            )
            db.session.add(user)
        else:
            user.screen_name = screen_name
            user.name = name
            user.profile_image_url = profile_image_url
        
        db.session.commit()
        
        # アプリケーションセッションにユーザー情報をセット
        session.permanent = True
        session['user_id'] = user.id
        session['screen_name'] = user.screen_name
        session['name'] = user.name
        session['profile_image_url'] = user.profile_image_url

        logger.info(f"Login successful for user: {user.screen_name}")

    except Exception as e:
        logger.error(f"!!! ERROR at /api/callback/twitter: {e}")
        traceback.print_exc()
        db.session.rollback()
        return redirect(f"{frontend_url}?login_error=callback_failed")
    
    return redirect(frontend_url)

# (以降のコードは変更ありません)
# ...

def generate_contest_results(contest_id):
    """
    定期バッチ専用：結果を集計し、ContestResult に保存する。
    """
    contest = Contest.query.get(contest_id)
    if not contest: return None 
    
    # すでに集計済みの場合はスキップ
    existing_results = ContestResult.query.filter_by(contest_id=contest_id).first()
    if existing_results:
        return

    # 一般投票者の総数（ユニーク）を取得
    total_general_voters = db.session.query(func.count(distinct(Vote.user_id)))\
        .filter(Vote.contest_id == contest_id, Vote.is_judge_vote == False).scalar()
    
    if total_general_voters is None or total_general_voters == 0:
        total_general_voters = 1

    judge_score_col = func.sum(case((Vote.is_judge_vote == True, Vote.count), else_=0))
    general_votes_col = func.sum(case((Vote.is_judge_vote == False, Vote.count), else_=0))

    results_query = db.session.query(
        Vote.post_id, 
        judge_score_col.label('judge_score'), 
        general_votes_col.label('general_votes')
    ).filter(Vote.contest_id == contest_id).group_by(Vote.post_id).subquery()

    judge_score_val = func.coalesce(results_query.c.judge_score, 0)
    general_votes_val = func.coalesce(results_query.c.general_votes, 0)
    
    # 採点方法に基づく計算式
    if contest.scoring_method == 'user':
        final_score_expr = general_votes_val
    elif contest.scoring_method == 'judge':
        final_score_expr = judge_score_val
    else: # 'both' or None
        final_score_expr = judge_score_val + (general_votes_val / total_general_voters) * contest.general_vote_weight

    ranked_posts_query = db.session.query(
        Post, 
        final_score_expr.label('total_score')
    ).outerjoin(
        results_query, Post.id == results_query.c.post_id
    ).filter(
        Post.contest_id == contest_id
    ).order_by(
        final_score_expr.desc(),
        Post.created_at.asc() # 同点時の順序用
    )

    ranked_results = []
    current_rank = 1
    last_score = -1
    skip = 0
    total_participants = Post.query.filter_by(contest_id=contest_id).count()
    advancement_cutoff = 0
    if contest.advancement_numerator is not None and contest.advancement_denominator:
        advancement_cutoff = (total_participants * contest.advancement_numerator) // contest.advancement_denominator
    
    # 審査員賞の取得
    judge_awards_query = db.session.query(Vote.post_id).filter(Vote.contest_id == contest_id, Vote.is_judge_award == True).all()
    judge_awarded_post_ids = {row[0] for row in judge_awards_query}

    for idx, (post, total_score) in enumerate(ranked_posts_query.all()):
        current_score_val = round(total_score, 2) if total_score is not None else 0
        if idx == 0:
            last_score = current_score_val
            
        if current_score_val != last_score: 
            current_rank += 1 + skip
            skip = 0
            last_score = current_score_val
        elif idx > 0:
            skip += 1
            
        is_advanced = current_rank <= advancement_cutoff if advancement_cutoff > 0 else False
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
            is_judge_award=is_judge_award
        )
        db.session.add(cr)

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
            'post_id': r.post_id,
            'rank': r.rank,
            'score': r.score,
            'is_advanced': r.is_advanced,
            'is_judge_award': r.is_judge_award
        }
    return results_dict

# --- 文字数カウントロジック (追加) ---
def calculate_weighted_length(text):
    if not text:
        return 0
        
    # 改行コードの正規化: \r\n -> \n, \r -> \n
    text = text.replace('\r\n', '\n').replace('\r', '\n')
        
    url_pattern = re.compile(r'https?://[\w/:%#\$&\?\(\)~\.=\+\-]+')
    processed_text = url_pattern.sub('x' * 23, text)
    
    length = 0
    for char in processed_text:
        code = ord(char)
        if (0x00 <= code <= 0x80) or (code == 0xf8f0) or (0xff61 <= code <= 0xff9f):
            length += 1
        else:
            length += 2
            
    return length

@app.route('/api/me')
def get_current_user():
    user_data = { 'logged_in': False }
    if 'user_id' in session:
        user_data['logged_in'] = True
        user_data['user'] = {
            'id': session['user_id'],
            'screen_name': session['screen_name'],
            'name': session.get('name'),
            'profile_image_url': session.get('profile_image_url'),
            'isAdmin': session['screen_name'] in [s.strip() for s in os.environ.get('ADMIN_SCREEN_NAMES', 'dummy_admin1,dummy_admin2').split(',') if s.strip()]
        }
        # --- ▼▼▼ set ではなく list を使うように修正 ▼▼▼ ---
        # セッションから 'judge_for_contest_ids' をリストとして取得 (なければ空のリスト)
        judge_contest_ids = session.get('judge_for_contest_ids', [])
        user_data['judge_contests'] = judge_contest_ids # リストをそのまま返す
        # --- ▲▲▲ ここまで ▲▲▲ ---
    return jsonify(user_data)

@app.route('/api/logout')
def logout():
    session.clear()
    return jsonify({'message': 'Logged out successfully'})




@app.route('/api/admin/contests', methods=['POST'])
def create_contest():
    if 'user_id' not in session: return jsonify({"error": "Login required"}), 401
    allowed_admins = [s.strip() for s in os.environ.get('ADMIN_SCREEN_NAMES', 'dummy_admin1,dummy_admin2').split(',') if s.strip()]
    if session.get('screen_name') not in allowed_admins:
        return jsonify({"error": "Forbidden: Admins only"}), 403

    data = request.get_json()
    try:
        has_qualifier = data.get('hasQualifier', False)

        # 通常/決勝の時刻をパース
        start_time_utc = datetime.fromisoformat(data['startTime'].replace('Z', '+00:00'))
        end_time_utc = datetime.fromisoformat(data['endTime'].replace('Z', '+00:00'))
        voting_end_time_utc = datetime.fromisoformat(data['votingEndTime'].replace('Z', '+00:00'))

        has_theme = data.get('hasTheme', True)
        theme_value = data.get('theme') if has_theme else None
        
        c_type = data.get('type', 'grandprix')
        scoring_method = data.get('scoringMethod', 'both')
        image_rule = data.get('imageRule', 'optional')
        is_voting_visible = data.get('isVotingVisible', True)
        advancement_numerator = int(data.get('advancementNumerator')) if data.get('advancementNumerator') else None
        advancement_denominator = int(data.get('advancementDenominator')) if data.get('advancementDenominator') else None
        general_vote_weight = int(data.get('generalVoteWeight', 50))
        judge_max_score = int(data.get('judgeMaxScore', 10))
        judge_password = data.get('judgePassword')

        if has_qualifier:
            q_start_str = data.get('qualifierStartTime')
            q_end_str = data.get('qualifierEndTime')
            q_voting_end_str = data.get('qualifierVotingEndTime')
            
            q_start_time_utc = datetime.fromisoformat(q_start_str.replace('Z', '+00:00')) if q_start_str else start_time_utc
            q_end_time_utc = datetime.fromisoformat(q_end_str.replace('Z', '+00:00')) if q_end_str else end_time_utc
            q_voting_end_time_utc = datetime.fromisoformat(q_voting_end_str.replace('Z', '+00:00')) if q_voting_end_str else voting_end_time_utc

            qualifier_contest = Contest(
                name=f"{data['name']} 予選",
                theme=data.get('qualifierTheme') if data.get('qualifierHasTheme') else None,
                has_theme=data.get('qualifierHasTheme', False),
                has_qualifier=False,
                type=c_type,
                scoring_method=data.get('qualifierScoringMethod', 'both'),
                image_rule=data.get('qualifierImageRule', 'optional'),
                advancement_numerator=advancement_numerator,
                advancement_denominator=advancement_denominator,
                is_voting_visible=data.get('qualifierIsVotingVisible', True),
                start_time=q_start_time_utc,
                end_time=q_end_time_utc,
                voting_end_time=q_voting_end_time_utc,
                judge_award_advancement=data.get('qualifierJudgeAwardAdvancement', False),
                general_vote_weight=int(data.get('qualifierGeneralVoteWeight', 50)),
                judge_max_score=int(data.get('qualifierJudgeMaxScore', 10)),
                judge_password=data.get('qualifierJudgePassword')
            )
            db.session.add(qualifier_contest)
            db.session.flush() # ID取得のため

            final_contest = Contest(
                name=f"{data['name']} 決勝",
                theme=theme_value,
                has_theme=has_theme,
                has_qualifier=True,
                type=c_type,
                scoring_method=scoring_method,
                image_rule=image_rule,
                parent_contest_id=qualifier_contest.id,
                is_voting_visible=is_voting_visible,
                start_time=start_time_utc,
                end_time=end_time_utc,
                voting_end_time=voting_end_time_utc,
                judge_award_advancement=data.get('judgeAwardAdvancement', False),
                general_vote_weight=general_vote_weight,
                judge_max_score=judge_max_score,
                judge_password=judge_password
            )
            db.session.add(final_contest)
            db.session.commit()
            
            # Cloud Tasksのスケジュール
            schedule_contest_task(qualifier_contest.id, 'post_start', qualifier_contest.start_time)
            schedule_contest_task(qualifier_contest.id, 'voting_start', qualifier_contest.end_time)
            schedule_contest_task(qualifier_contest.id, 'result_announce', qualifier_contest.voting_end_time)
            
            schedule_contest_task(final_contest.id, 'post_start', final_contest.start_time)
            schedule_contest_task(final_contest.id, 'voting_start', final_contest.end_time)
            schedule_contest_task(final_contest.id, 'result_announce', final_contest.voting_end_time)
            
            return jsonify({"message": "Contests created successfully", "id": final_contest.id, "qualifier_id": qualifier_contest.id}), 201

        else:
            new_contest = Contest(
                name=data['name'],
                theme=theme_value,
                has_theme=has_theme,
                has_qualifier=False,
                type=c_type,
                scoring_method=scoring_method,
                image_rule=image_rule,
                is_voting_visible=is_voting_visible,
                start_time=start_time_utc,
                end_time=end_time_utc,
                voting_end_time=voting_end_time_utc,
                judge_award_advancement=data.get('judgeAwardAdvancement', False),
                general_vote_weight=general_vote_weight,
                judge_max_score=judge_max_score,
                judge_password=judge_password
            )
            db.session.add(new_contest)
            db.session.commit()
            
            schedule_contest_task(new_contest.id, 'post_start', new_contest.start_time)
            schedule_contest_task(new_contest.id, 'voting_start', new_contest.end_time)
            schedule_contest_task(new_contest.id, 'result_announce', new_contest.voting_end_time)
            
            return jsonify({"message": "Contest created successfully", "id": new_contest.id}), 201
    except Exception as e:
        db.session.rollback()
        print(f"!!! ERROR at /api/admin/contests: {e}")
        traceback.print_exc()
        return jsonify({"error": "Failed to create contest"}), 500




# --- Mock API Endpoints ---
@app.route('/')
def index():
    return "ネタツイ大会バックエンド"

# Simple cache for get_contests
_contests_cache = None
_contests_cache_time = 0

@app.route('/api/contests')
def get_contests():
    global _contests_cache, _contests_cache_time
    import time
    if _contests_cache and time.time() - _contests_cache_time < 5:
        return _contests_cache

    try:
        contests = Contest.query.order_by(Contest.start_time.desc()).all()
        now = datetime.now(timezone.utc)
        ongoing, voting, upcoming, closed_list, closed_data = [], [], [], [], []
        latest_result = None

        # 投稿者数・投票者数・審査員数を大会ごとに一括で集計 (N+1問題の解消)
        post_counts = db.session.query(Post.contest_id, func.count(distinct(Post.user_id))).group_by(Post.contest_id).all()
        post_count_map = {row[0]: row[1] for row in post_counts}

        vote_counts = db.session.query(Vote.contest_id, func.count(distinct(Vote.user_id))).group_by(Vote.contest_id).all()
        vote_count_map = {row[0]: row[1] for row in vote_counts}

        judge_counts = db.session.query(Vote.contest_id, func.count(distinct(Vote.user_id))).filter(Vote.is_judge_vote == True).group_by(Vote.contest_id).all()
        judge_count_map = {row[0]: row[1] for row in judge_counts}

        for contest in contests:
            st = contest.start_time.replace(tzinfo=timezone.utc) if contest.start_time else None
            et = contest.end_time.replace(tzinfo=timezone.utc) if contest.end_time else None
            vt = contest.voting_end_time.replace(tzinfo=timezone.utc) if contest.voting_end_time else None
            
            # 事前集計した辞書から取得
            total_posters = post_count_map.get(contest.id, 0)
            total_voters = vote_count_map.get(contest.id, 0)
            total_judges = judge_count_map.get(contest.id, 0)
            
            c_data = { 
                'id': contest.id, 'name': contest.name, 'hasTheme': contest.has_theme, 'theme': contest.theme, 'hasQualifier': contest.has_qualifier, 
                'type': contest.type, 'scoringMethod': contest.scoring_method, 'imageRule': contest.image_rule, 'isVotingVisible': contest.is_voting_visible,
                'advancementNumerator': contest.advancement_numerator, 'advancementDenominator': contest.advancement_denominator, 'parentContestId': contest.parent_contest_id,
                'judgeAwardAdvancement': contest.judge_award_advancement,
                'startTime': st.astimezone(JST).isoformat() if st else None, 'endTime': et.astimezone(JST).isoformat() if et else None, 'votingEndTime': vt.astimezone(JST).isoformat() if vt else None, 
                'generalVoteWeight': contest.general_vote_weight, 'judgeMaxScore': contest.judge_max_score,
                # 追加フィールド
                'totalPosters': total_posters,
                'totalVoters': total_voters,
                'totalJudges': total_judges
            }
            
            if st and et and st <= now < et: ongoing.append(c_data)
            elif et and vt and et <= now < vt: voting.append(c_data)
            elif st and now < st: upcoming.append(c_data)
            elif vt and now >= vt: closed_list.append(contest); closed_data.append(c_data)
            
        if closed_data: 
            # closed_dataはすでにソートされている(contestsループ順)ので、先頭が最新
            latest = closed_data[0]
            latest_result = {
                'contest_id': latest['id'], 'contest_name': latest['name'], 'theme': latest['theme'],
                'totalPosters': latest['totalPosters'], 'totalVoters': latest['totalVoters'], 'totalJudges': latest['totalJudges']
            }
            
        upcoming.reverse()
        result = jsonify({'ongoing': ongoing, 'voting': voting, 'upcoming': upcoming, 'closed': closed_data, 'latestResult': latest_result})
        _contests_cache = result
        _contests_cache_time = time.time()
        return result
    except Exception as e: return jsonify({"error": "Failed"}), 500

@app.route('/api/contests/<int:id>')
def get_contest_details(id):
    import time
    start_time = time.time()
    try:
        contest = Contest.query.get_or_404(id)
        t1 = time.time()
        logger.info(f"[get_contest_details] get_or_404: {t1-start_time:.4f}s")
        user_id = session.get('user_id')
        is_advanced_to_final = None
        if user_id and contest.parent_contest_id:
            qualifier_result = ContestResult.query.filter_by(contest_id=contest.parent_contest_id, user_id=user_id).first()
            is_advanced_to_final = qualifier_result.is_advanced if qualifier_result else False
        
        t2 = time.time()
        logger.info(f"[get_contest_details] TOTAL TIME: {t2-start_time:.4f}s")
        return jsonify({
            'id': contest.id,
            'name': contest.name,
            'theme': contest.theme, # お題 (Noneの場合もある)
            'startTime': contest.start_time.replace(tzinfo=timezone.utc).astimezone(JST).isoformat(),
            'endTime': contest.end_time.replace(tzinfo=timezone.utc).astimezone(JST).isoformat(),
            'votingEndTime': contest.voting_end_time.replace(tzinfo=timezone.utc).astimezone(JST).isoformat(),
            'generalVoteWeight': contest.general_vote_weight,
            'judgeMaxScore': contest.judge_max_score,
            'hasTheme': contest.has_theme,
            'hasQualifier': contest.has_qualifier,
            'type': contest.type,
            'scoringMethod': contest.scoring_method,
            'imageRule': contest.image_rule,
            'isVotingVisible': contest.is_voting_visible,
            'advancementNumerator': contest.advancement_numerator,
            'advancementDenominator': contest.advancement_denominator,
            'judgeAwardAdvancement': contest.judge_award_advancement,
            'parentContestId': contest.parent_contest_id,
            'isAdvancedToFinal': is_advanced_to_final,
            'resultCommentTop': contest.result_comment_top,
            'resultCommentBottom': contest.result_comment_bottom
        })
    except Exception as e:
        print(f"!!! ERROR at /api/contests/{id}: {e}")
        return jsonify({"error": "Contest not found"}), 404

@app.route('/api/contests/<int:id>/posts')
def get_posts_for_contest(id):
    import time
    start_time = time.time()
    try:
        Contest.query.get_or_404(id)
        t1 = time.time()
        logger.info(f"[get_posts] get_or_404: {t1-start_time:.4f}s")
        posts = Post.query.filter_by(contest_id=id).order_by(Post.created_at.desc()).all()
        t2 = time.time()
        logger.info(f"[get_posts] posts query: {t2-t1:.4f}s")
        
        user_id = session.get('user_id')
        user_votes = {}
        user_has_voted = False 
        user_votes_map = {} 

        if user_id:
            votes = Vote.query.filter_by(user_id=user_id, contest_id=id).all()
            t3 = time.time()
            logger.info(f"[get_posts] votes query: {t3-t2:.4f}s")
            user_votes = {vote.post_id: vote.count for vote in votes}
            if votes:
                user_has_voted = True
            for v in votes:
                user_votes_map[v.post_id] = {
                    'count': v.count,
                    'is_judge_award': v.is_judge_award,
                    'judge_comment': v.judge_comment
                }
            from models import Comment
            user_comments = Comment.query.filter(Comment.user_id == user_id, Comment.post_id.in_([p.id for p in posts])).all()
            user_commented_post_ids = {c.post_id for c in user_comments}
            t4 = time.time()
            logger.info(f"[get_posts] comments query: {t4-t3:.4f}s")
        else:
            user_commented_post_ids = set()
            t4 = time.time()

        total_posters = db.session.query(func.count(distinct(Post.user_id))).filter(Post.contest_id == id).scalar() or 0
        t5 = time.time()
        logger.info(f"[get_posts] total_posters query: {t5-t4:.4f}s")

        posts_data = []
        for post in posts:
            my_vote = user_votes_map.get(post.id, {})
            posts_data.append({
                'id': post.id,
                'content': post.content,
                'created_at': post.created_at.replace(tzinfo=timezone.utc).astimezone(JST).isoformat(),
                'user_id': post.user_id,
                'myVotes': user_votes.get(post.id, 0),
                'images': post.images,
                'myJudgeAward': my_vote.get('is_judge_award', False),
                'myJudgeComment': my_vote.get('judge_comment', None),
                'hasCommented': post.id in user_commented_post_ids
            })
        
        t6 = time.time()
        logger.info(f"[get_posts] loop formatting: {t6-t5:.4f}s")
        logger.info(f"[get_posts] TOTAL TIME: {t6-start_time:.4f}s")
        return jsonify({
            'posts': posts_data,
            'userHasVotedInContest': user_has_voted,
            'totalPosters': total_posters
        })
        # --- ▲▲▲ ここまで ▲▲▲ ---
    except Exception as e:
        print(f"!!! ERROR at GET /api/contests/{id}/posts: {e}")
        return jsonify({"error": "Failed to fetch posts"}), 500



@app.route('/api/contests/<int:id>/posts', methods=['POST'])
def submit_post(id):
    if 'user_id' not in session: return jsonify({"error": "Login required"}), 401
    user_id = session['user_id']

    # FormDataで来るため request.form と request.files を使う
    content = request.form.get('content', '')
    files = request.files.getlist('images') # 複数ファイル

    # バリデーション: テキストも画像もなければエラー
    if not content and not files:
        return jsonify({"error": "Content or images required"}), 400
    
    # 画像枚数制限
    if len(files) > 4:
        return jsonify({"error": "Max 4 images allowed"}), 400

    try:
        c = Contest.query.get_or_404(id); now = datetime.now(timezone.utc)
        if not (c.start_time.replace(tzinfo=timezone.utc) <= now < c.end_time.replace(tzinfo=timezone.utc)): 
            return jsonify({"error": "Outside period"}), 403
            
        # 画像必須のバリデーション
        valid_files = [f for f in files if f and f.filename]
        if c.image_rule == 'required' and len(valid_files) == 0:
            return jsonify({"error": "画像を最低1枚添付してください"}), 400
            
        # 決勝コンテストの場合の進出者チェック
        if c.parent_contest_id:
            qualifier_result = ContestResult.query.filter_by(contest_id=c.parent_contest_id, user_id=user_id).first()
            if not qualifier_result or not qualifier_result.is_advanced:
                return jsonify({"error": "予選を通過していないため、この大会には投稿できません"}), 403
        
        if Post.query.filter_by(user_id=user_id, contest_id=id).first():
             return jsonify({"error": "Already posted"}), 409

        # 画像アップロード処理
        image_urls = []
        for file in valid_files:
            if allowed_file(file.filename):
                url = save_file(file)
                image_urls.append(url)
        
        # Post作成 (images setter経由で保存)
        new_post = Post(content=content, contest_id=id, user_id=user_id)
        new_post.images = image_urls # JSON化して保存される

        db.session.add(new_post)
        db.session.commit()
        
        # レスポンス用データ
        return jsonify({
            'id': new_post.id, 
            'content': new_post.content, 
            'images': new_post.images,
            'created_at': new_post.created_at.replace(tzinfo=timezone.utc).astimezone(JST).isoformat(),
            'user_id': new_post.user_id
        }), 201

    except Exception as e: 
        db.session.rollback()
        print(f"Error: {e}")
        return jsonify({"error": "Error"}), 500
# --- ▲▲▲ ここまで ▲▲▲ ---

@app.route('/api/contests/<int:id>/vote', methods=['POST'])
def submit_votes(id):
    import time
    start_time = time.time()
    logger.info(f"==> [submit_votes] START for contest {id}")
    if 'user_id' not in session: return jsonify({"error": "Login required"}), 401
    
    user_id = session['user_id']
    data = request.get_json()
    votes_to_submit = data.get('votes') # { "postId": count }
    judge_award = data.get('judgeAward') # { "postId": 123, "comment": "..." } or null
    content = request.form.get('content', '')

    if content:
        content = content.replace('\r\n', '\n').replace('\r', '\n')

    if not isinstance(votes_to_submit, dict):
         return jsonify({"error": "Invalid vote data"}), 400
    
    # バリデーション: 文字数チェック
    if calculate_weighted_length(content) > 280:
        return jsonify({"error": "Text too long (max 280)"}), 400

    try:
        is_judge = id in session.get('judge_for_contest_ids', [])
        judge_contest_ids = session.get('judge_for_contest_ids', [])
        is_judge_voting_now = id in judge_contest_ids
        
        t0 = time.time()
        Vote.query.filter_by(user_id=user_id, contest_id=id).delete()
        t1 = time.time()
        logger.info(f"==> [submit_votes] delete took: {t1 - t0:.4f}s")

        # 期間チェック
        c = Contest.query.get_or_404(id)
        t2 = time.time()
        logger.info(f"==> [submit_votes] get_or_404 took: {t2 - t1:.4f}s")
        now = datetime.now(timezone.utc)
        if not (c.end_time.replace(tzinfo=timezone.utc) <= now < c.voting_end_time.replace(tzinfo=timezone.utc)):
             return jsonify({"error": "Outside period"}), 403
        
        max_score = c.judge_max_score if is_judge else 1

        # --- 投票データの保存 ---
        # 1. 点数投票の保存
        # N+1問題を回避するため、事前に対象のPostをバルク取得
        post_ids_to_fetch = []
        for pid_str in votes_to_submit.keys():
            try:
                post_ids_to_fetch.append(int(pid_str))
            except ValueError:
                pass
                
        posts_map = {}
        if post_ids_to_fetch:
            fetched_posts = Post.query.filter(Post.id.in_(post_ids_to_fetch)).all()
            for p in fetched_posts:
                posts_map[p.id] = p

        processed_post_ids = set()
        for pid_str, count_val in votes_to_submit.items():
            try:
                post_id = int(pid_str)
                
                # 自分の投稿への投票を禁止（事前取得したマップから検索）
                post = posts_map.get(post_id)
                if not post or post.user_id == user_id:
                    continue

                count = float(count_val)
                if is_judge_voting_now:
                    if not (0 <= count <= max_score): raise ValueError
                else:
                    if count not in (0, 1): raise ValueError
                
                # 審査員賞の対象かどうか
                is_award = False
                comment = None
                if is_judge_voting_now and judge_award and judge_award.get('postId') == post_id:
                    is_award = True
                    comment = judge_award.get('comment')

                # 投票数が正、または審査員賞であれば保存
                if count > 0 or is_award:
                    db.session.add(Vote(
                        user_id=user_id, post_id=post_id, contest_id=id,
                        count=count, is_judge_vote=is_judge_voting_now,
                        is_judge_award=is_award, judge_comment=comment
                    ))
                    processed_post_ids.add(post_id)
            except (ValueError, TypeError): continue

        # 2. 審査員賞が選択されているが、点数が0点(votesに含まれない/0)の場合のフォロー
        if is_judge_voting_now and judge_award:
            award_pid = judge_award.get('postId')
            if award_pid and award_pid not in processed_post_ids:
                # 0点で賞だけあげるケース
                db.session.add(Vote(
                    user_id=user_id, post_id=award_pid, contest_id=id,
                    count=0, is_judge_vote=True,
                    is_judge_award=True, judge_comment=judge_award.get('comment')
                ))

        t3 = time.time()
        logger.info(f"==> [submit_votes] loop took: {t3 - t2:.4f}s")
        db.session.commit()
        t4 = time.time()
        logger.info(f"==> [submit_votes] commit took: {t4 - t3:.4f}s")
        logger.info(f"==> [submit_votes] FINISHED in {t4 - start_time:.4f}s")
        return jsonify({"message": "Voted"}), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"==> [submit_votes] ERROR in {time.time() - start_time:.4f}s: {e}")
        print(f"Error: {e}")
        return jsonify({"error": "Error"}), 500
    
@app.route('/api/contests/<int:id>/results')
def get_contest_results(id):
    try:
        user_id = session.get('user_id'); c = Contest.query.get_or_404(id); now = datetime.now(timezone.utc)
        if now < c.voting_end_time.replace(tzinfo=timezone.utc): return jsonify({"error": "Voting ongoing"}), 403
        
        all_posts = Post.query.options(joinedload(Post.user)).filter(Post.contest_id == id).all()
        if not all_posts: return jsonify({'contest': {'id': c.id, 'name': c.name, 'theme': c.theme}, 'results': [], 'judgeAwards': [], 'totalPosters': 0, 'totalVoters': 0})
        
        contest_results = get_cached_contest_results(id)
        
        # --- 審査員賞の取得 ---
        judge_awards_query = db.session.query(Vote, User, Post).join(User, Vote.user_id == User.id).join(Post, Vote.post_id == Post.id).filter(Vote.contest_id == id, Vote.is_judge_award == True).all()
        judge_awards_data = []
        award_badges = {} # post_id -> ["審査員名賞", ...]

        for vote, judge_user, post in judge_awards_query:
            award_name = f"{judge_user.name}賞"
            # 結果リスト表示用バッジ
            if post.id not in award_badges: award_badges[post.id] = []
            award_badges[post.id].append(award_name)
            
            # 審査員賞タブ表示用データ
            judge_awards_data.append({
                'judge': { 'screen_name': judge_user.screen_name, 'name': judge_user.name, 'profile_image_url': judge_user.profile_image_url },
                'comment': vote.judge_comment,
                'post': {
                    'post_id': post.id,
                    'content': post.content,
                    'images': post.images,
                    'user': { 'screen_name': post.user.screen_name, 'name': post.user.name, 'profile_image_url': post.user.profile_image_url },
                    'created_at': post.created_at.replace(tzinfo=timezone.utc).astimezone(JST).isoformat()
                }
            })

        # ... (以下、既存の結果整形ロジック) ...
        all_votes_query = db.session.query(Vote, User).join(User, Vote.user_id == User.id).filter(Vote.contest_id == id).all()
        voters_by_post = {}
        for vote, user in all_votes_query:
            if vote.post_id not in voters_by_post: voters_by_post[vote.post_id] = []
            # 投票者リスト表示: 審査員の場合は点数も表示したいのでcountを含める
            voters_by_post[vote.post_id].append({ 'screen_name': user.screen_name, 'name': user.name, 'count': vote.count, 'is_judge': vote.is_judge_vote })
        
        post_ids = [p.id for p in all_posts]
        bookmark_counts = dict(db.session.query(Bookmark.post_id, func.count(Bookmark.id)).filter(Bookmark.post_id.in_(post_ids)).group_by(Bookmark.post_id).all())
        user_bookmarks = set()
        if user_id: user_bookmarks = {p for (p,) in db.session.query(Bookmark.post_id).filter(Bookmark.user_id == user_id, Bookmark.post_id.in_(post_ids)).all()}
        comment_counts = dict(db.session.query(Comment.post_id, func.count(Comment.id)).filter(Comment.post_id.in_(post_ids)).group_by(Comment.post_id).all())
        user_commented_post_ids = set()
        if user_id: user_commented_post_ids = {c.post_id for c in Comment.query.filter_by(user_id=user_id).filter(Comment.post_id.in_(post_ids)).all()}

        results_list = []
        for post in all_posts:
            post_result = contest_results.get(post.id, {'rank': None, 'score': 0})
            post_voters = voters_by_post.get(post.id, [])
            post_voters.sort(key=lambda v: v['is_judge'], reverse=True)
            results_list.append({
                'rank': post_result['rank'],
                'post_id': post.id,
                'content': post.content,
                'images': post.images,
                'created_at': post.created_at.replace(tzinfo=timezone.utc).astimezone(JST).isoformat(),
                'score': post_result['score'],
                'user': { 'screen_name': post.user.screen_name, 'name': post.user.name, 'profile_image_url': post.user.profile_image_url },
                'voters': post_voters,
                'bookmarkCount': bookmark_counts.get(post.id, 0),
                'commentCount': comment_counts.get(post.id, 0),
                'hasCommented': post.id in user_commented_post_ids,
                'isBookmarked': post.id in user_bookmarks,
                'awards': award_badges.get(post.id, []), # バッジ情報を追加
                'is_advanced': post_result.get('is_advanced', False)
            })
        
        results_list.sort(key=lambda x: (x['rank'] is None, x['rank']))
        total_posters = db.session.query(func.count(distinct(Post.user_id))).filter(Post.contest_id == id).scalar()
        total_voters = db.session.query(func.count(distinct(Vote.user_id))).filter(Vote.contest_id == id).scalar()
        total_judges = db.session.query(func.count(distinct(Vote.user_id))).filter(Vote.contest_id == id, Vote.is_judge_vote == True).scalar()

        return jsonify({
            'contest': { 'id': c.id, 'name': c.name, 'theme': c.theme },
            'results': results_list,
            'judgeAwards': judge_awards_data, # 追加
            'totalPosters': total_posters or 0,
            'totalVoters': total_voters or 0,
            'totalJudges': total_judges or 0
        })
    except Exception as e:
        print(e); traceback.print_exc(); return jsonify({"error": "Error"}), 500
    
@app.route('/api/contests/<int:id>/judge/login', methods=['POST'])
def judge_login(id):
    if 'user_id' not in session:
        return jsonify({"error": "ログインが必要です。"}), 401

    data = request.get_json()
    password = data.get('password')

    if not password:
        return jsonify({"error": "パスワードを入力してください。"}), 400

    try:
        contest = Contest.query.get_or_404(id)
        
        if contest.scoring_method == 'user':
            return jsonify({"error": "この大会は一般投票のみのため、審査員として参加できません。"}), 400

        if contest.judge_password and contest.judge_password == password:
            # --- ▼▼▼ set ではなく list を使うように修正 ▼▼▼ ---
            # セッションからリストを取得 (なければ空のリストを作成)
            judge_contest_ids = session.get('judge_for_contest_ids', [])
            # リストに大会IDがなければ追加する
            if id not in judge_contest_ids:
                judge_contest_ids.append(id)
            session['judge_for_contest_ids'] = judge_contest_ids # 更新したリストをセッションに保存
            session.modified = True
            # --- ▲▲▲ ここまで ▲▲▲ ---

            print(f"--- Judge Login Success: User {session.get('user_id')} for Contest {id} ---")
            print(f" -> Current Judge Contests in Session: {session['judge_for_contest_ids']}")

            return jsonify({"redirectUrl": f"/venue/{id}"}), 200
        else:
            print(f"--- Judge Login Failed: User {session.get('user_id')} for Contest {id} ---")
            return jsonify({"error": "パスワードが正しくありません。"}), 401

    except Exception as e:
        print(f"!!! ERROR at POST /api/contests/{id}/judge/login: {e}")
        traceback.print_exc()
        return jsonify({"error": "審査員認証中にエラーが発生しました。"}), 500
    
@app.route('/api/profile/<string:screen_name>')
def get_user_profile_updated(screen_name):
    try:
        viewer_id = session.get('user_id')
        target_user = User.query.filter_by(screen_name=screen_name).first()
        if not target_user: return jsonify({"error": "Not found"}), 404
        user_id = target_user.id
        now = datetime.now(timezone.utc)
        results_cache = {}

        # --- 共通整形関数 ---
        def format_posts(posts_query_result):
            target_posts = []
            target_post_ids = []
            
            # 1. 期間判定とID収集
            for post in posts_query_result:
                # 投票終了していない大会の投稿は表示しない（ネタバレ防止）
                if now < post.contest.voting_end_time.replace(tzinfo=timezone.utc):
                    continue
                target_posts.append(post)
                target_post_ids.append(post.id)
            
            if not target_posts:
                return []

            # 2. 一括データ取得 (パフォーマンス向上のため、フルORMオブジェクトではなく必要なカラムのみタプルで取得)
            # (a) 投票データ (投票者リスト構築用)
            votes_data = db.session.query(Vote.post_id, Vote.count, Vote.is_judge_vote, Vote.user_id, User.screen_name, User.name)\
                .join(User, Vote.user_id == User.id)\
                .filter(Vote.post_id.in_(target_post_ids)).all()
            voters_map = {} # post_id -> [voter_dict, ...]
            my_votes_map = {} # post_id -> count (閲覧者が投票した数)

            for v_post_id, v_count, v_is_judge_vote, v_user_id, u_screen_name, u_name in votes_data:
                if v_post_id not in voters_map: voters_map[v_post_id] = []
                # 審査員の場合は点数も表示したいのでcountを含める
                voters_map[v_post_id].append({
                    'screen_name': u_screen_name,
                    'name': u_name,
                    'count': v_count,
                    'is_judge': v_is_judge_vote
                })
                # 閲覧者の投票状況を確認
                if viewer_id and v_user_id == viewer_id:
                    my_votes_map[v_post_id] = v_count

            # (b) 審査員賞データ (バッジ用)
            awards_data = db.session.query(Vote.post_id, User.name)\
                .join(User, Vote.user_id == User.id)\
                .filter(Vote.post_id.in_(target_post_ids), Vote.is_judge_award == True).all()
            awards_map = {} # post_id -> ["xxx賞", ...]
            for a_post_id, u_name in awards_data:
                if a_post_id not in awards_map: awards_map[a_post_id] = []
                awards_map[a_post_id].append(f"{u_name}賞")

            # (c) ブックマーク数
            bm_counts = dict(db.session.query(Bookmark.post_id, func.count(Bookmark.id)).filter(Bookmark.post_id.in_(target_post_ids)).group_by(Bookmark.post_id).all())
            
            # (d) 閲覧者のブックマーク状況
            viewer_bms = set()
            if viewer_id:
                viewer_bms = {p for (p,) in db.session.query(Bookmark.post_id).filter(Bookmark.user_id == viewer_id, Bookmark.post_id.in_(target_post_ids)).all()}

            # 3. 整形
            formatted = []
            for post in target_posts:
                cid = post.contest_id
                # ランキング計算 (キャッシュ利用)
                if cid not in results_cache:
                    results_cache[cid] = get_cached_contest_results(cid)
                res = results_cache[cid].get(post.id)
                
                # 投票者リストのソート (審査員優先)
                post_voters = voters_map.get(post.id, [])
                post_voters.sort(key=lambda v: v['is_judge'], reverse=True)

                formatted.append({
                    'post_id': post.id,
                    'content': post.content,
                    'images': post.images,
                    'created_at': post.created_at.replace(tzinfo=timezone.utc).astimezone(JST).isoformat(),
                    'contest': {
                        'id': post.contest.id,
                        'name': post.contest.name,
                        'theme': post.contest.theme,
                        'scoringMethod': post.contest.scoring_method
                    },
                    'user': {
                        'screen_name': post.user.screen_name,
                        'name': post.user.name,
                        'profile_image_url': post.user.profile_image_url
                    },
                    'rank': res['rank'] if res else None,
                    'score': res['score'] if res else 0,
                    'bookmarkCount': bm_counts.get(post.id, 0),
                    'isBookmarked': post.id in viewer_bms,
                    'voters': post_voters,        # 追加: 投票者一覧
                    'awards': awards_map.get(post.id, []), # 追加: 審査員賞バッジ
                    'myVotes': my_votes_map.get(post.id, 0) # 追加: 自分の投票数
                })
            return formatted

        # ユーザーの投稿
        user_posts_raw = Post.query.filter_by(user_id=user_id).options(joinedload(Post.contest), joinedload(Post.user)).order_by(Post.created_at.desc()).all()
        
        # ブックマークした投稿
        bookmarks_raw = db.session.query(Post).join(Bookmark, Post.id == Bookmark.post_id).filter(Bookmark.user_id == user_id).options(joinedload(Post.user), joinedload(Post.contest)).order_by(Bookmark.created_at.desc()).all()

        # いいねした投稿 (一般投票かつcount>0)
        liked_posts_raw = db.session.query(Post).join(Vote, Post.id == Vote.post_id)\
            .filter(Vote.user_id == user_id, Vote.is_judge_vote == False, Vote.count > 0)\
            .options(joinedload(Post.contest), joinedload(Post.user))\
            .order_by(Vote.created_at.desc()).all()

        return jsonify({
            'user': {
                'id': target_user.id,
                'screen_name': target_user.screen_name,
                'name': target_user.name,
                'profile_image_url': target_user.profile_image_url
            },
            'posts': format_posts(user_posts_raw),
            'bookmarks': format_posts(bookmarks_raw),
            'likes': format_posts(liked_posts_raw)
        })

    except Exception as e:
        print(e)
        traceback.print_exc()
        return jsonify({"error": "Error"}), 500
    


@app.route('/api/contests/<int:contest_id>/posts/<int:post_id>', methods=['PUT'])
def update_post(contest_id, post_id):
    if 'user_id' not in session: return jsonify({"error": "Login required"}), 401
    user_id = session['user_id']

    new_content = None
    
    # JSONとFormDataの判別
    if request.content_type and request.content_type.startswith('application/json'):
        data = request.get_json()
        new_content = data.get('content')
        kept_images = data.get('kept_images', [])
        files = []
    else:
        new_content = request.form.get('content')
        kept_images_str = request.form.get('kept_images', '[]')
        try: kept_images = json.loads(kept_images_str)
        except: kept_images = []
        files = request.files.getlist('images')

    if new_content:
        new_content = new_content.replace('\r\n', '\n').replace('\r', '\n')

    # テキストも画像もなければエラー（ただし画像全削除＆テキストありはOK）
    if not new_content and not kept_images and not files: return jsonify({"error": "No content"}), 400

    if new_content and calculate_weighted_length(new_content) > 280:
        return jsonify({"error": "Text too long (max 280)"}), 400
    
    try:
        post_to_edit = Post.query.filter_by(id=post_id, user_id=user_id, contest_id=contest_id).first()
        if not post_to_edit: return jsonify({"error": "Not found"}), 404
        c = Contest.query.get(contest_id); now = datetime.now(timezone.utc)
        if not (c.start_time.replace(tzinfo=timezone.utc) <= now < c.end_time.replace(tzinfo=timezone.utc)): return jsonify({"error": "Outside period"}), 403
        
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
        return jsonify({
            'id': post_to_edit.id, 
            'content': post_to_edit.content, 
            'images': post_to_edit.images, 
            'created_at': post_to_edit.created_at.replace(tzinfo=timezone.utc).astimezone(JST).isoformat(), 
            'user_id': post_to_edit.user_id, 
            'myVotes': 0
        }), 200
    except Exception as e: 
        db.session.rollback()
        print(e)
        return jsonify({"error": "Error"}), 500

@app.route('/api/contests/<int:contest_id>/posts/<int:post_id>', methods=['DELETE'])
def delete_post(contest_id, post_id):
    if 'user_id' not in session: return jsonify({"error": "Login required"}), 401
    user_id = session['user_id']
    try:
        post_to_delete = Post.query.filter_by(id=post_id, user_id=user_id, contest_id=contest_id).first()
        if not post_to_delete: return jsonify({"error": "Not found"}), 404
        
        c = Contest.query.get(contest_id)
        now = datetime.now(timezone.utc)
        if not (c.start_time.replace(tzinfo=timezone.utc) <= now < c.end_time.replace(tzinfo=timezone.utc)): 
            return jsonify({"error": "Outside period"}), 403
            
        if post_to_delete.images:
            for url in post_to_delete.images:
                try: delete_file(url)
                except: pass
                
        Vote.query.filter_by(post_id=post_id).delete()
        Comment.query.filter_by(post_id=post_id).delete()
        Notification.query.filter_by(post_id=post_id).delete()
        Bookmark.query.filter_by(post_id=post_id).delete()
        ContestResult.query.filter_by(post_id=post_id).delete()
        
        db.session.delete(post_to_delete)
        db.session.commit()
        return jsonify({"message": "Deleted successfully"}), 200
    except Exception as e:
        db.session.rollback()
        print(e)
        return jsonify({"error": "Error"}), 500
    
@app.route('/api/admin/contests/management')
def get_management_contests():
    if 'user_id' not in session: return jsonify({"error": "Login required"}), 401
    allowed_admins = [s.strip() for s in os.environ.get('ADMIN_SCREEN_NAMES', 'dummy_admin1,dummy_admin2').split(',') if s.strip()]
    if session.get('screen_name') not in allowed_admins:
        return jsonify({"error": "Forbidden: Admins only"}), 403
    
    try:
        now = datetime.now(timezone.utc)
        # 投票終了時間が現在時刻より未来の大会を取得 (upcoming, ongoing, voting)
        # 開始時間が新しい順 (最近作成されたものが上に来る)
        active_contests = Contest.query.filter(
            Contest.voting_end_time >= now
        ).order_by(Contest.start_time.desc()).all()

        contests_data = []
        for contest in active_contests:
            contests_data.append({
                'id': contest.id,
                'name': contest.name,
                'theme': contest.theme if contest.has_theme else None,
                'hasQualifier': contest.has_qualifier,
                'startTime': contest.start_time.replace(tzinfo=timezone.utc).astimezone(JST).isoformat(),
                'endTime': contest.end_time.replace(tzinfo=timezone.utc).astimezone(JST).isoformat(),
                'votingEndTime': contest.voting_end_time.replace(tzinfo=timezone.utc).astimezone(JST).isoformat(),
                'judgePassword': contest.judge_password, # パスワードも含める
                'type': contest.type,
                'scoringMethod': contest.scoring_method,
                'imageRule': contest.image_rule,
                'generalVoteWeight': contest.general_vote_weight,
                'judgeMaxScore': contest.judge_max_score,
                'isVotingVisible': contest.is_voting_visible,
                'advancementNumerator': contest.advancement_numerator,
                'advancementDenominator': contest.advancement_denominator,
                'judgeAwardAdvancement': contest.judge_award_advancement,
                'resultCommentTop': contest.result_comment_top,
                'resultCommentBottom': contest.result_comment_bottom
            })
        return jsonify(contests_data)
    except Exception as e:
        print(f"!!! ERROR at GET /api/admin/contests/management: {e}")
        traceback.print_exc()
        return jsonify({"error": "Failed to fetch contests for management"}), 500
# --- ▲▲▲ ここまで ▲▲▲ ---

@app.route('/api/admin/contests/<int:id>', methods=['PUT'])
def update_contest(id):
    if 'user_id' not in session: return jsonify({"error": "Login required"}), 401
    allowed_admins = [s.strip() for s in os.environ.get('ADMIN_SCREEN_NAMES', 'dummy_admin1,dummy_admin2').split(',') if s.strip()]
    if session.get('screen_name') not in allowed_admins:
        return jsonify({"error": "Forbidden: Admins only"}), 403

    contest = Contest.query.get(id)
    if not contest:
        return jsonify({"error": "Contest not found"}), 404

    data = request.get_json()
    try:
        # 更新可能なフィールドの更新
        if 'name' in data: contest.name = data['name']
        if 'theme' in data: contest.theme = data['theme'] if data.get('hasTheme') else None
        if 'hasTheme' in data: contest.has_theme = data['hasTheme']
        if 'type' in data: contest.type = data['type']
        if 'scoringMethod' in data: contest.scoring_method = data['scoringMethod']
        if 'imageRule' in data: contest.image_rule = data['imageRule']
        if 'isVotingVisible' in data: contest.is_voting_visible = data['isVotingVisible']
        if 'advancementNumerator' in data: contest.advancement_numerator = int(data['advancementNumerator']) if data['advancementNumerator'] else None
        if 'advancementDenominator' in data: contest.advancement_denominator = int(data['advancementDenominator']) if data['advancementDenominator'] else None
        if 'generalVoteWeight' in data: contest.general_vote_weight = int(data['generalVoteWeight'])
        if 'judgeMaxScore' in data: contest.judge_max_score = int(data['judgeMaxScore'])
        if 'judgePassword' in data: contest.judge_password = data['judgePassword']
        
        # 時刻の更新 (ISOフォーマットを想定)
        if 'startTime' in data: contest.start_time = datetime.fromisoformat(data['startTime'].replace('Z', '+00:00'))
        if 'endTime' in data: contest.end_time = datetime.fromisoformat(data['endTime'].replace('Z', '+00:00'))
        if 'votingEndTime' in data: contest.voting_end_time = datetime.fromisoformat(data['votingEndTime'].replace('Z', '+00:00'))

        # コメントの更新
        if 'resultCommentTop' in data: contest.result_comment_top = data['resultCommentTop']
        if 'resultCommentBottom' in data: contest.result_comment_bottom = data['resultCommentBottom']
        
        # 審査員賞での決勝進出設定の更新
        if 'judgeAwardAdvancement' in data: contest.judge_award_advancement = data['judgeAwardAdvancement']
        if 'qualifierJudgeAwardAdvancement' in data: contest.judge_award_advancement = data['qualifierJudgeAwardAdvancement'] # フロントの名称揺れ対応

        db.session.commit()
        
        # 時刻が変更された可能性があるのでタスクを再スケジュール
        schedule_contest_task(contest.id, 'post_start', contest.start_time)
        schedule_contest_task(contest.id, 'voting_start', contest.end_time)
        schedule_contest_task(contest.id, 'result_announce', contest.voting_end_time)

        return jsonify({"message": "Contest updated successfully"}), 200
    except Exception as e:
        db.session.rollback()
        print(f"!!! ERROR at PUT /api/admin/contests/{id}: {e}")
        traceback.print_exc()
        return jsonify({"error": "Failed to update contest"}), 500

# --- ▼▼▼ 大会削除APIを新設 ▼▼▼ ---
@app.route('/api/admin/contests/<int:id>', methods=['DELETE'])
def delete_contest(id):
    if 'user_id' not in session: return jsonify({"error": "Login required"}), 401
    allowed_admins = [s.strip() for s in os.environ.get('ADMIN_SCREEN_NAMES', 'dummy_admin1,dummy_admin2').split(',') if s.strip()]
    if session.get('screen_name') not in allowed_admins:
        return jsonify({"error": "Forbidden: Admins only"}), 403

    try:
        contest_to_delete = Contest.query.get(id)
        if not contest_to_delete:
            return jsonify({"error": "削除対象の大会が見つかりません。"}), 404

        # --- ▼▼▼ 関連データの削除処理を追加 ▼▼▼ ---
        # 1. 関連する投票(Vote)を削除
        Vote.query.filter_by(contest_id=id).delete()
        # 2. 関連する投稿(Post)を削除
        Post.query.filter_by(contest_id=id).delete()
        # 3. 中間コミット (任意だが、ステップを分ける場合は推奨)
        # db.session.commit() # ここでコミットしても良い
        # --- ▲▲▲ ここまで ▲▲▲ ---

        # 4. 大会(Contest)自体を削除
        db.session.delete(contest_to_delete)
        db.session.commit() # 最終コミット

        print(f"--- Contest Deleted: ID={id} ---")
        return jsonify({"message": "大会が正常に削除されました。"}), 200
    except Exception as e:
        db.session.rollback() # エラー時はロールバック
        print(f"!!! ERROR at DELETE /api/admin/contests/{id}: {e}")
        traceback.print_exc()
        return jsonify({"error": "大会の削除中にエラーが発生しました。"}), 500

# --- ▼▼▼ News API ▼▼▼ ---
@app.route('/api/news', methods=['GET'])
def get_news():
    try:
        news_items = News.query.order_by(News.created_at.desc()).limit(20).all()
        return jsonify([{
            'id': item.id,
            'tweet_id': item.tweet_id,
            'created_at': item.created_at.isoformat()
        } for item in news_items]), 200
    except Exception as e:
        print(f"!!! ERROR at GET /api/news: {e}")
        return jsonify({"error": "ニュースの取得に失敗しました。"}), 500

@app.route('/api/admin/news', methods=['GET'])
def get_admin_news():
    if 'user_id' not in session: return jsonify({"error": "Login required"}), 401
    allowed_admins = [s.strip() for s in os.environ.get('ADMIN_SCREEN_NAMES', 'dummy_admin1,dummy_admin2').split(',') if s.strip()]
    if session.get('screen_name') not in allowed_admins:
        return jsonify({"error": "Forbidden: Admins only"}), 403
    try:
        news_items = News.query.order_by(News.created_at.desc()).all()
        return jsonify([{
            'id': item.id,
            'tweet_id': item.tweet_id,
            'created_at': item.created_at.isoformat()
        } for item in news_items]), 200
    except Exception as e:
        print(f"!!! ERROR at GET /api/admin/news: {e}")
        return jsonify({"error": "ニュースの取得に失敗しました。"}), 500

@app.route('/api/admin/news', methods=['POST'])
def add_news():
    if 'user_id' not in session: return jsonify({"error": "Login required"}), 401
    allowed_admins = [s.strip() for s in os.environ.get('ADMIN_SCREEN_NAMES', 'dummy_admin1,dummy_admin2').split(',') if s.strip()]
    if session.get('screen_name') not in allowed_admins:
        return jsonify({"error": "Forbidden: Admins only"}), 403
    try:
        data = request.json
        tweet_id = data.get('tweet_id')
        if not tweet_id:
            return jsonify({"error": "ツイートIDまたはURLは必須です。"}), 400
        
        import re
        match = re.search(r'status/(\d+)', tweet_id)
        if match:
            tweet_id = match.group(1)
            
        new_news = News(tweet_id=tweet_id)
        db.session.add(new_news)
        db.session.commit()
        return jsonify({"message": "ニュースを追加しました。", "id": new_news.id}), 201
    except Exception as e:
        db.session.rollback()
        print(f"!!! ERROR at POST /api/admin/news: {e}")
        return jsonify({"error": "ニュースの追加に失敗しました。"}), 500

@app.route('/api/admin/news/<int:id>', methods=['DELETE'])
def delete_news(id):
    if 'user_id' not in session: return jsonify({"error": "Login required"}), 401
    allowed_admins = [s.strip() for s in os.environ.get('ADMIN_SCREEN_NAMES', 'dummy_admin1,dummy_admin2').split(',') if s.strip()]
    if session.get('screen_name') not in allowed_admins:
        return jsonify({"error": "Forbidden: Admins only"}), 403
    try:
        news_item = News.query.get(id)
        if not news_item:
            return jsonify({"error": "ニュースが見つかりません。"}), 404
        db.session.delete(news_item)
        db.session.commit()
        return jsonify({"message": "ニュースを削除しました。"}), 200
    except Exception as e:
        db.session.rollback()
        print(f"!!! ERROR at DELETE /api/admin/news/{id}: {e}")
        return jsonify({"error": "ニュースの削除に失敗しました。"}), 500
# --- ▲▲▲ News API ▲▲▲ ---
    
@app.route('/api/posts/<int:post_id>/bookmark', methods=['POST'])
def toggle_bookmark(post_id):
    if 'user_id' not in session:
        return jsonify({"error": "ログインが必要です。"}), 401
    user_id = session['user_id']
    try:
        post = Post.query.get(post_id)
        if not post: return jsonify({"error": "投稿が見つかりません。"}), 404
        existing_bookmark = Bookmark.query.filter_by(user_id=user_id, post_id=post_id).first()
        if existing_bookmark:
            db.session.delete(existing_bookmark)
            is_bookmarked = False
        else:
            new_bookmark = Bookmark(user_id=user_id, post_id=post_id)
            db.session.add(new_bookmark)
            is_bookmarked = True
        db.session.commit()
        bookmark_count = db.session.query(func.count(Bookmark.id)).filter(Bookmark.post_id == post_id).scalar()
        return jsonify({
            "message": "ブックマークを更新しました。",
            "isBookmarked": is_bookmarked,
            "bookmarkCount": bookmark_count if bookmark_count is not None else 0
        }), 200
    except Exception as e:
        db.session.rollback()
        print(f"!!! ERROR at POST /api/posts/{post_id}/bookmark: {e}")
        traceback.print_exc()
        return jsonify({"error": "ブックマーク処理中にエラーが発生しました。"}), 500

@app.route('/api/posts/<int:post_id>/like', methods=['POST'])
def toggle_like(post_id):
    if 'user_id' not in session: return jsonify({"error": "Login required"}), 401
    user_id = session['user_id']
    
    try:
        post = Post.query.get_or_404(post_id)
        
        if post.user_id == user_id:
            return jsonify({"error": "Cannot like your own post."}), 403

        c = post.contest
        now = datetime.now(timezone.utc)
        
        # 投票期間中の一般投票は一括APIを使用するため禁止
        if now < c.voting_end_time.replace(tzinfo=timezone.utc):
            return jsonify({"error": "Voting is ongoing, use the bulk vote API."}), 403
            
        # 審査員のみの大会以外は結果発表後のいいねを禁止（スコアと混同するため）
        if c.scoring_method != 'judge':
            return jsonify({"error": "Cannot like during results when user voting is enabled."}), 403

        existing_vote = Vote.query.filter_by(user_id=user_id, post_id=post_id).first()
        is_liked = False
        
        if existing_vote:
            if existing_vote.is_judge_vote:
                return jsonify({"error": "審査員として採点済みのため、いいねは追加できません。"}), 400
            db.session.delete(existing_vote)
        else:
            new_vote = Vote(user_id=user_id, post_id=post_id, contest_id=c.id, count=1, is_judge_vote=False, is_judge_award=False)
            db.session.add(new_vote)
            is_liked = True
            
            # 通知生成
            if user_id != post.user_id:
                notification = Notification(
                    user_id=post.user_id, sender_id=user_id, type='like', post_id=post_id, contest_id=c.id
                )
                db.session.add(notification)
                
        db.session.commit()
        
        # 最新のいいね数
        like_count = Vote.query.filter_by(post_id=post_id, is_judge_vote=False, count=1).count()
        return jsonify({"isLiked": is_liked, "likeCount": like_count}), 200
    except Exception as e:
        db.session.rollback()
        print(f"Error toggling like: {e}")
        return jsonify({"error": "いいね処理中にエラーが発生しました。"}), 500

# --- Phase 4: コメント・通知機能のAPI ---

@app.route('/api/posts/<int:post_id>/comments', methods=['GET'])
def get_comments(post_id):
    post = Post.query.get_or_404(post_id)
    comments = Comment.query.filter_by(post_id=post_id).order_by(Comment.created_at.asc()).all()
    return jsonify([{
        'id': c.id,
        'user_id': c.user_id,
        'post_id': c.post_id,
        'content': c.content,
        'is_judge': c.is_judge,
        'created_at': c.created_at.replace(tzinfo=timezone.utc).astimezone(JST).isoformat(),
        'updated_at': c.updated_at.replace(tzinfo=timezone.utc).astimezone(JST).isoformat(),
        'user': {
            'name': c.user.name,
            'screen_name': c.user.screen_name,
            'profile_image_url': c.user.profile_image_url
        }
    } for c in comments])

@app.route('/api/posts/<int:post_id>/comments', methods=['POST'])
def add_comment(post_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    user_id = session['user_id']
    post = Post.query.get_or_404(post_id)
    data = request.get_json()
    raw_content = data.get('content', '')
    
    if not raw_content.strip() or len(raw_content) > 140:
        return jsonify({'error': 'Comment must be between 1 and 140 characters'}), 400
    content = raw_content
        
    existing_comment = Comment.query.filter_by(post_id=post_id, user_id=user_id).first()
    if existing_comment:
        return jsonify({'error': 'You have already commented on this post'}), 409
        
    judge_contests = session.get('judge_for_contest_ids', [])
    is_judge = post.contest_id in judge_contests

    new_comment = Comment(
        user_id=user_id,
        post_id=post_id,
        content=content,
        is_judge=is_judge
    )
    db.session.add(new_comment)
    
    # 結果期間中であれば通知作成
    contest = post.contest
    now = datetime.now(timezone.utc)
    if now >= contest.voting_end_time.replace(tzinfo=timezone.utc) and user_id != post.user_id:
        notification = Notification(
            user_id=post.user_id,
            sender_id=user_id,
            type='comment',
            post_id=post_id,
            contest_id=post.contest_id
        )
        db.session.add(notification)
        
    db.session.commit()
    return jsonify({'message': 'Comment added successfully', 'id': new_comment.id}), 201

@app.route('/api/comments/<int:comment_id>', methods=['PUT', 'DELETE'])
def modify_comment(comment_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
        
    user_id = session['user_id']
    comment = Comment.query.get_or_404(comment_id)
    
    if comment.user_id != user_id:
        return jsonify({'error': 'Forbidden'}), 403
        
    if request.method == 'DELETE':
        db.session.delete(comment)
        db.session.commit()
        return jsonify({'message': 'Comment deleted'})
        
    data = request.get_json()
    raw_content = data.get('content', '')
    if not raw_content.strip() or len(raw_content) > 140:
        return jsonify({'error': 'Invalid content length'}), 400
        
    comment.content = raw_content
    db.session.commit()
    return jsonify({'message': 'Comment updated'})

@app.route('/api/notifications', methods=['GET'])
def get_notifications():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
        
    user_id = session['user_id']
    notifications = Notification.query.filter_by(user_id=user_id)\
        .options(
            joinedload(Notification.sender),
            joinedload(Notification.post),
            joinedload(Notification.contest)
        )\
        .order_by(Notification.created_at.desc()).all()

    # コメント取得のN+1問題解消（対象のpost_idを一括取得してマッピング）
    comment_pairs = [(n.post_id, n.sender_id) for n in notifications if n.type == 'comment']
    comment_map = {}
    if comment_pairs:
        post_ids = list(set([p[0] for p in comment_pairs]))
        comments = Comment.query.filter(Comment.post_id.in_(post_ids)).order_by(Comment.created_at.desc()).all()
        for c in comments:
            key = (c.post_id, c.user_id)
            if key not in comment_map: # order_by desc なので最初に見つかったものが最新
                comment_map[key] = c.content[:40] + '...' if len(c.content) > 40 else c.content

    def get_comment_content(n):
        if n.type == 'comment':
            return comment_map.get((n.post_id, n.sender_id))
        return None

    return jsonify([{
        'id': n.id,
        'type': n.type,
        'is_read': n.is_read,
        'post_id': n.post_id,
        'contest_id': n.contest_id,
        'created_at': n.created_at.replace(tzinfo=timezone.utc).astimezone(JST).isoformat(),
        'sender': {
            'name': n.sender.name,
            'screen_name': n.sender.screen_name,
            'profile_image_url': n.sender.profile_image_url
        } if n.sender else None,
        'post': {
             'content': n.post.content[:40] + '...' if len(n.post.content) > 40 else n.post.content
        } if n.post else None,
        'comment': {
             'content': get_comment_content(n)
        } if n.type == 'comment' else None,
        'contest': {
            'name': n.contest.name,
            'type': n.contest.type
        } if n.contest else None
    } for n in notifications])

@app.route('/api/notifications/read', methods=['POST'])
def mark_notifications_read():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    user_id = session['user_id']
    
    Notification.query.filter_by(user_id=user_id, is_read=False).update({'is_read': True})
    db.session.commit()
    return jsonify({'message': 'All notifications marked as read'})

# --- Cloud Tasks Integration ---
def schedule_contest_task(contest_id, event_type, schedule_time):
    project = os.environ.get('GCP_PROJECT_ID')
    location = os.environ.get('GCP_LOCATION')
    queue = os.environ.get('GCP_QUEUE_NAME')
    handler_url = os.environ.get('TASK_HANDLER_URL') or os.environ.get('GCR_URL')

    if not all([project, location, queue, handler_url]):
        print(f"Skipping task scheduling for {event_type} - GCP configuration missing.")
        return

    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(project, location, queue)

    url = f"{handler_url}/api/tasks/contest/{contest_id}/{event_type}"
    
    task = {
        'http_request': {
            'http_method': tasks_v2.HttpMethod.POST,
            'url': url,
            'headers': {'Content-type': 'application/json'},
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
    task['schedule_time'] = timestamp

    try:
        response = client.create_task(request={'parent': parent, 'task': task})
        print(f"Created task {response.name} for {event_type} at {schedule_time}")
    except Exception as e:
        print(f"Failed to create task for {event_type}: {e}")

@app.route('/api/tasks/contest/<int:id>/<event_type>', methods=['POST'])
def handle_contest_task(id, event_type):
    # Security note: In a real app, verify the request comes from Cloud Tasks (e.g. OIDC token)
    contest = Contest.query.get(id)
    if not contest:
        return jsonify({'error': 'Contest not found'}), 404

    now = datetime.now(timezone.utc)
    changed = False

    if event_type == 'post_start':
        if contest.start_time and now >= contest.start_time.replace(tzinfo=timezone.utc) and not contest.notified_post_start:
            print(f"[{contest.id}] Post start notification (Cloud Tasks)")
            users = User.query.all()
            for u in users:
                db.session.add(Notification(user_id=u.id, type='contest_post_start', contest_id=contest.id))
            contest.notified_post_start = True
            changed = True
            
    elif event_type == 'voting_start':
        if contest.end_time and now >= contest.end_time.replace(tzinfo=timezone.utc) and not contest.notified_voting_start:
            print(f"[{contest.id}] Voting start notification (Cloud Tasks)")
            users = User.query.all()
            for u in users:
                db.session.add(Notification(user_id=u.id, type='contest_voting_start', contest_id=contest.id))
            contest.notified_voting_start = True
            changed = True

    elif event_type == 'result_announce':
        if contest.voting_end_time and now >= contest.voting_end_time.replace(tzinfo=timezone.utc) and not contest.notified_result_announce:
            print(f"[{contest.id}] Result announce notification & calculation (Cloud Tasks)")
            generate_contest_results(contest.id)
            users = User.query.all()
            for u in users:
                db.session.add(Notification(user_id=u.id, type='contest_result_announce', contest_id=contest.id))
            contest.notified_result_announce = True
            changed = True

    if changed:
        db.session.commit()
        return jsonify({'message': f'Processed {event_type}'}), 200

    return jsonify({'message': 'Task skipped (time not reached or already processed)'}), 200

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
        if contest.start_time and contest.start_time.replace(tzinfo=timezone.utc) <= now and not contest.notified_post_start:
            print(f"[{contest.id}] Post start notification")
            if all_users is None: all_users = User.query.all()
            for u in all_users:
                db.session.add(Notification(user_id=u.id, type='contest_post_start', contest_id=contest.id))
            contest.notified_post_start = True
            changed = True
            
        # 投票開始
        if contest.end_time and contest.end_time.replace(tzinfo=timezone.utc) <= now and not contest.notified_voting_start:
            print(f"[{contest.id}] Voting start notification")
            if all_users is None: all_users = User.query.all()
            for u in all_users:
                db.session.add(Notification(user_id=u.id, type='contest_voting_start', contest_id=contest.id))
            contest.notified_voting_start = True
            changed = True
            
        # 結果発表
        if contest.voting_end_time and contest.voting_end_time.replace(tzinfo=timezone.utc) <= now and not contest.notified_result_announce:
            print(f"[{contest.id}] Result announce notification & calculation")
            generate_contest_results(contest.id)
            if all_users is None: all_users = User.query.all()
            for u in all_users:
                db.session.add(Notification(user_id=u.id, type='contest_result_announce', contest_id=contest.id))
            contest.notified_result_announce = True
            changed = True
            
        if changed:
            db.session.commit()
            print(f"[{contest.id}] Committed changes")
            
    # --- 古い通知の自動削除 (30日経過) ---
    cutoff_date = now - timedelta(days=30)
    try:
        deleted_count = Notification.query.filter(Notification.created_at < cutoff_date).delete(synchronize_session=False)
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
    from models import db, User, UserStats, Contest, ContestResult
    from sqlalchemy import func, case
    print("--- update-user-stats batch started ---")
    
    gp_1st = func.sum(case(((Contest.type == 'grandprix') & (ContestResult.rank == 1), 1), else_=0)).label('gp_1st')
    gp_2nd = func.sum(case(((Contest.type == 'grandprix') & (ContestResult.rank == 2), 1), else_=0)).label('gp_2nd')
    gp_3rd = func.sum(case(((Contest.type == 'grandprix') & (ContestResult.rank == 3), 1), else_=0)).label('gp_3rd')
    daily_1st = func.sum(case(((Contest.type == 'daily') & (ContestResult.rank == 1), 1), else_=0)).label('daily_1st')
    daily_2nd = func.sum(case(((Contest.type == 'daily') & (ContestResult.rank == 2), 1), else_=0)).label('daily_2nd')
    daily_3rd = func.sum(case(((Contest.type == 'daily') & (ContestResult.rank == 3), 1), else_=0)).label('daily_3rd')
    judge_awards = func.sum(case((ContestResult.is_judge_award == True, 1), else_=0)).label('judge_awards')

    results = db.session.query(
        User.id,
        gp_1st, gp_2nd, gp_3rd,
        daily_1st, daily_2nd, daily_3rd,
        judge_awards
    ).outerjoin(ContestResult, User.id == ContestResult.user_id)\
     .outerjoin(Contest, ContestResult.contest_id == Contest.id)\
     .group_by(User.id).all()

    for row in results:
        user_id = row[0]
        stats = UserStats.query.filter_by(user_id=user_id).first()
        if not stats:
            stats = UserStats(user_id=user_id)
            db.session.add(stats)
        
        stats.gp_1st = row.gp_1st or 0
        stats.gp_2nd = row.gp_2nd or 0
        stats.gp_3rd = row.gp_3rd or 0
        stats.daily_1st = row.daily_1st or 0
        stats.daily_2nd = row.daily_2nd or 0
        stats.daily_3rd = row.daily_3rd or 0
        stats.judge_awards = row.judge_awards or 0

    db.session.commit()
    print("--- update-user-stats batch completed ---")

@app.route('/api/users', methods=['GET'])
def get_users_list():
    from models import User, UserStats
    from sqlalchemy import asc, desc, func
    
    search_query = request.args.get('q', '')
    page = request.args.get('page', 1, type=int)
    per_page = 100
    
    query = User.query.outerjoin(UserStats, User.id == UserStats.user_id).options(joinedload(User.stats))
    if search_query:
        search_term = f"%{search_query}%"
        query = query.filter(db.or_(
            User.name.ilike(search_term),
            User.screen_name.ilike(search_term),
            User.twitter_id.ilike(search_term)
        ))
        
    gp_medals = func.coalesce(UserStats.gp_1st, 0) + func.coalesce(UserStats.gp_2nd, 0) + func.coalesce(UserStats.gp_3rd, 0)
    daily_medals = func.coalesce(UserStats.daily_1st, 0) + func.coalesce(UserStats.daily_2nd, 0) + func.coalesce(UserStats.daily_3rd, 0)
    judge_awards_count = func.coalesce(UserStats.judge_awards, 0)

    query = query.order_by(
        desc(gp_medals),
        desc(judge_awards_count),
        desc(daily_medals),
        asc(User.name)
    )
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    users_data = []
    for user in pagination.items:
        stats = user.stats
        users_data.append({
            'id': user.id,
            'twitter_id': user.twitter_id,
            'name': user.name,
            'screen_name': user.screen_name,
            'profile_image_url': user.profile_image_url,
            'stats': {
                'gp_1st': stats.gp_1st if stats else 0,
                'gp_2nd': stats.gp_2nd if stats else 0,
                'gp_3rd': stats.gp_3rd if stats else 0,
                'daily_1st': stats.daily_1st if stats else 0,
                'daily_2nd': stats.daily_2nd if stats else 0,
                'daily_3rd': stats.daily_3rd if stats else 0,
                'judge_awards': stats.judge_awards if stats else 0
            }
        })
        
    return jsonify({
        'users': users_data,
        'page': pagination.page,
        'total_pages': pagination.pages,
        'total_items': pagination.total,
        'has_next': pagination.has_next,
        'has_prev': pagination.has_prev
    }), 200

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        print("Database tables created (if not existed).")
    
    # 環境変数PORTを取得（Cloud Runでは必須）、なければローカル用の5001を使う
    port = int(os.environ.get('PORT', 5001))
    
    # host='0.0.0.0' を指定してコンテナ外からのアクセスを許可する
    # 本番環境では debug=False にする
    app.run(host='0.0.0.0', port=port, debug=False)