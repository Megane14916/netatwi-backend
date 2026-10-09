# ネタツイグランプリ バックエンド

ネタツイを投稿・投票・審査するコンテストサイトです。このリポジトリは API・データ管理・認証を担当します。

- フロントエンドのリポジトリURL: [netatwi-frontend](https://github.com/Megane14916/netatwi-frontend)
- サイトURL: [https://n-1gp.vercel.app](https://n-1gp.vercel.app)

## 使用技術

| 領域 | 技術 |
| --- | --- |
| フロントエンド | Next.js 14（App Router）、React 18、TypeScript |
| UI・データ取得 | Tailwind CSS、Radix UI、SWR |
| バックエンド | Flask、SQLAlchemy、Cloud Run |
| データ・画像 | Neon PostgreSQL、Cloudflare R2（ローカル DB は SQLite） |
| 非同期処理・認証 | Cloud Tasks、Cloud Run Jobs、X API（OAuth 2.0） |
| テスト・CI | Jest、Testing Library、GitHub Actions |
| デプロイ | Vercel、Cloud Run |

## システム構成

画面は Next.js / Vercel、API は Flask / Cloud Run で動作します。データは Neon、画像は R2 に保存し、X でログインします。大会イベントは Cloud Tasks、ランキング集計は Cloud Run Jobs で処理します。

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

## 開発環境構築

Python 3.11 を使用します。リポジトリ直下で実行してください（PowerShell）。

```powershell
Copy-Item .env.example .env
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

`.env` を設定してから起動します。

```powershell
python app.py
```

`http://127.0.0.1:5001` で起動し、初回起動時にテーブルを作成します。

## 環境変数

設定項目は [`.env.example`](.env.example) を参照してください。ローカルでは次の値を設定します。

```dotenv
FLASK_DEBUG=True
SQLALCHEMY_DATABASE_URI=sqlite:///project.db
SECRET_KEY=replace-with-your-local-secret
FRONTEND_URL=http://localhost:3000
USE_R2=False
GCP_PROJECT_ID=
```

Cloud Tasks を使わない場合は `GCP_PROJECT_ID` を空にします。X ログインには `X_CONSUMER_KEY` / `X_CONSUMER_SECRET` と、コールバック URL `http://localhost:3000/api/callback/twitter` の登録が必要です。

## テスト

```powershell
python -m pytest -q
```

詳細は [tests/README.md](tests/README.md) を参照してください。

## デプロイ

[Dockerfile](Dockerfile) を使って Cloud Run にデプロイします。本番用の環境変数を設定し、`FLASK_DEBUG` は `False` にします。
