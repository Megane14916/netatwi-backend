import os
import traceback
import logging
import uuid
import json
import boto3 # R2用
from werkzeug.utils import secure_filename
from flask import Flask, jsonify, session, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS
from requests_oauthlib import OAuth1Session
from dotenv import load_dotenv
from models import db, User, Contest, Post, Vote, Bookmark
from datetime import datetime, timezone, timedelta
from sqlalchemy import func, case, distinct
from sqlalchemy.orm import joinedload
from werkzeug.middleware.proxy_fix import ProxyFix
from urllib.parse import urlparse


load_dotenv()

# --- 環境変数の読み込みと検証 ---
db_uri = os.environ.get('SQLALCHEMY_DATABASE_URI')
secret_key = os.environ.get('SECRET_KEY')
frontend_url = os.environ.get('FRONTEND_URL').rstrip('/') #例: "https://netatwi-frontend.vercel.app"
gcp_backend_url = os.environ.get('GCR_URL') # GCPで設定したCloud RunのURL
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

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

app = Flask(__name__)

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0, x_prefix=0)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- アプリケーション設定 ---
app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', 'a-very-secret-key-that-is-secure'),
    SQLALCHEMY_DATABASE_URI=os.environ.get('SQLALCHEMY_DATABASE_URI', 'sqlite:///project.db'),

    SQLALCHEMY_ENGINE_OPTIONS={
        "pool_pre_ping": True,
        "pool_recycle": 300, # 5分ごとに接続をリサイクル（念のため）
    },
    
    # SameSite属性は 'Lax' でOK（CSRF保護のため）
    SESSION_COOKIE_SAMESITE='None',
    
    # localhost環境でのトラブルを避けるため、DOMAIN指定を削除
    # SESSION_COOKIE_DOMAIN='localhost', 
    
    # 【変更】HTTPS環境向けに True に設定
    # ※ 注意: http://localhost で動かす場合、ブラウザがCookieを送信しなくなるため
    #   ログインセッションが維持できなくなる可能性があります。
    #   ローカル開発で動作させる場合は False に戻すか、localhostをhttps化してください。
    SESSION_COOKIE_SECURE=True,
    MAX_CONTENT_LENGTH=16 * 1024 * 1024 
)

JST = timezone(timedelta(hours=9), 'JST')

# --- CORS設定 (最重要) ---
# 環境変数から読み取ったフロントエンドのURLを許可する
CORS(app, supports_credentials=True, origins=[ALLOWED_ORIGINS])
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

# --- X OAuth Login ---
X_CONSUMER_KEY = os.environ.get("X_CONSUMER_KEY")
X_CONSUMER_SECRET = os.environ.get("X_CONSUMER_SECRET")
REQUEST_TOKEN_URL = "https://api.twitter.com/oauth/request_token"
AUTHORIZE_URL = "https://api.twitter.com/oauth/authorize"
ACCESS_TOKEN_URL = "https://api.twitter.com/oauth/access_token"
USER_INFO_URL = "https://api.twitter.com/1.1/account/verify_credentials.json"



@app.before_request
def log_request_info():
    # ログイン関連のパスのみ詳細ログを出力
    if request.path.startswith("/api/login") or request.path.startswith("/api/callback"):
        logger.info(f"=== REQUEST START: {request.path} ===")
        logger.info(f"Headers: {dict(request.headers)}")
        logger.info(f"Cookies sent from browser: {request.cookies}")
        logger.info(f"Session (before processing): {dict(session)}")
        # プロキシヘッダーの確認
        logger.info(f"X-Forwarded-Proto: {request.headers.get('X-Forwarded-Proto')}")
        logger.info(f"Is Secure (Flask detected): {request.is_secure}")

@app.route("/api/login/twitter")
def twitter_login():
    try:
        # リクエスト元のオリジンを取得
        origin = request.args.get('origin') or request.headers.get('Referer')
        # オリジンが許可リストにあるか確認 (なければリストの最初=メインサイトへ)
        target_frontend = origin if origin else ALLOWED_ORIGINS[0]
        
        # セッションに「戻るべきフロントエンドのURL」を保存
        session['frontend_url'] = target_frontend.rstrip('/')

        # コールバックURLはバックエンドのURL（固定）
        # ※ここは変えなくてOK。X側から戻ってくるのは常にバックエンドのこのURLです
        callback_url = f"{request.url_root.rstrip('/')}/api/callback/twitter"
        
        # 念のためhttpが含まれていたら置換
        if callback_url.startswith("http://"):
            callback_url = callback_url.replace("http://", "https://", 1)

        logger.info(f"Generated Callback URL: {callback_url}")

        twitter = OAuth1Session(X_CONSUMER_KEY, client_secret=X_CONSUMER_SECRET, callback_uri=callback_url)
        response = twitter.fetch_request_token(REQUEST_TOKEN_URL)
        
        # セッションにトークンを保存
        session['oauth_token'] = response.get("oauth_token")
        session['oauth_token_secret'] = response.get("oauth_token_secret")

        session.modified = True
        
        logger.info(f"Saved to session - Token: {session.get('oauth_token')}")
        
        authorization_url = twitter.authorization_url(AUTHORIZE_URL)
        return redirect(authorization_url)
    except Exception as e:
        logger.error(f"!!! ERROR at /api/login/twitter: {e}")
        traceback.print_exc()
        return jsonify({"error": "Failed to connect to Twitter"}), 500

@app.route('/api/callback/twitter')
def twitter_callback():
    logger.info(f"=== CALLBACK START ===")
    logger.info(f"Session keys present: {list(session.keys())}")

    oauth_token = session.pop('oauth_token', None)
    oauth_token_secret = session.pop('oauth_token_secret', None)
    verifier = request.args.get('oauth_verifier')

    logger.info(f"Retrieved from session - Token: {oauth_token}, Verifier: {verifier}")

    target_url = session.get('frontend_url', ALLOWED_ORIGINS[0])

    if not all([oauth_token, oauth_token_secret, verifier]):
        logger.error("Missing token or verifier in callback.")
        # エラーの詳細をクエリパラメータに付与してリダイレクト
        if not oauth_token:
            reason = "session_token_missing"
        elif not verifier:
            reason = "verifier_missing"
        else:
            reason = "unknown_missing"
        return redirect(f"{target_url}?login_error={reason}") # frontend_url を使用

    try:
        oauth_session = OAuth1Session(
            client_key=X_CONSUMER_KEY, client_secret=X_CONSUMER_SECRET,
            resource_owner_key=oauth_token, resource_owner_secret=oauth_token_secret,
            verifier=verifier
        )
        access_token_data = oauth_session.fetch_access_token(ACCESS_TOKEN_URL)
        
        user_session = OAuth1Session(
            client_key=X_CONSUMER_KEY, client_secret=X_CONSUMER_SECRET,
            resource_owner_key=access_token_data.get('oauth_token'),
            resource_owner_secret=access_token_data.get('oauth_token_secret')
        )
        response = user_session.get(USER_INFO_URL)
        response.raise_for_status()
        user_data = response.json()

        user = User.query.filter_by(twitter_id=user_data.get('id_str')).first()
        if not user:
            user = User(
                twitter_id=user_data.get('id_str'), 
                screen_name=user_data.get('screen_name'),
                name = user_data.get('name'),
                profile_image_url=user_data.get('profile_image_url_https', '').replace('_normal', '')
            )
            db.session.add(user)
        else:
            user.screen_name = user_data.get('screen_name')
            user.name = user_data.get('name')
            user.profile_image_url = user_data.get('profile_image_url_https', '').replace('_normal', '')
        
        db.session.commit()
        
        session['user_id'] = user.id
        session['screen_name'] = user.screen_name
        session['name'] = user.name
        session['profile_image_url'] = user.profile_image_url

        logger.info(f"Login successful for user: {user.screen_name}")

    except Exception as e:
        print(f"!!! ERROR at /api/callback/twitter: {e}")
        traceback.print_exc()
        db.session.rollback()
        return redirect(f"{target_url}?login_error=callback_failed") # target_url を使用
    
    target_url = session.get('frontend_url', ALLOWED_ORIGINS[0])
    return redirect(target_url)

# (以降のコードは変更ありません)
# ...

def calculate_contest_results(contest_id):
    """
    計算式: 審査員得票数の合計 + (一般得票数 / 一般投票者数) * general_vote_weight
    """
    contest = Contest.query.get(contest_id)
    if not contest: return None 

    # 一般投票者の総数（ユニーク）を取得
    total_general_voters = db.session.query(func.count(distinct(Vote.user_id)))\
        .filter(Vote.contest_id == contest_id, Vote.is_judge_vote == False).scalar()
    
    if total_general_voters is None or total_general_voters == 0:
        total_general_voters = 1

    # 審査員票はそのまま合計 (重みなし)
    judge_score_col = func.sum(case((Vote.is_judge_vote == True, Vote.count), else_=0))
    # 一般票はいいね数合計
    general_votes_col = func.sum(case((Vote.is_judge_vote == False, Vote.count), else_=0))

    results_query = db.session.query(
        Vote.post_id, 
        judge_score_col.label('judge_score'), 
        general_votes_col.label('general_votes')
    ).filter(Vote.contest_id == contest_id).group_by(Vote.post_id).subquery()

    judge_score_val = func.coalesce(results_query.c.judge_score, 0)
    general_votes_val = func.coalesce(results_query.c.general_votes, 0)
    
    # 新しい計算式
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
        Post.created_at.asc()
    )

    ranked_results = []
    current_rank = 0; last_score = -1; rank_counter = 0
    
    for post, total_score in ranked_posts_query.all():
        rank_counter += 1
        current_score_val = round(total_score, 2) if total_score is not None else 0
        if current_score_val != last_score: 
            current_rank = rank_counter
            last_score = current_score_val
        ranked_results.append({'post_id': post.id, 'rank': current_rank, 'score': current_score_val})
        
    return {result['post_id']: result for result in ranked_results}

@app.route('/api/me')
def get_current_user():
    user_data = { 'logged_in': False }
    if 'user_id' in session:
        user_data['logged_in'] = True
        user_data['user'] = {
            'id': session['user_id'],
            'screen_name': session['screen_name'],
            'name': session.get('name'),
            'profile_image_url': session.get('profile_image_url')
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
    data = request.get_json()
    try:
        has_qualifier = data.get('hasQualifier', False)

        # 通常/決勝の時刻をパース
        start_time_utc = datetime.fromisoformat(data['startTime'].replace('Z', '+00:00'))
        end_time_utc = datetime.fromisoformat(data['endTime'].replace('Z', '+00:00'))
        voting_end_time_utc = datetime.fromisoformat(data['votingEndTime'].replace('Z', '+00:00'))

        # --- ▼▼▼ 予選時刻の処理を追加 ▼▼▼ ---
        qualifier_start_time_utc = None
        qualifier_end_time_utc = None
        qualifier_voting_end_time_utc = None

        if has_qualifier:
            # 予選ありの場合のみ、予選時刻データを取得・パース
            q_start_str = data.get('qualifierStartTime')
            q_end_str = data.get('qualifierEndTime')
            q_voting_end_str = data.get('qualifierVotingEndTime')
            
            # データが存在すればdatetimeオブジェクトに変換
            if q_start_str:
                qualifier_start_time_utc = datetime.fromisoformat(q_start_str.replace('Z', '+00:00'))
            if q_end_str:
                qualifier_end_time_utc = datetime.fromisoformat(q_end_str.replace('Z', '+00:00'))
            if q_voting_end_str:
                qualifier_voting_end_time_utc = datetime.fromisoformat(q_voting_end_str.replace('Z', '+00:00'))
        # --- ▲▲▲ ここまで ▲▲▲ ---

        has_theme = data.get('hasTheme', True)
        theme_value = data.get('theme') if has_theme else None
        allow_images = data.get('allowImages', True)

        new_contest = Contest(
            name=data['name'],
            theme=theme_value,
            has_theme=has_theme,
            has_qualifier=has_qualifier,
            allow_images=allow_images,
            start_time=start_time_utc, # 通常/決勝
            end_time=end_time_utc,     # 通常/決勝
            voting_end_time=voting_end_time_utc, # 通常/決勝
            # --- ▼▼▼ 予選時刻を保存 ▼▼▼ ---
            qualifier_start_time=qualifier_start_time_utc,
            qualifier_end_time=qualifier_end_time_utc,
            qualifier_voting_end_time=qualifier_voting_end_time_utc,
            # --- ▲▲▲ ここまで ▲▲▲ ---
            general_vote_weight=int(data.get('generalVoteWeight', 50)),
            judge_max_score=int(data.get('judgeMaxScore', 10)),
            judge_password=data.get('judgePassword')
        )
        db.session.add(new_contest)
        db.session.commit()
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

@app.route('/api/contests')
def get_contests():
    try:
        contests = Contest.query.order_by(Contest.start_time.desc()).all()
        now = datetime.now(timezone.utc)
        ongoing, voting, upcoming, closed_list, closed_data = [], [], [], [], []
        latest_result = None
        for contest in contests:
            st = contest.start_time.replace(tzinfo=timezone.utc) if contest.start_time else None
            et = contest.end_time.replace(tzinfo=timezone.utc) if contest.end_time else None
            vt = contest.voting_end_time.replace(tzinfo=timezone.utc) if contest.voting_end_time else None
            
            # 投稿者数・投票者数の計算
            total_posters = db.session.query(func.count(distinct(Post.user_id))).filter(Post.contest_id == contest.id).scalar() or 0
            total_voters = db.session.query(func.count(distinct(Vote.user_id))).filter(Vote.contest_id == contest.id).scalar() or 0
            total_judges = db.session.query(func.count(distinct(Vote.user_id))).filter(Vote.contest_id == contest.id, Vote.is_judge_vote == True).scalar() or 0
            
            c_data = { 
                'id': contest.id, 'name': contest.name, 'hasTheme': contest.has_theme, 'theme': contest.theme, 'hasQualifier': contest.has_qualifier, 
                'startTime': st.astimezone(JST).isoformat() if st else None, 'endTime': et.astimezone(JST).isoformat() if et else None, 'votingEndTime': vt.astimezone(JST).isoformat() if vt else None, 
                'qualifierStartTime': contest.qualifier_start_time.replace(tzinfo=timezone.utc).astimezone(JST).isoformat() if contest.qualifier_start_time else None, 
                'qualifierEndTime': contest.qualifier_end_time.replace(tzinfo=timezone.utc).astimezone(JST).isoformat() if contest.qualifier_end_time else None, 
                'qualifierVotingEndTime': contest.qualifier_voting_end_time.replace(tzinfo=timezone.utc).astimezone(JST).isoformat() if contest.qualifier_voting_end_time else None, 
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
        return jsonify({'ongoing': ongoing, 'voting': voting, 'upcoming': upcoming, 'closed': closed_data, 'latestResult': latest_result})
    except Exception as e: return jsonify({"error": "Failed"}), 500

@app.route('/api/contests/<int:id>')
def get_contest_details(id):
    try:
        contest = Contest.query.get_or_404(id)
        # DBから読み出したUTC時刻にタイムゾーン情報を付与し、JSTに変換して返す
        return jsonify({
            'id': contest.id,
            'name': contest.name,
            'theme': contest.theme, # お題 (Noneの場合もある)
            'startTime': contest.start_time.replace(tzinfo=timezone.utc).astimezone(JST).isoformat(),
            'endTime': contest.end_time.replace(tzinfo=timezone.utc).astimezone(JST).isoformat(),
            'votingEndTime': contest.voting_end_time.replace(tzinfo=timezone.utc).astimezone(JST).isoformat(),
            # --- ▼▼▼ 設定値を追加 ▼▼▼ ---
            'generalVoteWeight': contest.general_vote_weight,
            'judgeMaxScore': contest.judge_max_score,
            'hasTheme': contest.has_theme,
            'hasQualifier': contest.has_qualifier,
            'allowImages': contest.allow_images,
            # --- ▲▲▲ ここまで ▲▲▲ ---
        })
    except Exception as e:
        print(f"!!! ERROR at /api/contests/{id}: {e}")
        return jsonify({"error": "Contest not found"}), 404

@app.route('/api/contests/<int:id>/posts')
def get_posts_for_contest(id):
    try:
        Contest.query.get_or_404(id)
        posts = Post.query.filter_by(contest_id=id).order_by(Post.created_at.desc()).all()
        
        user_id = session.get('user_id')
        user_votes = {}
        # --- ▼▼▼ 既に投票済みかチェックするフラグを追加 ▼▼▼ ---
        user_has_voted = False 
        # --- ▲▲▲ ここまで ▲▲▲ ---
        user_votes_map = {} 

        if user_id:
            votes = Vote.query.filter_by(user_id=user_id, contest_id=id).all()
            user_votes = {vote.post_id: vote.count for vote in votes}
            # --- ▼▼▼ 投票記録があればフラグをTrueに ▼▼▼ ---
            if votes: # 1件でも投票記録があれば投票済みとみなす
                user_has_voted = True
            for v in votes:
                user_votes_map[v.post_id] = {
                    'count': v.count,
                    'is_judge_award': v.is_judge_award,
                    'judge_comment': v.judge_comment
                }
            # --- ▲▲▲ ここまで ▲▲▲ ---

        total_posters = db.session.query(func.count(distinct(Post.user_id))).filter(Post.contest_id == id).scalar() or 0

        posts_data = []
        for post in posts:
            my_vote = user_votes_map.get(post.id, {})
            posts_data.append({
                'id': post.id,
                'content': post.content,
                'created_at': post.created_at.replace(tzinfo=timezone.utc).astimezone(JST).isoformat(),
                'user_id': post.user_id,
                'myVotes': user_votes.get(post.id, 0) ,
                'images': post.images, # 画像URLリストを追加
                'myJudgeAward': my_vote.get('is_judge_award', False),   # 追加
                'myJudgeComment': my_vote.get('judge_comment', None)
            })
        
        # --- ▼▼▼ レスポンスにフラグを追加 ▼▼▼ ---
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
        
        if Post.query.filter_by(user_id=user_id, contest_id=id).first():
             return jsonify({"error": "Already posted"}), 409

        # 画像アップロード処理
        image_urls = []
        for file in files:
            if file and allowed_file(file.filename):
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
    if 'user_id' not in session: return jsonify({"error": "Login required"}), 401
    
    user_id = session['user_id']
    data = request.get_json()
    votes_to_submit = data.get('votes') # { "postId": count }
    judge_award = data.get('judgeAward') # { "postId": 123, "comment": "..." } or null

    if not isinstance(votes_to_submit, dict):
         return jsonify({"error": "Invalid vote data"}), 400

    try:
        is_judge = id in session.get('judge_for_contest_ids', [])
        judge_contest_ids = session.get('judge_for_contest_ids', [])
        is_judge_voting_now = id in judge_contest_ids
        
        Vote.query.filter_by(user_id=user_id, contest_id=id).delete()

        # 期間チェック
        c = Contest.query.get_or_404(id)
        now = datetime.now(timezone.utc)
        if not (c.end_time.replace(tzinfo=timezone.utc) <= now < c.voting_end_time.replace(tzinfo=timezone.utc)):
             return jsonify({"error": "Outside period"}), 403
        
        max_score = c.judge_max_score if is_judge else 1

        # --- 投票データの保存 ---
        # 1. 点数投票の保存
        processed_post_ids = set()
        for pid_str, count_val in votes_to_submit.items():
            try:
                post_id = int(pid_str)
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

        db.session.commit()
        return jsonify({"message": "Voted"}), 200
    except Exception as e:
        db.session.rollback()
        print(f"Error: {e}")
        return jsonify({"error": "Error"}), 500
    
@app.route('/api/contests/<int:id>/results')
def get_contest_results(id):
    try:
        user_id = session.get('user_id'); c = Contest.query.get_or_404(id); now = datetime.now(timezone.utc)
        if now < c.voting_end_time.replace(tzinfo=timezone.utc): return jsonify({"error": "Voting ongoing"}), 403
        
        all_posts = Post.query.options(joinedload(Post.user)).filter(Post.contest_id == id).all()
        if not all_posts: return jsonify({'contest': {'id': c.id, 'name': c.name, 'theme': c.theme}, 'results': [], 'judgeAwards': [], 'totalPosters': 0, 'totalVoters': 0})
        
        contest_results = calculate_contest_results(id) or {}
        
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
                'isBookmarked': post.id in user_bookmarks,
                'awards': award_badges.get(post.id, []) # バッジ情報を追加
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

            # 2. 一括データ取得
            # (a) 投票データ (投票者リスト構築用)
            votes_data = db.session.query(Vote, User).join(User, Vote.user_id == User.id).filter(Vote.post_id.in_(target_post_ids)).all()
            voters_map = {} # post_id -> [voter_dict, ...]
            my_votes_map = {} # post_id -> count (閲覧者が投票した数)

            for vote, v_user in votes_data:
                if vote.post_id not in voters_map: voters_map[vote.post_id] = []
                # 審査員の場合は点数も表示したいのでcountを含める
                voters_map[vote.post_id].append({
                    'screen_name': v_user.screen_name,
                    'name': v_user.name,
                    'count': vote.count,
                    'is_judge': vote.is_judge_vote
                })
                # 閲覧者の投票状況を確認
                if viewer_id and vote.user_id == viewer_id:
                    my_votes_map[vote.post_id] = vote.count

            # (b) 審査員賞データ (バッジ用)
            awards_data = db.session.query(Vote, User).join(User, Vote.user_id == User.id).filter(Vote.post_id.in_(target_post_ids), Vote.is_judge_award == True).all()
            awards_map = {} # post_id -> ["xxx賞", ...]
            for vote, j_user in awards_data:
                if vote.post_id not in awards_map: awards_map[vote.post_id] = []
                awards_map[vote.post_id].append(f"{j_user.name}賞")

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
                    results_cache[cid] = calculate_contest_results(cid) or {}
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
                        'theme': post.contest.theme
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

    # テキストも画像もなければエラー（ただし画像全削除＆テキストありはOK）
    if not new_content and not kept_images and not files: return jsonify({"error": "No content"}), 400
    
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
    
@app.route('/api/admin/contests/management')
def get_management_contests():
    # 本番環境では管理者チェックが必要
    # if not session.get('is_admin'): return jsonify({"error": "Unauthorized"}), 403
    
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
                # 必要に応じて予選時刻なども追加
            })
        return jsonify(contests_data)
    except Exception as e:
        print(f"!!! ERROR at GET /api/admin/contests/management: {e}")
        traceback.print_exc()
        return jsonify({"error": "Failed to fetch contests for management"}), 500
# --- ▲▲▲ ここまで ▲▲▲ ---

# --- ▼▼▼ 大会削除APIを新設 ▼▼▼ ---
@app.route('/api/admin/contests/<int:id>', methods=['DELETE'])
def delete_contest(id):
    # 本番環境では管理者チェックが必要
    # if not session.get('is_admin'): return jsonify({"error": "Unauthorized"}), 403

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

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        print("Database tables created (if not existed).")
    
    # 環境変数PORTを取得（Cloud Runでは必須）、なければローカル用の5001を使う
    port = int(os.environ.get('PORT', 5001))
    
    # host='0.0.0.0' を指定してコンテナ外からのアクセスを許可する
    # 本番環境では debug=False にする
    app.run(host='0.0.0.0', port=port, debug=False)
