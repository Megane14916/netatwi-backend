"""X OAuth protocol and user-info HTTP boundary."""

import base64
import hashlib
import logging
import os
import secrets

from requests.auth import HTTPBasicAuth
from requests_oauthlib import OAuth2Session


logger = logging.getLogger("app")

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


def build_authorization(callback_url):
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

    return authorization_url, state, code_verifier


def fetch_user_data(callback_url, session_state, code_verifier, code):
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

    return user_data
