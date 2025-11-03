import os
import traceback
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

load_dotenv()
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

app = Flask(__name__)

# --- アプリケーション設定 ---
app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', 'a-very-secret-key-that-is-secure'),
    SQLALCHEMY_DATABASE_URI=os.environ.get('SQLALCHEMY_DATABASE_URI', 'sqlite:///project.db'),
    SESSION_COOKIE_SAMESITE='Lax',
    # クッキーが localhost ドメイン用であることを明示
    SESSION_COOKIE_DOMAIN='localhost',
    SESSION_COOKIE_SECURE=False
)

JST = timezone(timedelta(hours=9), 'JST')

CORS(app, supports_credentials=True, origins=["http://localhost:3000"])
db.init_app(app)
migrate = Migrate(app, db)

# --- X OAuth Login ---
X_CONSUMER_KEY = os.environ.get("X_CONSUMER_KEY")
X_CONSUMER_SECRET = os.environ.get("X_CONSUMER_SECRET")
REQUEST_TOKEN_URL = "https://api.twitter.com/oauth/request_token"
AUTHORIZE_URL = "https://api.twitter.com/oauth/authorize"
ACCESS_TOKEN_URL = "https://api.twitter.com/oauth/access_token"
USER_INFO_URL = "https://api.twitter.com/1.1/account/verify_credentials.json"

@app.route("/api/login/twitter")
def twitter_login():
    try:
        # プロキシ経由で正しいURLをXに伝える
        callback_url = url_for('twitter_callback', _external=False)
        full_callback_url = f"http://localhost:3000{callback_url}"

        twitter = OAuth1Session(X_CONSUMER_KEY, client_secret=X_CONSUMER_SECRET, callback_uri=full_callback_url)
        response = twitter.fetch_request_token(REQUEST_TOKEN_URL)
        session['oauth_token'] = response.get("oauth_token")
        session['oauth_token_secret'] = response.get("oauth_token_secret")
        authorization_url = twitter.authorization_url(AUTHORIZE_URL)
        return jsonify({'authorization_url': authorization_url})
    except Exception as e:
        print(f"!!! ERROR at /api/login/twitter: {e}")
        return jsonify({"error": "Failed to connect to Twitter"}), 500

@app.route('/api/callback/twitter')
def twitter_callback():
    oauth_token = session.pop('oauth_token', None)
    oauth_token_secret = session.pop('oauth_token_secret', None)
    verifier = request.args.get('oauth_verifier')

    if not all([oauth_token, oauth_token_secret, verifier]):
        return redirect("http://localhost:3000?login_error=session_token_missing")

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
                profile_image_url=user_data.get('profile_image_url_https', '').replace('_normal', '')
            )
            db.session.add(user)
        else:
            user.screen_name = user_data.get('screen_name')
            user.profile_image_url = user_data.get('profile_image_url_https', '').replace('_normal', '')
        
        db.session.commit()
        
        session['user_id'] = user.id
        session['screen_name'] = user.screen_name
        session['profile_image_url'] = user.profile_image_url
    except Exception as e:
        print(f"!!! ERROR at /api/callback/twitter: {e}")
        traceback.print_exc()
        db.session.rollback()
        return redirect("http://localhost:3000?login_error=callback_failed")
    
    return redirect("http://localhost:3000")

# (以降のコードは変更ありません)
# ...

def calculate_contest_results(contest_id):
    """指定された大会IDの結果を集計して返すヘルパー関数"""
    contest = Contest.query.get(contest_id)
    if not contest:
        return None # 大会が存在しない

    # is_judge_vote が True の場合は ratio を掛け、そうでなければそのまま count を使う
    score_calculation = case(
        (Vote.is_judge_vote == True, Vote.count * contest.judge_vote_ratio),
        else_=Vote.count
    )

    results_query = db.session.query(
        Vote.post_id,
        func.sum(score_calculation).label('total_score')
    ).filter(
        Vote.contest_id == contest_id
    ).group_by(
        Vote.post_id
    ).subquery()

    ranked_posts_query = db.session.query(
        Post,
        results_query.c.total_score
    ).join(
        results_query, Post.id == results_query.c.post_id
    ).filter(
        Post.contest_id == contest_id
    ).order_by(
        results_query.c.total_score.desc(),
        Post.created_at.asc()
    )

    ranked_results = []
    # ランキングとスコアを計算
    current_rank = 0
    last_score = -1
    rank_counter = 0
    for post, total_score in ranked_posts_query.all():
        rank_counter += 1
        # 同点の場合は同じ順位にする
        if total_score != last_score:
            current_rank = rank_counter
            last_score = total_score
        
        ranked_results.append({
            'post_id': post.id,
            'rank': current_rank,
            'score': total_score if total_score is not None else 0 # スコアがない場合は0
        })

    # post_id をキーにした辞書に変換して返す
    return {result['post_id']: result for result in ranked_results}

@app.route('/api/me')
def get_current_user():
    user_data = { 'logged_in': False }
    if 'user_id' in session:
        user_data['logged_in'] = True
        user_data['user'] = {
            'id': session['user_id'],
            'screen_name': session['screen_name'],
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
            judge_vote_ratio=int(data['judgeVoteRatio']),
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

        ongoing_contests_data = []
        voting_contests_data = []
        upcoming_contests_data = []
        closed_contests_list = []
        closed_contests_data = []
        latest_result_data = None

        for contest in contests:
            # --- ▼▼▼ 時刻の aware 化を最初に行う ▼▼▼ ---
            start_time_aware = contest.start_time.replace(tzinfo=timezone.utc) if contest.start_time else None
            end_time_aware = contest.end_time.replace(tzinfo=timezone.utc) if contest.end_time else None
            voting_end_time_aware = contest.voting_end_time.replace(tzinfo=timezone.utc) if contest.voting_end_time else None
            qualifier_start_time_aware = contest.qualifier_start_time.replace(tzinfo=timezone.utc) if contest.qualifier_start_time else None
            qualifier_end_time_aware = contest.qualifier_end_time.replace(tzinfo=timezone.utc) if contest.qualifier_end_time else None
            qualifier_voting_end_time_aware = contest.qualifier_voting_end_time.replace(tzinfo=timezone.utc) if contest.qualifier_voting_end_time else None
            # --- ▲▲▲ ここまで ▲▲▲ ---

            contest_data_for_frontend = {
                'id': contest.id, 'name': contest.name,
                # --- ▼▼▼ has_theme と theme を追加 ▼▼▼ ---
                'hasTheme': contest.has_theme,
                'theme': contest.theme if contest.has_theme else None,
                # --- ▲▲▲ ここまで ▲▲▲ ---
                # --- ▼▼▼ has_qualifier と予選時刻を追加 ▼▼▼ ---
                'hasQualifier': contest.has_qualifier,
                'startTime': start_time_aware.astimezone(JST).isoformat() if start_time_aware else None,
                'endTime': end_time_aware.astimezone(JST).isoformat() if end_time_aware else None,
                'votingEndTime': voting_end_time_aware.astimezone(JST).isoformat() if voting_end_time_aware else None,
                'qualifierStartTime': qualifier_start_time_aware.astimezone(JST).isoformat() if qualifier_start_time_aware else None,
                'qualifierEndTime': qualifier_end_time_aware.astimezone(JST).isoformat() if qualifier_end_time_aware else None,
                'qualifierVotingEndTime': qualifier_voting_end_time_aware.astimezone(JST).isoformat() if qualifier_voting_end_time_aware else None,
                # --- ▲▲▲ ここまで ▲▲▲ ---
                'judgeVoteRatio': contest.judge_vote_ratio
            }

            # 分類ロジック (予選がある場合も考慮が必要だが、今回は簡略化のため通常時間で分類)
            # 本格実装では、予選時間も見てステータスを細分化する必要がある
            if start_time_aware and end_time_aware and start_time_aware <= now < end_time_aware:
                ongoing_contests_data.append(contest_data_for_frontend)
            elif end_time_aware and voting_end_time_aware and end_time_aware <= now < voting_end_time_aware:
                voting_contests_data.append(contest_data_for_frontend)
            elif start_time_aware and now < start_time_aware:
                upcoming_contests_data.append(contest_data_for_frontend)
            elif voting_end_time_aware and now >= voting_end_time_aware : # 終了済み
                closed_contests_list.append(contest)
                closed_contests_data.append(contest_data_for_frontend)

        # 最新の結果を取得するロジック
        if closed_contests_list:
            latest_closed_contest = closed_contests_list[0]
            # --- ▼▼▼ 最新結果の構造をシンプル化 ▼▼▼ ---
            latest_result_data = {
                'contest_id': latest_closed_contest.id,
                'contest_name': latest_closed_contest.name,
                'theme': latest_closed_contest.theme if latest_closed_contest.has_theme else None,
            }
            # --- ▲▲▲ ここまで ▲▲▲ ---

        upcoming_contests_data.reverse()

        return jsonify({
            'ongoing': ongoing_contests_data,
            'voting': voting_contests_data,
            'upcoming': upcoming_contests_data,
            'closed': closed_contests_data,
            'latestResult': latest_result_data
        })
    except Exception as e:
        print(f"!!! ERROR at /api/contests: {e}")
        traceback.print_exc()
        return jsonify({"error": "Failed to fetch contests"}), 500

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
            'judgeVoteRatio': contest.judge_vote_ratio,
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

        if user_id:
            votes = Vote.query.filter_by(user_id=user_id, contest_id=id).all()
            user_votes = {vote.post_id: vote.count for vote in votes}
            # --- ▼▼▼ 投票記録があればフラグをTrueに ▼▼▼ ---
            if votes: # 1件でも投票記録があれば投票済みとみなす
                user_has_voted = True
            # --- ▲▲▲ ここまで ▲▲▲ ---


        posts_data = []
        for post in posts:
            posts_data.append({
                'id': post.id,
                'content': post.content,
                'created_at': post.created_at.replace(tzinfo=timezone.utc).astimezone(JST).isoformat(),
                'user_id': post.user_id,
                'myVotes': user_votes.get(post.id, 0) 
            })
        
        # --- ▼▼▼ レスポンスにフラグを追加 ▼▼▼ ---
        return jsonify({
            'posts': posts_data,
            'userHasVotedInContest': user_has_voted 
        })
        # --- ▲▲▲ ここまで ▲▲▲ ---
    except Exception as e:
        print(f"!!! ERROR at GET /api/contests/{id}/posts: {e}")
        return jsonify({"error": "Failed to fetch posts"}), 500



@app.route('/api/contests/<int:id>/posts', methods=['POST'])
def submit_post(id):
    if 'user_id' not in session:
        return jsonify({"error": "ログインが必要です。"}), 401

    user_id = session['user_id']
    data = request.get_json()
    content = data.get('content')

    if not content:
        return jsonify({"error": "投稿内容がありません。"}), 400

    try:
        existing_post = Post.query.filter_by(user_id=user_id, contest_id=id).first()
        if existing_post:
            return jsonify({"error": "この大会には既に投稿済みです。"}), 409

        new_post = Post(content=content, contest_id=id, user_id=user_id)
        db.session.add(new_post)
        db.session.commit()

        return jsonify({
            'id': new_post.id,
            'content': new_post.content,
            # DB保存後にtzinfoが失われるため、再度UTCを指定してからJSTに変換する
            'created_at': new_post.created_at.replace(tzinfo=timezone.utc).astimezone(JST).isoformat(),
            'user_id': new_post.user_id
        }), 201

    except Exception as e:
        db.session.rollback()
        print(f"!!! ERROR at POST /api/contests/{id}/posts: {e}")
        traceback.print_exc()
        return jsonify({"error": "投稿処理中にエラーが発生しました。"}), 500

@app.route('/api/contests/<int:id>/vote', methods=['POST'])
def submit_votes(id):
    if 'user_id' not in session:
        return jsonify({"error": "ログインが必要です。"}), 401
    
    user_id = session['user_id']
    votes_data = request.get_json() 

    if not isinstance(votes_data, dict) or 'votes' not in votes_data or not isinstance(votes_data['votes'], dict):
         return jsonify({"error": "無効なリクエスト形式です。"}), 400
         
    votes_to_submit = votes_data['votes']

    try:
        # --- ▼▼▼ 審査員モードか判定 ▼▼▼ ---
        judge_contest_ids = session.get('judge_for_contest_ids', [])
        is_judge_voting_now = id in judge_contest_ids
        print(f"--- Vote Submission: User {user_id} for Contest {id}. Is Judge? {is_judge_voting_now} ---") # ログ追加
        # --- ▲▲▲ ここまで ▲▲▲ ---

        # 既に投票済みかチェック (審査員票は一般票とは別に扱わない - 一度投票したら終わり)
        existing_vote = Vote.query.filter_by(user_id=user_id, contest_id=id).first()
        if existing_vote:
            # ここで「審査員としてなら再投票可能」とするかは要件次第ですが、今回は不可とします
            return jsonify({"error": "この大会には既に投票済みです（一般票または審査員票）。"}), 409

        contest = Contest.query.get_or_404(id)
        now = datetime.now(timezone.utc) 

        contest_end_time_aware = contest.end_time.replace(tzinfo=timezone.utc)
        voting_end_time_aware = contest.voting_end_time.replace(tzinfo=timezone.utc)

        if not (contest_end_time_aware <= now < voting_end_time_aware):
             return jsonify({"error": "現在は投票期間外です。"}), 403

        total_votes = sum(votes_to_submit.values())
        
        # 審査員は10票制限を無視するか？ -> 今回は無視しない（一般票と同じルール）
        if total_votes < 10 and not is_judge_voting_now: # 一般票の場合のみチェック
            return jsonify({"error": f"合計10票以上の投票が必要です。現在の合計: {total_votes}票"}), 400

        # 投票データをDBに保存
        for post_id_str, count in votes_to_submit.items():
            try:
                post_id = int(post_id_str)
                if not (0 <= count <= 3):
                    raise ValueError("投票数は0から3の間でなければなりません。")
                
                post = Post.query.filter_by(id=post_id, contest_id=id).first()
                if not post:
                    raise ValueError(f"投稿ID {post_id} が無効です。")

                if count > 0: 
                    vote = Vote(
                        user_id=user_id, 
                        post_id=post_id, 
                        contest_id=id, 
                        count=count,
                        # --- ▼▼▼ is_judge_vote を設定 ▼▼▼ ---
                        is_judge_vote=is_judge_voting_now 
                        # --- ▲▲▲ ここまで ▲▲▲ ---
                    )
                    db.session.add(vote)

            except (ValueError, TypeError) as ve:
                 db.session.rollback()
                 return jsonify({"error": f"投票データの処理中にエラーが発生しました: {ve}"}), 400

        db.session.commit()
        return jsonify({"message": "投票を受け付けました。"}), 200

    except Exception as e:
        db.session.rollback()
        print(f"!!! ERROR at POST /api/contests/{id}/vote: {e}")
        traceback.print_exc()
        return jsonify({"error": "投票処理中に予期せぬエラーが発生しました。"}), 500
    
@app.route('/api/contests/<int:id>/results')
def get_contest_results(id):
    try:
        user_id = session.get('user_id') # ログインユーザーID
        contest = Contest.query.get_or_404(id)
        now = datetime.now(timezone.utc)
        voting_end_time_aware = contest.voting_end_time.replace(tzinfo=timezone.utc)

        if now < voting_end_time_aware:
             return jsonify({"error": "まだ投票期間中です。"}), 403

        # 1. 全ての投稿を取得 (ユーザー情報も結合)
        all_posts_query = Post.query.options(joinedload(Post.user)).filter(Post.contest_id == id).all()
        if not all_posts_query:
             return jsonify({ 'contest': { 'id': contest.id, 'name': contest.name, 'theme': contest.theme }, 'results': [], 'totalPosters': 0, 'totalVoters': 0 })

        # 2. 全ての投票情報を取得 (投票者情報も結合)
        all_votes_query = db.session.query(Vote, User).join(User, Vote.user_id == User.id).filter(Vote.contest_id == id).all()
        voters_by_post = {}
        for vote, user in all_votes_query:
            if vote.post_id not in voters_by_post: voters_by_post[vote.post_id] = []
            voters_by_post[vote.post_id].append({ 'screen_name': user.screen_name, 'count': vote.count, 'is_judge': vote.is_judge_vote })

        # 3. 各投稿のスコアと順位を計算 (0票も含む)
        contest_results = calculate_contest_results(id) or {}

        # 4. ブックマーク情報を取得
        post_ids = [p.id for p in all_posts_query]
        bookmark_counts_query = db.session.query(Bookmark.post_id, func.count(Bookmark.id).label('bookmark_count')).filter(Bookmark.post_id.in_(post_ids)).group_by(Bookmark.post_id).all()
        bookmark_counts = {post_id: count for post_id, count in bookmark_counts_query}
        user_bookmarks = set()
        if user_id:
            user_bookmarks_query = db.session.query(Bookmark.post_id).filter(Bookmark.user_id == user_id, Bookmark.post_id.in_(post_ids)).all()
            user_bookmarks = {post_id for (post_id,) in user_bookmarks_query}

        # 5. 全投稿リストに情報を結合
        results_list = []
        for post in all_posts_query:
            post_result = contest_results.get(post.id, {'rank': None, 'score': 0}) # 結果がない(0票)場合
            post_voters = voters_by_post.get(post.id, [])
            post_voters.sort(key=lambda v: v['is_judge'], reverse=True)
            results_list.append({
                'rank': post_result['rank'],
                'post_id': post.id,
                'content': post.content,
                'created_at': post.created_at.replace(tzinfo=timezone.utc).astimezone(JST).isoformat(),
                'score': post_result['score'],
                'user': { 'screen_name': post.user.screen_name, 'profile_image_url': post.user.profile_image_url },
                'voters': post_voters,
                'bookmarkCount': bookmark_counts.get(post.id, 0),
                'isBookmarked': post.id in user_bookmarks
            })
        
        # 6. 最終ソート (順位がNoneでないものを優先し、次にスコア順)
        results_list.sort(key=lambda x: (x['rank'] is None, -x['score'], datetime.fromisoformat(x['created_at']).timestamp()))
        # 順位を再割り当て
        ranked_results_data = []
        current_rank = 0
        last_score = -1
        rank_counter = 0
        for result in results_list:
            rank_counter += 1
            if result['score'] != last_score:
                current_rank = rank_counter
                last_score = result['score']
            result['rank'] = current_rank if result['score'] > 0 else None # 0票はランクなし
            ranked_results_data.append(result)

        # 7. 統計情報
        total_posters = db.session.query(func.count(distinct(Post.user_id))).filter(Post.contest_id == id).scalar()
        total_voters = db.session.query(func.count(distinct(Vote.user_id))).filter(Vote.contest_id == id).scalar()

        return jsonify({
            'contest': { 'id': contest.id, 'name': contest.name, 'theme': contest.theme },
            'results': ranked_results_data,
            'totalPosters': total_posters if total_posters is not None else 0,
            'totalVoters': total_voters if total_voters is not None else 0
        })

    except Exception as e:
        print(f"!!! ERROR at GET /api/contests/{id}/results: {e}")
        traceback.print_exc()
        return jsonify({"error": "結果の取得に失敗しました。"}), 500
    
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
def get_user_profile(screen_name):
    try:
        # --- ▼▼▼ 修正点 ▼▼▼ ---
        # first_or_404() から first() に変更
        target_user = User.query.filter_by(screen_name=screen_name).first()
        
        # ユーザーが見つからなかった場合、404 JSONを返す
        if not target_user:
            return jsonify({"error": "ユーザーが見つかりません。"}), 404
        # --- ▲▲▲ ここまで ▲▲▲ ---
        
        user_id = target_user.id

        # (以降のロジックは変更なし)
        user_posts_query = Post.query.filter_by(user_id=user_id).options(joinedload(Post.contest), joinedload(Post.user)).order_by(Post.created_at.desc()).all()
        profile_posts_data = []
        results_cache = {}
        now = datetime.now(timezone.utc)
        
        for post in user_posts_query:
            contest = post.contest
            contest_id = contest.id
            rank = None
            score = None
            voting_end_time_aware = contest.voting_end_time.replace(tzinfo=timezone.utc)
            if now >= voting_end_time_aware:
                if contest_id not in results_cache: results_cache[contest_id] = calculate_contest_results(contest_id) or {}
                post_result = results_cache[contest_id].get(post.id)
                if post_result: rank, score = post_result['rank'], post_result['score']
            profile_posts_data.append({
                'post_id': post.id, 'content': post.content,
                'created_at': post.created_at.replace(tzinfo=timezone.utc).astimezone(JST).isoformat(),
                'contest': { 'id': contest.id, 'name': contest.name, 'theme': contest.theme },
                'user': { 'screen_name': post.user.screen_name, 'profile_image_url': post.user.profile_image_url },
                'rank': rank, 'score': score
            })

        bookmarked_posts_query = db.session.query(Post).join(Bookmark, Post.id == Bookmark.post_id).filter(Bookmark.user_id == user_id).options(joinedload(Post.user), joinedload(Post.contest)).order_by(Bookmark.created_at.desc()).all()
        bookmarks_data = []
        for post in bookmarked_posts_query:
            contest = post.contest
            contest_id = contest.id
            rank = None
            score = None
            voting_end_time_aware = contest.voting_end_time.replace(tzinfo=timezone.utc)
            if now >= voting_end_time_aware:
                if contest_id not in results_cache: results_cache[contest_id] = calculate_contest_results(contest_id) or {}
                post_result = results_cache[contest_id].get(post.id)
                if post_result: rank, score = post_result['rank'], post_result['score']
            bookmarks_data.append({
                'post_id': post.id, 'content': post.content,
                'created_at': post.created_at.replace(tzinfo=timezone.utc).astimezone(JST).isoformat(),
                'contest': { 'id': contest.id, 'name': contest.name, 'theme': contest.theme },
                'user': { 'screen_name': post.user.screen_name, 'profile_image_url': post.user.profile_image_url },
                'rank': rank, 'score': score
            })

        return jsonify({
            'user': { 'id': target_user.id, 'screen_name': target_user.screen_name, 'profile_image_url': target_user.profile_image_url },
            'posts': profile_posts_data,
            'bookmarks': bookmarks_data
        })

    except Exception as e:
        print(f"!!! ERROR at GET /api/profile/{screen_name}: {e}")
        traceback.print_exc()
        return jsonify({"error": "プロフィール情報の取得に失敗しました。"}), 500
    


@app.route('/api/contests/<int:contest_id>/posts/<int:post_id>', methods=['PUT'])
def update_post(contest_id, post_id):
    if 'user_id' not in session:
        return jsonify({"error": "ログインが必要です。"}), 401

    user_id = session['user_id']
    data = request.get_json()
    new_content = data.get('content')

    if not new_content:
        return jsonify({"error": "投稿内容がありません。"}), 400

    try:
        # 編集対象の投稿を検索 (ユーザーIDとコンテストIDも一致するか確認)
        post_to_edit = Post.query.filter_by(id=post_id, user_id=user_id, contest_id=contest_id).first()

        if not post_to_edit:
            return jsonify({"error": "編集対象の投稿が見つからないか、編集権限がありません。"}), 404

        # 大会が投稿受付中か確認 (任意だが推奨)
        contest = Contest.query.get(contest_id)
        now = datetime.now(timezone.utc)
        start_time_aware = contest.start_time.replace(tzinfo=timezone.utc)
        end_time_aware = contest.end_time.replace(tzinfo=timezone.utc)
        if not (start_time_aware <= now < end_time_aware):
            return jsonify({"error": "現在は投稿受付期間外のため編集できません。"}), 403

        # 内容を更新して保存
        post_to_edit.content = new_content
        post_to_edit.updated_at = datetime.now(timezone.utc) # 更新日時を記録 (モデルにupdated_atが必要)
        db.session.commit()

        # 更新後の投稿データを返す
        return jsonify({
            'id': post_to_edit.id,
            'content': post_to_edit.content,
            'created_at': post_to_edit.created_at.replace(tzinfo=timezone.utc).astimezone(JST).isoformat(),
            'user_id': post_to_edit.user_id,
            'myVotes': 0 # 編集時にはmyVotesは不要だが、型合わせのため0を返す
        }), 200

    except Exception as e:
        db.session.rollback()
        print(f"!!! ERROR at PUT /api/contests/{contest_id}/posts/{post_id}: {e}")
        traceback.print_exc()
        return jsonify({"error": "投稿の編集中にエラーが発生しました。"}), 500
    
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
    app.run(port=5001, debug=True)

