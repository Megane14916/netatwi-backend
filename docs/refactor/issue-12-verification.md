# Issue #12: 認証連携の service 抽出

計画書の「順 10」の認証領域。PR #36 取り込み後の `origin/master`
(`48c1b76`) から `refactor/12-auth-services` を作成した。

## 変更範囲

- `integrations/x_oauth.py`: PKCE、OAuth URL 生成、トークン交換、X のユーザー情報取得。
- `services/auth.py`: OAuth 開始時のセッション更新、callback 検証、ユーザー同期、
  ログインセッション更新、審査員認証の判断・セッション更新。
- `blueprints/auth.py`: HTTP 入力、service 呼び出し、JSON・リダイレクト、
  元の例外処理と rate limit を維持。
- 外部通信の fake は route ではなく integration の `OAuth2Session` を差し替える。

既存の文を AST の行番号で機械的に切り出した。AST から元の処理を再生成していない。
service と integration は Flask の応答を生成せず、認可 URL、ユーザーデータ、
失敗理由・認証結果を返す。HTTP 応答への変換は route が担当する。

## 同等性の比較

```powershell
python docs/refactor/verify_issue_12_extraction.py
python -m pytest -q -p no:cacheprovider
```

検証スクリプトは基準コミットの認証 route と比較し、8つの抽出関数の文を
AST で確認する。明示した関数呼び出しと戻り値の境界だけを許容する。
元の HTTP 応答を返していた箇所は、同じ失敗理由・認証結果を service から返し、
route で元の JSON・ステータス・リダイレクトに変換する。
route の引数・デコレータ・HTTP 入力・応答式・例外ハンドラも比較する。
OAuth 設定と `app.py` は変更していない。

## 検証結果

- 変更前の既存テスト: **97 passed**。
- 移動前に追加した認証の特性テスト: **22 passed**。
- 移動後の全テスト: **119 passed**。
- PKCE、`s256`、scope の `%20` 置換、セッション消去と審査員情報の引き継ぎを確認。
- callback の state・verifier・code・URL error、検証値の先行消費、
  新規／既存／退会済みユーザー、通信・データ・commit の失敗を確認。
- commit はセッションへのユーザー情報設定より前に実行され、失敗時は元の
  rollback と `callback_failed` 応答になることを確認。
- 認証ログの文言・順序、審査員認証の標準出力、再実行、既存の400／401／500応答、
  JSON `null` 時の例外、5回／分の rate limit を確認。
- 全35 route と static の URL map、factory、`app:app`、CLI 名が既存契約と同等。
- 全10モデルの metadata・DDL・リレーションが snapshot と一致。
  一時 SQLite の基準スキーマに対する Alembic 差分ゼロ。
- `git diff --check`: 成功。

ローカルは一時仮想環境 `netatwi-issue3-venv` の Python 3.12.14 を使用。
外部通信は fake とネットワーク拒否 fixture で隔離した。
Python 3.11 は PR の既存 GitHub Actions で確認する。
既存の SQLAlchemy・protobuf の非推奨警告は残る。

## コミットの区切り

1. 認証の特性テストを追加し、移動前に成功を確認。
2. service／integration への抽出と fake の差し替え先を更新し、全テストを確認。
3. 機械比較スクリプトと検証記録を保存。

## やってないこと・戻し方

OAuth フロー、認証条件、HTTP 契約、ログ内容、資格情報管理、
パスワード管理、セキュリティの改善は含まない。service の純粋関数化や
トランザクション境界の改善も行っていない。
DB migration、フロントエンド変更、特別なデプロイ順は不要。
問題があれば PR の3コミットをまとめて revert し、元の route に戻せる。
