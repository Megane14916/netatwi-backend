"""X OAuth and judge authentication routes."""

import base64
import hashlib
import logging
import os
import secrets
import traceback

from flask import current_app, jsonify, redirect, request, session
from requests.auth import HTTPBasicAuth
from requests_oauthlib import OAuth2Session

from app_extensions import limiter
from models import Contest, User, db
from .legacy import LegacyEndpointBlueprint


bp = LegacyEndpointBlueprint("auth", __name__)
logger = logging.getLogger("app")

# --- X OAuth 2.0 設定 (古い1.0aの設定2箇所は削除してこれに差し替え) ---
X_CLIENT_ID = os.environ.get(
    "X_CONSUMER_KEY"
)  # "X_CLIENT_ID" としても良いが、既存の環境変数を流用
X_CLIENT_SECRET = os.environ.get(
    "X_CONSUMER_SECRET"
)  # "X_CLIENT_SECRET" としても良いが、既存の環境変数を流用
AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
TOKEN_URL = "https://api.x.com/2/oauth2/token"
USER_INFO_URL = "https://api.x.com/2/users/me"
X_SCOPES = ["tweet.read", "users.read"]


@bp.route("/api/login/twitter")
def twitter_login():
    try:
        # コールバックURLを生成（ローカル環境ではHTTPを使用）
        callback_url = f"{current_app.config['FRONTEND_URL']}/api/callback/twitter"
        logger.info(f"Generated Callback URL: {callback_url}")

        # OAuth 2.0 (PKCE) に必要な安全なランダム文字列を生成
        code_verifier = secrets.token_urlsafe(48)
        hashed = hashlib.sha256(code_verifier.encode("utf-8")).digest()

        # パディング（=）を除去し、確実にURLセーフなBase64にする
        code_challenge = base64.urlsafe_b64encode(hashed).decode("utf-8").rstrip("=")

        # OAuth2Session の構築
        twitter = OAuth2Session(X_CLIENT_ID, redirect_uri=callback_url, scope=X_SCOPES)
        authorization_url, state = twitter.authorization_url(
            AUTHORIZE_URL,
            code_challenge=code_challenge,
            code_challenge_method="s256",  # 👈 ★大文字 "S256" から 小文字 "s256" に修正
        )

        # 👈 ★Xの厳格な仕様対策：スコープの区切り文字「+」を「%20」に強制置換
        authorization_url = authorization_url.replace("+", "%20")

        # セッションに検証用の値を保存
        # 審査員認証情報を引き継いでからセッションをクリアする
        judge_ids = session.get("judge_for_contest_ids", [])
        session.clear()
        session["oauth_state"] = state
        session["code_verifier"] = code_verifier
        if judge_ids:
            session["judge_for_contest_ids"] = judge_ids
        session.modified = True

        logger.info(f"Saved to session - State: {state}")

        return jsonify({"authorization_url": authorization_url})
    except Exception as e:
        logger.error(f"!!! ERROR at /api/login/twitter: {e}")
        traceback.print_exc()
        return jsonify({"error": "Failed to connect to Twitter"}), 500


@bp.route("/api/callback/twitter")
def twitter_callback():
    logger.info(f"=== CALLBACK START ===")
    logger.info(f"Session keys present: {list(session.keys())}")

    # セッションから検証用データを取得・削除
    session_state = session.pop("oauth_state", None)
    code_verifier = session.pop("code_verifier", None)

    # Xから返ってきた認可コードと state を取得
    url_state = request.args.get("state")
    code = request.args.get("code")
    error = request.args.get("error")

    if error:
        logger.error(f"X Login Error from URL: {error}")
        return redirect(f"{current_app.config['FRONTEND_URL']}?login_error={error}")

    if not all([session_state, code_verifier, code]):
        logger.error("Missing state, code_verifier, or code in callback.")
        reason = "session_token_missing" if not session_state else "verifier_missing"
        return redirect(f"{current_app.config['FRONTEND_URL']}?login_error={reason}")

    # state の一致検証（CSRF対策）
    if url_state != session_state:
        logger.error(f"State mismatch: url={url_state}, session={session_state}")
        return redirect(f"{current_app.config['FRONTEND_URL']}?login_error=state_mismatch")

    try:
        callback_url = f"{current_app.config['FRONTEND_URL']}/api/callback/twitter"

        # 1. アクセストークンの取得
        twitter = OAuth2Session(
            X_CLIENT_ID, redirect_uri=callback_url, state=session_state
        )
        auth = HTTPBasicAuth(X_CLIENT_ID, X_CLIENT_SECRET)

        # token の中身を明示的に取得する
        token_response = twitter.fetch_token(
            token_url=TOKEN_URL,
            client_secret=X_CLIENT_SECRET,
            code=code,
            auth=auth,
            code_verifier=code_verifier,
        )

        # 返ってきたデータからアクセストークンを直接取り出す
        access_token = token_response.get("access_token")
        if not access_token:
            raise ValueError("Token response did not contain access_token")

        logger.info(
            f"Access Token successfully fetched (starts with: {access_token[:10]}...)"
        )

        # 2. ユーザー情報の取得 (★ライブラリのバグを回避するため、通常の requests で直接ヘッダーを指定)
        import requests

        headers = {
            "Authorization": f"Bearer {access_token}"  # 👈 ここで確実にトークンを付与
        }

        # 無料プランでも安全に動くよう、まずはフィールド指定なしでリクエスト
        response = requests.get(
            f"{USER_INFO_URL}?user.fields=profile_image_url", headers=headers
        )

        # もしエラーなら、Xから返ってきたエラー内容の詳細をログに出す
        if response.status_code != 200:
            logger.error(f"X API Error Response Body: {response.text}")

        response.raise_for_status()
        res_json = response.json()

        # API v2 のデータ構造からユーザー情報を抽出
        user_data = res_json.get("data", {})

        twitter_id = user_data.get("id")
        screen_name = user_data.get("username")
        name = user_data.get("name")

        # 画像URLは、この基本リクエストが成功した後に次のステップで取得するため、一旦空文字にします
        profile_image_url = user_data.get("profile_image_url", "").replace(
            "_normal", ""
        )

        if not twitter_id:
            raise ValueError("Failed to retrieve user ID from X API v2 json")

        # 3. データベースの更新・保存処理 (ここから下は元のコードのままで大丈夫です)
        user = User.query.filter_by(twitter_id=twitter_id).first()
        if not user:
            user = User(
                twitter_id=twitter_id,
                screen_name=screen_name,
                name=name,
                profile_image_url=profile_image_url,
            )
            db.session.add(user)
        else:
            if user.deleted_at:
                return redirect(f"{current_app.config['FRONTEND_URL']}?login_error=account_deleted")
            user.screen_name = screen_name
            user.name = name
            user.profile_image_url = profile_image_url

        db.session.commit()

        # アプリケーションセッションにユーザー情報をセット
        session.permanent = True
        session["user_id"] = user.id
        session["screen_name"] = user.screen_name
        session["name"] = user.name
        session["profile_image_url"] = user.profile_image_url

        logger.info(f"Login successful for user: {user.screen_name}")

    except Exception as e:
        logger.error(f"!!! ERROR at /api/callback/twitter: {e}")
        traceback.print_exc()
        db.session.rollback()
        return redirect(f"{current_app.config['FRONTEND_URL']}?login_error=callback_failed")

    return redirect(current_app.config["FRONTEND_URL"])


@bp.route("/api/contests/<int:id>/judge/login", methods=["POST"])
@limiter.limit("5 per minute")
def judge_login(id):
    if "user_id" not in session:
        return jsonify({"error": "ログインが必要です。"}), 401

    data = request.get_json()
    password = data.get("password")

    if not password:
        return jsonify({"error": "パスワードを入力してください。"}), 400

    try:
        contest = Contest.query.get_or_404(id)

        if contest.scoring_method == "user":
            return jsonify(
                {"error": "この大会は一般投票のみのため、審査員として参加できません。"}
            ), 400

        if contest.judge_password and contest.judge_password == password:
            # --- ▼▼▼ set ではなく list を使うように修正 ▼▼▼ ---
            # セッションからリストを取得 (なければ空のリストを作成)
            judge_contest_ids = session.get("judge_for_contest_ids", [])
            # リストに大会IDがなければ追加する
            if id not in judge_contest_ids:
                judge_contest_ids.append(id)
            session["judge_for_contest_ids"] = (
                judge_contest_ids  # 更新したリストをセッションに保存
            )
            session.modified = True
            # --- ▲▲▲ ここまで ▲▲▲ ---

            print(
                f"--- Judge Login Success: User {session.get('user_id')} for Contest {id} ---"
            )
            print(
                f" -> Current Judge Contests in Session: {session['judge_for_contest_ids']}"
            )

            return jsonify({"redirectUrl": f"/venue/{id}"}), 200
        else:
            print(
                f"--- Judge Login Failed: User {session.get('user_id')} for Contest {id} ---"
            )
            return jsonify({"error": "パスワードが正しくありません。"}), 401

    except Exception as e:
        print(f"!!! ERROR at POST /api/contests/{id}/judge/login: {e}")
        traceback.print_exc()
        return jsonify({"error": "審査員認証中にエラーが発生しました。"}), 500
