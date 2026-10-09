# ネタツイグランプリ

ネタツイを投稿・投票・審査するコンテストサイトです。このリポジトリは API・データ管理・認証・大会イベントの処理を担当します。

- フロントエンドのURL（別リポジトリ）: [netatwi-frontend](https://github.com/Megane14916/netatwi-frontend)
- サイトURL: [https://n-1gp.vercel.app](https://n-1gp.vercel.app)

## 使用技術

| 領域 | 技術 |
| --- | --- |
| フロントエンド | Next.js 14（App Router）、React 18、TypeScript |
| UI・データ取得 | Tailwind CSS、Radix UI、SWR |
| バックエンド | Python 3.11、Flask、SQLAlchemy、Gunicorn、Cloud Run |
| データ・画像 | Neon PostgreSQL、Cloudflare R2（ローカル DB は SQLite） |
| 非同期処理・認証 | Cloud Tasks、Cloud Run Jobs、X API（OAuth 2.0） |
| テスト・CI | pytest、pytest-flask、GitHub Actions（frontend は Jest、Testing Library） |
| デプロイ | Vercel、Cloud Run 向け Dockerfile |

## システム構成

```text
[利用者のブラウザ]
   │ 画面表示・操作、Cookie 付き /api/*
   ⇅
[Next.js / Vercel]
   │ /api rewrite・Server Component の通信
   ⇅
[Flask API / Cloud Run] ──データの読み書き──⇄ [Neon PostgreSQL]
   ├─ 大会イベントを予約 ──▶ [Cloud Tasks]
   │                            └─ 指定時刻に HTTP 実行 ──▶ [Flask API]
   ├─ 投稿画像を保存・削除 ──▶ [Cloudflare R2] ──公開画像を配信──▶ [ブラウザ]
   └─ トークン交換・ユーザー情報取得 ──⇄ [X API]

[利用者のブラウザ] ──ログイン認可・リダイレクト──⇄ [X の認可画面]
[Cloud Run Jobs / ユーザーランキング集計]
   └─ 大会結果を読み、UserStats を更新 ──⇄ [Neon PostgreSQL]
```

- **画面と API:** ブラウザの `/api/*` は Next.js が Cloud Run に転送します。Server Component は `BACKEND_URL` で直接 API を呼びます。
- **認証と画像:** X の認可後、コールバックは `/api/callback/twitter` を通って API に届きます。API はセッション Cookie を発行し、投稿画像を R2 に保存します。ブラウザは R2 の公開 URL から画像を読みます。
- **大会イベント:** API が投稿開始・投票開始・結果発表を Cloud Tasks に予約します。Tasks は指定時刻に API を呼び、API が通知と大会結果を Neon に保存します。
- **ランキング:** Cloud Run Jobs が Neon の大会結果を読み、`UserStats` の順位を更新します。API は保存された順位を画面へ返します。

## ディレクトリ構成

| パス | 役割 |
| --- | --- |
| `app.py` / `wsgi.py` | 開発サーバー / Gunicorn の起動入口 |
| `app/factory.py` / `app/config.py` / `app/extensions.py` | アプリ生成・環境設定・DB などの拡張機能 |
| `app/routes/` | 機能ごとの Blueprint・HTTP リクエストとレスポンス |
| `app/services/` | 大会・投稿・投票・集計・権限などの業務処理 |
| `app/models/` | SQLAlchemy のモデル・リレーション |
| `app/integrations/` | X OAuth・画像ストレージ・Cloud Tasks との連携 |
| `app/cli/` | 大会イベント処理・ランキング集計・画像削除の再試行 |
| `tests/` / `docs/` | テスト・開発資料 |
| `Dockerfile` / `.github/workflows/tests.yml` | Cloud Run 用コンテナ・CI |

`from app import create_app` でアプリケーションファクトリを取得します。HTTP 層は `app/routes/`、業務処理は `app/services/`、外部サービスとの通信は `app/integrations/` に配置します。個人用の補助スクリプトは Git 管理外の `scripts/` に置きます。詳しくは [補助スクリプトの運用](docs/local-scripts.md) を参照してください。

## 開発環境構築

### 前提条件

- Python 3.11（Dockerfile・CI と共通）
- frontend を動かす場合は Node.js 20.x / npm 10.x
- X ログインを試す場合は X Developer Portal の OAuth 2.0 クライアント情報

### セットアップ

2 つのリポジトリを同じ親ディレクトリに配置します。

```sh
git clone https://github.com/Megane14916/netatwi-frontend.git
git clone https://github.com/Megane14916/netatwi-backend.git
```

backend の準備（PowerShell）:

```powershell
cd netatwi-backend
Copy-Item .env.example .env
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

起動前に `.env` の `SECRET_KEY` をローカル用の値へ変更します。Cloud Tasks を使わない場合は、設定例に入っている `GCP_PROJECT_ID`・`GCP_LOCATION`・`GCP_QUEUE_NAME`・`TASK_HANDLER_URL` を空にしてください。最低限の設定は [環境変数](#環境変数) の例を参照してください。

```powershell
python app.py
```

macOS / Linux では `Copy-Item` を `cp`、仮想環境の作成を `python3.11 -m venv .venv`、有効化を `source .venv/bin/activate` に置き換えます。backend は通常 `http://127.0.0.1:5001` で起動し、初回起動時にテーブルを作ります。`PORT` を設定すると待ち受けポートを変更できます。

別のターミナルで frontend を起動します。

```powershell
cd netatwi-frontend
Copy-Item .env.example .env.local
npm ci
npm run dev
```

macOS / Linux では `Copy-Item` を `cp` に置き換えます。frontend の `BACKEND_URL` は既定で `http://127.0.0.1:5001` です。`http://localhost:3000` を開き、`http://localhost:3000/api/contests` が JSON を返せば接続できています。

### テスト・CLI

仮想環境を有効化し、リポジトリ直下から実行します。

| コマンド | 内容 |
| --- | --- |
| `python -m pytest -q` | 全テスト（CI と共通） |
| `python -m pytest -q tests/unit` | 文字数計算・権限などの単体テスト |
| `python -m pytest -q tests/api` | API・セッション・入力検証・DB 更新のテスト |
| `python -m pytest -q tests/integration` | 起動入口・モデル・CLI・集計・外部連携などのテスト |
| `python -m flask --app app:create_app routes` | 登録済みルートの一覧 |
| `python -m flask --app app:create_app --help` | CLI の一覧 |
| `python -m flask --app app:create_app process-contests` | 大会の状態変化に応じた通知・結果集計 |
| `python -m flask --app app:create_app update-user-stats` | 大会結果から `UserStats`・ランキングを更新 |

通常のテストは一時 SQLite DB と外部サービスの fake を使うため、frontend や本番の資格情報は不要です。PostgreSQL の並行処理テストは CI の専用ジョブで使い捨て DB を使って検証し、通常のローカル実行ではスキップします。詳しくは [テストの実行](tests/README.md) を参照してください。

集計 CLI は `.env` の接続先 DB を更新します。ローカルでは `python app.py` でテーブルを作成してから使います。`create_app`・WSGI・CLI の起動自体はテーブルを作成しません。

## 環境変数

[`.env.example`](.env.example) を `.env` にコピーして使います。設定の読み込みは [`app/config.py`](app/config.py) を参照してください。

| 変数 | 用途 |
| --- | --- |
| `FLASK_DEBUG` | `True` でローカル向けの DB・Cookie・HTTP OAuth 設定を使用。本番は未設定または `False` |
| `SQLALCHEMY_DATABASE_URI` | ローカルは `sqlite:///project.db`、本番は Neon PostgreSQL の接続 URI |
| `SECRET_KEY` | セッション管理用の秘密鍵。本番は十分な長さのランダムな値を設定 |
| `FRONTEND_URL` | CORS・ログイン後の遷移・OAuth コールバックの基準 URL。ローカルは `http://localhost:3000` |
| `GCR_URL` | 本番の backend の HTTPS オリジン。Cloud Tasks の送信先の代替値にも使用 |
| `PORT` | 待ち受けポート。開発サーバーは既定で `5001`、コンテナでは Cloud Run が指定 |
| `X_CONSUMER_KEY` / `X_CONSUMER_SECRET` | X OAuth 2.0 の Client ID / Client Secret |
| `ADMIN_SCREEN_NAMES` | 管理者として許可する X アカウントの screen_name（カンマ区切り） |
| `USE_R2` | `True` で R2 に画像を保存。`False` では `static/uploads/` にローカル保存 |
| `R2_BUCKET_NAME` / `R2_PUBLIC_URL` | R2 のバケット名 / 画像を配信する公開 URL |
| `R2_ENDPOINT_URL` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` | R2 の S3 互換 API エンドポイントと資格情報 |
| `GCP_PROJECT_ID` / `GCP_LOCATION` / `GCP_QUEUE_NAME` | Cloud Tasks のプロジェクト・リージョン・キュー名 |
| `TASK_HANDLER_URL` | Cloud Tasks の送信先となる backend の HTTPS オリジン（未設定時は `GCR_URL`） |
| `TASKS_OIDC_AUDIENCE` | Tasks の OIDC トークンの audience。送信側と検証側で同じ値を使用 |
| `TASKS_SERVICE_ACCOUNT_EMAIL` | Tasks の OIDC トークンを発行し、API が呼び出し元として許可するサービスアカウント |

ローカル設定例（Cloud Tasks を使わない場合）:

```dotenv
FLASK_APP=app.py
FLASK_DEBUG=True
SQLALCHEMY_DATABASE_URI=sqlite:///project.db
SECRET_KEY=replace-with-your-local-secret
FRONTEND_URL=http://localhost:3000
USE_R2=False
GCP_PROJECT_ID=
GCP_LOCATION=
GCP_QUEUE_NAME=
TASK_HANDLER_URL=
```

SQLite の DB は `instance/project.db` に作成されます。`FLASK_DEBUG=True` はローカル向け設定の切り替えに使われますが、`python app.py` は `debug=False` で起動します。

X ログインには実際の `X_CONSUMER_KEY` / `X_CONSUMER_SECRET` と、X 側のコールバック URL `http://localhost:3000/api/callback/twitter` が必要です。ログイン時はブラウザで `localhost:3000` を使い、`FRONTEND_URL` とホスト名を揃えます。

Cloud Tasks の予約には送信先と GCP の設定、OIDC の 2 変数、Google Cloud の認証情報・権限が必要です。GCP または送信先の設定が不足すると予約をスキップします。Tasks 用 API は OIDC 設定がなければ `503` を返し、設定済みの場合はトークンの audience と呼び出し元を検証します。

`USE_R2=False` では画像 URL が `/static/uploads/...` になります。frontend の rewrite は `/api/*` が対象のため、画面でローカル画像を表示する場合は `/static/uploads/*` の配信設定も必要です。R2 を使う場合は frontend の `next.config.js` の `images.remotePatterns` を公開画像ホストに合わせます。

## デプロイ

[`Dockerfile`](Dockerfile) は Python 3.11 のイメージを使い、`gunicorn --bind "0.0.0.0:${PORT}" --workers 1 --threads 8 --timeout 0 "wsgi:app"` で API を起動します。

Cloud Run API に本番の `SQLALCHEMY_DATABASE_URI`・`SECRET_KEY`・`FRONTEND_URL`・`GCR_URL` と、X・R2・Cloud Tasks の設定を渡します。`FLASK_DEBUG` は未設定または `False` にします。WSGI 起動時にテーブルは自動作成されないため、デプロイ前に本番 DB のスキーマを準備・更新してください。

Cloud Tasks はキューと OIDC 用サービスアカウントを用意し、API からのタスク作成とサービスアカウントによるトークン発行に必要な権限を設定します。`TASK_HANDLER_URL`・`TASKS_OIDC_AUDIENCE`・`TASKS_SERVICE_ACCOUNT_EMAIL` を API の設定と揃えます。

ユーザーランキング集計は同じイメージを Cloud Run Jobs で使い、コマンドを `python`、引数を `-m flask --app app:create_app update-user-stats` に変更して実行します。Jobs にも同じ Neon の接続 URI と、アプリ生成に必要な `SECRET_KEY`・`FRONTEND_URL` を設定します。

frontend は Vercel に接続し、`BACKEND_URL` に稼働中の backend の HTTPS オリジンを設定します。backend の `FRONTEND_URL` と X のコールバック URL は公開サイトに合わせます。詳細は [frontend の README](https://github.com/Megane14916/netatwi-frontend#readme) を参照してください。
