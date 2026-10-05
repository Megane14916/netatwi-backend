"""Authentication decisions, user synchronization and session updates."""

import logging

from flask import current_app, session

from app.integrations import x_oauth
from app.models import Contest, User, db


logger = logging.getLogger("app")


def start_twitter_login():
    callback_url = f"{current_app.config['FRONTEND_URL']}/api/callback/twitter"
    logger.info(f"Generated Callback URL: {callback_url}")

    authorization_url, state, code_verifier = x_oauth.build_authorization(callback_url)

    judge_ids = session.get("judge_for_contest_ids", [])
    session.clear()
    session["oauth_state"] = state
    session["code_verifier"] = code_verifier
    if judge_ids:
        session["judge_for_contest_ids"] = judge_ids
    session.modified = True

    logger.info(f"Saved to session - State: {state}")

    return authorization_url


def begin_twitter_callback():
    logger.info(f"=== CALLBACK START ===")
    logger.info(f"Session keys present: {list(session.keys())}")

    # セッションから検証用データを取得・削除
    session_state = session.pop("oauth_state", None)
    code_verifier = session.pop("code_verifier", None)

    return session_state, code_verifier


def validate_twitter_callback(session_state, code_verifier, url_state, code, error):
    if error:
        logger.error(f"X Login Error from URL: {error}")
        return error

    if not all([session_state, code_verifier, code]):
        logger.error("Missing state, code_verifier, or code in callback.")
        reason = "session_token_missing" if not session_state else "verifier_missing"
        return reason

    # state の一致検証（CSRF対策）
    if url_state != session_state:
        logger.error(f"State mismatch: url={url_state}, session={session_state}")
        return "state_mismatch"


def complete_twitter_login(session_state, code_verifier, code):
    callback_url = f"{current_app.config['FRONTEND_URL']}/api/callback/twitter"
    user_data = x_oauth.fetch_user_data(callback_url, session_state, code_verifier, code)
    return sync_twitter_user(user_data)


def sync_twitter_user(user_data):
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
            return "account_deleted"
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


def authenticate_judge(id, password):
    contest = Contest.query.get_or_404(id)

    if contest.scoring_method == "user":
        return "user_only"

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

        return "authenticated"
    else:
        print(
            f"--- Judge Login Failed: User {session.get('user_id')} for Contest {id} ---"
        )
        return "invalid_password"
