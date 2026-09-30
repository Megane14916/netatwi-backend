# netatwi-backend リファクタリング計画

## 目的と対象

`netatwi-backend` の保守性と検証可能性を上げる。対象はバックエンドの Flask アプリ、SQLAlchemy モデル、バッチ／外部サービスとの接続、テストである。フロントエンドは別リポジトリとして扱い、バックエンドの API 契約を先に固定する。

この計画では **(1) 現行動作の記録とテスト、(2) ファイルの移動・分割、(3) services 層への責務の移動、(4) 挙動を改善する修正** を順番に進める。ファイル分割とロジック改善は同じ PR に入れない。構造変更 PR では URL、HTTP メソッド、ステータス、JSON のキーと型、認証条件、DB スキーマ、時刻・スコア計算、外部サービスへの副作用を維持する。現行動作に不具合があれば再現テストと修正を別 Issue／PR にする。

## 調査時点の状態

- デフォルトブランチと PR の取り込み先は `master` とする。現在のチェックアウトも `master`（`origin/master` を追跡）。`dev` と `fix/x-login-bug` は作業ブランチの起点に使わない。
- `app.py` は約 3,064 行、`@app.route` は 35 箇所。起動時設定、CORS・Limiter・Migrate、X OAuth、投稿と画像、投票、結果集計、プロフィール、管理 API、ニュース、コメント、通知、Cloud Tasks、CLI コマンドが混在している。
- `models.py` は約 207 行で `db` と 10 モデル（`User`, `Contest`, `Post`, `Vote`, `Bookmark`, `Comment`, `Notification`, `ContestResult`, `UserStats`, `News`）を定義する。テーブル名、外部キー、制約、リレーション名は分割時に維持する。
- テストは `tests/test_scoring.py` の 2 件のみ。テストは `calculate_contest_results` を import するが、現行 `app.py` にある関数名は `generate_contest_results` と `get_cached_contest_results`。テストの期待値も現行の保存型集計に合わせて確認し直す必要がある。`tests/conftest.py` はアプリを import した後に DB URI を変更しており、接続先の分離を保証できない。
- `app.py` の import 時に環境変数を検証し、`static/uploads` を作成する。テスト・CLI・WSGI の起動方法に影響するため、初期化順を保った段階的な変更が必要。
- Cloud Tasks の HTTP ハンドラと `process-contests` CLI が大会通知・結果生成をそれぞれ実装している。スケジュール、再実行、通知の重複、コミット境界をテスト対象にする。
- `Dockerfile` は `gunicorn ... "app:app"` で起動し、`sync_comment_counts.py` などの補助スクリプトも `from app import app` / `from models import ...` を使用する。移行中は互換入口を維持する。
- `migrations/` は `.gitignore` に指定されている。既存の追跡ファイルはあるが、新しい revision の扱いはスキーマ変更 Issue で明示する。モデル分割 PR は migration 不要・自動生成差分ゼロを条件とする。
- 調査環境の `venv` と `py` ランチャーは Python プロセスを起動できず、現時点で pytest の実行結果は取得できていない。最初の Issue で再現可能な Python 環境と実行手順を確立する。

## 到達したい構成

以下は責務の目安。ディレクトリ名は最初の構造 PR で確定する。

```text
app.py                    # app:app の互換入口と起動のみ
netatwi/
  __init__.py              # create_app(config) と Blueprint／CLI 登録
  config.py                # 環境設定
  extensions.py            # db, migrate, limiter 等の一度だけの生成
  models/                  # db を共有するモデル定義と全モデルの登録
  routes/                  # auth, contests, posts, voting, results,
                           # profile, admin, news, interactions,
                           # comments, notifications, tasks
  services/                # 認証連携、投稿・画像、投票、集計、
                           # 大会ライフサイクル、通知、統計
  integrations/            # X API、R2、Cloud Tasks の境界
  cli/                     # process-contests, update-user-stats
tests/
  unit/
  api/
  integration/
```

routes は HTTP 入力・セッションの読み取り、service 呼び出し、HTTP 応答への変換を担当する。services は大会期間や権限に関わる判断、集計、DB 更新の単位、外部処理の調整を担当する。DB と外部サービスの依存は差し替え可能にし、循環 import を作らない。モデルは永続化定義と単純な値変換に絞る。`create_app` を導入しても、移行期間は `app.py` から `app` と必要な互換名を公開する。

## Issue と PR の実施順

各行を原則 1 Issue・1 ブランチ・1 PR とする。大きくなった場合は同じ種類の作業の中で API 群ごとにさらに分ける。Issue には予定する対象外作業を **「やらないこと」**、PR には完成した差分に含まれない作業を **「やってないこと」** として記載する。PR には変更範囲と検証結果も必ず記載する。

| 順 | Issue／PR の主題 | やること | 対象外・完了条件 |
| --- | --- | --- | --- |
| 1 | 最初のテスト追加と GitHub Actions | Python の実行手順、`app` import 前にテスト用環境変数を設定するテスト初期化、一時 SQLite DB、外部 API／R2／Cloud Tasks のモック、最初の有効なテストを用意。既存テストの関数名・期待値のずれを現行仕様に照らして修正する。同じ PR に GitHub Actions の `pytest` ワークフローを追加し、`master` 向け PR と `master` への push で実行する。 | アプリ機能を変えない。実 DB・外部サービスへ接続しない。ローカルと GitHub Actions でテスト収集・実行が可能。 |
| 2 | 現行 API の特性テスト | 全 35 route の URL・メソッド・endpoint 名を記録。認証、権限、期間境界、投稿、投票、結果、管理、コメント、通知などの代表的な正常／異常応答をテストする。 | 仕様を理想形に直さない。構造変更前の振る舞いを明文化する。 |
| 3 | 集計・副作用のテスト | `generate_contest_results` の採点方式、同点順位、予選進出、審査員賞、空大会、再実行を検証。Cloud Tasks と CLI の通知・結果保存、カウンタ、画像の保存／削除はモックとテスト DB で確認する。 | 集計アルゴリズムや副作用の順序を変更しない。 |
| 4 | 起動・設定の分割 | `create_app`、設定、拡張機能、共通フック、エラーハンドラを分ける。テスト fixture はアプリ生成時に設定を渡す方式へ移す。`app:app` と Flask CLI の入口を保つ。 | API の移動とビジネスロジック改善を含めない。起動設定・URL マップが同等。 |
| 5 | `models.py` の分割 | 単一 `db` と全モデルを `models/` に分け、import 互換と Alembic metadata 登録を確認する。 | カラム、テーブル名、制約、リレーション、クエリを変えない。migration の自動生成差分がゼロ。 |
| 6 | 認証・管理・ニュース route の移動 | X ログイン／コールバック、審査員認証、管理 API、ニュース API を Blueprint に移す。 | 認証・パスワード・エラー処理を改善しない。URL・endpoint 名・レスポンスを維持。 |
| 7 | 大会・投稿・プロフィール route の移動 | 大会一覧／詳細、投稿 CRUD、プロフィールを Blueprint に移す。 | SQL・表示条件・画像処理を改善しない。API 契約が同等。 |
| 8 | 投票・結果・交流 route の移動 | 投票、結果、ブックマーク、いいね、コメント、通知、ユーザー一覧を Blueprint に移す。 | 集計式・投票条件・カウンタ処理を改善しない。API 契約が同等。 |
| 9 | tasks・CLI の分割 | Cloud Tasks ハンドラと 2 つの CLI コマンドを専用モジュールへ移す。 | 通知タイミング、冪等性、コミット回数を変えない。CLI 名と task URL を維持。 |
| 10 | services 層への移動 | route／CLI にあるビジネス処理を領域ごとに services へ**そのまま**抽出する。投稿・画像、投票、集計、大会ライフサイクル、通知・統計、認証連携を小 PR に分ける。 | 抽出 PR ではロジックの最適化・不具合修正をしない。route を薄くし、特性テストを通す。 |
| 11 | 品質改善 | 10 までの後に、重複した判定やシリアライズ、例外・ログ、入力検証、トランザクション境界、型・lint を対象別 Issue で改善する。修正ごとに再現テストを追加する。 | ファイル分割を含めない。意図した変更以外の API 契約を維持する。 |
| 12 | 運用上の不具合・安全性 | 別 Issue で優先度を付け、例えば task ハンドラの呼出元認証、OAuth 時のヘッダ／セッションログ、投票対象の大会確認、画像と DB の整合性、削除時の参照整合性を調査・修正する。 | 構造変更と混ぜない。仕様変更やデータ移行が必要ならその内容と影響を個別 PR に書く。 |

順 6〜8 は実際の差分が大きければさらに分割する。順 10 の service 抽出も領域ごとに独立した PR とし、「ファイル移動」と「ロジック改善」を同一 PR にしない。現在の挙動を固定すると危険な点は、特性テストにその事実を記録し、修正 Issue を別に起こす。

## テスト方針と各段階のゲート

- **unit**: 文字数計算、期間判定、採点方式、同点順位、進出判定、通知イベント判定、ユーザー統計の順位。時刻は固定し、DB が不要な計算は純粋関数へ移した後に個別テストする。
- **API**: Flask test client で匿名／一般／審査員／管理者を用意。投稿・投票・審査員賞・集計結果・プロフィール・コメント・ブックマーク・通知・管理の HTTP 契約を確認する。境界時刻、0 点、同点、空データ、同じリクエストの再実行を含める。
- **integration**: テスト DB 上で model metadata、制約、カウンタと行データ、commit／rollback、Cloud Tasks と CLI の経路を確認する。PostgreSQL 固有の SQL・型・制約に依存する箇所は CI で PostgreSQL の検証枠を設ける。
- **外部サービス**: X OAuth、R2、Cloud Tasks は固定レスポンスの fake／mock を使い、認可 state とセッション、アップロード／削除、タスクの URL と予定時刻を検証する。実サービスの資格情報を CI に要求しない。
- **実行環境**: ローカルでは Dockerfile に合わせた Python 3.11 の仮想環境を作り、`requirements.txt` を入れて `python -m pytest -q` を実行する方法を基本とする。最初のテストは `app` の import 前にテスト用 URI を環境変数へ設定し、一時 SQLite DB で実行する。順 4 の後は `create_app` にテスト設定を渡す。GitHub Actions でも Python 3.11 と一時 SQLite DB を使い、最初のテスト追加 PR から毎回実行する。PostgreSQL 固有の挙動や migration を検証する段階では、別途 GitHub Actions の PostgreSQL service container を使うテストを追加する。
- **構造変更 PR の必須確認**: `pytest` 全件、URL map の差分、`app:app` での起動、CLI 名、全モデルの metadata、Alembic の schema diff。route の差分は入力と出力・副作用が等価であることをレビューする。
- **挙動変更 PR の必須確認**: 変更前に失敗する再現テスト、変更後の全件テスト、API・DB・運用への影響、必要な移行／ロールバック手順。品質ツールは最初に既存警告の範囲を記録し、以降は変更箇所から段階的に適用する。

## Issue・ブランチ・PR の運用

1. バックエンド GitHub リポジトリに上表の Issue を作り、`test`、`structure`、`service`、`behavior` などのラベルと依存先を付ける。別リポジトリのフロントエンド変更が必要になった場合は、その Issue をフロントエンド側に作り、相互リンクする。
2. 取り込み先は `master` に統一し、各作業ブランチは最新の `master` から作る。`dev` を作業の起点や PR の取り込み先にしない。例: `test/123-isolated-fixtures`、`refactor/124-split-models`、`fix/125-vote-contest-check`。番号は実際の Issue 番号を使う。
3. 1 ブランチは 1 Issue の目的に絞り、1 PR で取り込む。積み重ねが必要な場合は依存 PR を明記し、前段の取り込み後に取り込み先へ追従させる。構造変更 PR と挙動変更 PR を混ぜない。レビューしやすい差分の大きさを優先する。
4. PR 説明には `Closes #番号`、変更内容、**やってないこと**、影響する API／DB／外部サービス、テスト結果、残るリスク、必要なデプロイ順と戻し方を書く。Issue は「やること／やらないこと／受け入れ条件」を持つ。PR の「やってないこと」は実際の差分と照合し、単に予定を書き写さない。
5. 最初のテスト追加と同じ PR で GitHub Actions を導入する。その PR 以降は Actions の成功とレビューを取り込み条件にする。リファクタリング中は各 PR の取り込み後にもテストを実行し、問題が出たらその PR 単位で戻せる状態を保つ。実 DB の migration や本番設定変更は別 PR・別手順として扱う。

### Issue 記述例（API 移動）

```text
タイトル: 大会一覧 API を Blueprint に移動する
やること: GET /api/contests と関連フックの登録位置を移し、URL map と API 特性テストで同等性を確認する。
やらないこと: レスポンス形式、キャッシュ時間、集計方法、DB クエリ、エラー処理の仕様は変えない。
受け入れ条件: URL・メソッド・endpoint 名が同じで、対象テストと全体テストが通る。
```

### PR 記述例（API 移動）

```text
Closes #<Issue 番号>
変更内容: 大会一覧 route を contests Blueprint に移動した。
やってないこと: API 仕様変更、キャッシュ／SQL の改善、モデル変更は行っていない。
検証: pytest、URL map 比較、app:app 起動確認。
影響・戻し方: URL／DB 変更なし。この PR を revert して元の登録位置に戻せる。
```

## 着手前に確認する事項

- `master` の保護ルールと既存の未取り込み PR。GitHub Actions は最初のテスト追加 PR で設定する。
- API 契約を変える個別 Issue に限り、フロントエンドが呼ぶ URL・メソッドと参照するレスポンス項目を確認し、必要なら両リポジトリのリリース順を決める。構造変更だけの PR では API 契約を維持するため、互換期間は設定しない。
- ローカルの Python 3.11 仮想環境と GitHub Actions 上の Python 3.11／一時 SQLite DB を実行可能にする。現環境では Python 起動に失敗したため、計画の順 1 の完了までテスト結果を成功と扱わない。
- 本番 DB の migration 履歴と Cloud Tasks の認証／再試行設定。構造変更では本番データを書き換えず、挙動修正の Issue で必要性を判断する。
