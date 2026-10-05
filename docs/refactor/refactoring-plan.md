# netatwi-backend リファクタリング計画

## 目的と対象

`netatwi-backend` の保守性と検証可能性を上げる。対象はバックエンドの Flask アプリ、SQLAlchemy モデル、バッチ／外部サービスとの接続、テストである。フロントエンドは別リポジトリとして扱い、バックエンドの API 契約を先に固定する。

この計画では **(1) 現行動作の記録とテスト、(2) ファイルの移動・分割、(3) services 層への責務の移動と最終構成への配置統一、(4) 挙動を改善する修正** を順番に進める。ファイル分割とロジック改善は同じ PR に入れない。構造変更 PR では URL、HTTP メソッド、ステータス、JSON のキーと型、認証条件、DB スキーマ、時刻・スコア計算、外部サービスへの副作用を維持する。現行動作に不具合があれば再現テストと修正を別 Issue／PR にする。

## 当初の調査時点の状態

以下は計画作成時の記録であり、現在の配置・テスト数・実行環境を表すものではない。

- デフォルトブランチと PR の取り込み先は `master` とする。現在のチェックアウトも `master`（`origin/master` を追跡）。`dev` と `fix/x-login-bug` は作業ブランチの起点に使わない。
- `app.py` は約 3,064 行、`@app.route` は 35 箇所。起動時設定、CORS・Limiter・Migrate、X OAuth、投稿と画像、投票、結果集計、プロフィール、管理 API、ニュース、コメント、通知、Cloud Tasks、CLI コマンドが混在している。
- `models.py` は約 207 行で `db` と 10 モデル（`User`, `Contest`, `Post`, `Vote`, `Bookmark`, `Comment`, `Notification`, `ContestResult`, `UserStats`, `News`）を定義する。テーブル名、外部キー、制約、リレーション名は分割時に維持する。
- テストは `tests/test_scoring.py` の 2 件のみ。テストは `calculate_contest_results` を import するが、現行 `app.py` にある関数名は `generate_contest_results` と `get_cached_contest_results`。テストの期待値も現行の保存型集計に合わせて確認し直す必要がある。`tests/conftest.py` はアプリを import した後に DB URI を変更しており、接続先の分離を保証できない。
- `app.py` の import 時に環境変数を検証し、`static/uploads` を作成する。テスト・CLI・WSGI の起動方法に影響するため、初期化順を保った段階的な変更が必要。
- Cloud Tasks の HTTP ハンドラと `process-contests` CLI が大会通知・結果生成をそれぞれ実装している。スケジュール、再実行、通知の重複、コミット境界をテスト対象にする。
- `Dockerfile` は `gunicorn ... "app:app"` で起動し、`sync_comment_counts.py` などの補助スクリプトも `from app import app` / `from models import ...` を使用する。移行中は互換入口を維持する。
- `migrations/` は `.gitignore` に指定されている。既存の追跡ファイルはあるが、新しい revision の扱いはスキーマ変更 Issue で明示する。モデル分割 PR は migration 不要・自動生成差分ゼロを条件とする。
- 調査環境の `venv` と `py` ランチャーは Python プロセスを起動できず、現時点で pytest の実行結果は取得できていない。最初の Issue で再現可能な Python 環境と実行手順を確立する。

## 現在の進捗と次の工程（2026-10-05 更新）

- #3〜#17に続き、#43〜#52／PR #55〜#64を取り込み済み。コメント、交流、大会・投稿・プロフィール・ニュース・ユーザーの取得／更新と退会処理をserviceへ抽出し、全35 routeをBlueprintへ移した。
- #50でservicesからBlueprintへの共通依存を解消し、#51でfactory・登録処理を集約した。#52で58実装を `app/` 配下へ配置し、既存全テスト645件がローカル・GitHub Actionsで成功した。詳細は [#52検証記録](issue-52-verification.md) を参照する。
- #53の本PRではテストをunit/api/integrationへ配置し、同じ645ケース・snapshot・fixture・fakeを維持して全体監査を行う。アプリ本体はマージ済み#52と一致する。[#53検証記録](issue-53-verification.md) と [実行手順](../../tests/README.md) が現在の配置の記録である。
- #43〜#53の11件の構造工程は、#53のPRのマージで完了とする。その後、#18〜#22の品質改善と#23〜#27の運用上の不具合修正を別Issue/PRで進める。各Issueの前提も#53の完了へ更新する。
- 既存の権限判定の重複、route側のrollback・例外境界、OAuthログ、投票対象の大会所属、画像・削除の整合性は構造工程で改善していない。これらを構造完了と混同しない。

## 到達した構成

最終パッケージ名はユーザー指定の **`app/`** とする。当初の構成図の `netatwi/` は採用しない。実装は#52、テスト配置は#53で下記の構成へ移した。

```text
app.py                    # 直接起動と必要な互換入口
app/
  __init__.py              # create_app、app、登録関数・互換helperの公開
  factory.py               # アプリ生成、runtime初期化、Blueprint／CLI登録の本体
  config.py                # 環境設定
  extensions.py            # db, migrate, limiter 等の一度だけの生成
  hooks.py                 # 共通hook、エラーハンドラ
  runtime_dependencies.py  # アプリの現在のhelper/logger/schedulerへの接続
  models/                  # db を共有するモデル定義と全モデルの登録
  routes/                  # auth, contests, posts, voting, results,
                           # profile, admin, news, interactions,
                           # comments, notifications, users, tasks と残る基本 route
  services/                # 認証連携、投稿・画像、投票、集計、
                           # 大会ライフサイクル、通知、統計、コメント、
                           # 交流、プロフィール、ユーザー、ニュース等
  integrations/            # X API、R2、Cloud Tasks の境界
  cli/                     # process-contests, update-user-stats
tests/
  conftest.py              # 環境・SQLite・固定時刻・外部fake・通信拒否を共有
  unit/
  api/
  integration/
  snapshots/               # URL map、DDL、リレーション
```

routes は HTTP 入力・セッションの読み取り、service 呼び出し、HTTP 応答への変換を担当する。services は大会期間や権限に関わる判断、取得・集計、DB 更新の単位、外部処理の調整を担当する。DB と外部サービスの依存は差し替え可能にし、services から routes への依存や循環 import を作らない。モデルは永続化定義と単純な値変換に絞る。

旧 `blueprints/` の内容は `app/routes/` に移し、旧配置には薄いimport再公開だけを残した。models・CLIとflat moduleも同様にcanonical moduleと同じオブジェクトを再公開する。services/integrationsの旧childは遅延aliasで、rootは状態を持たない互換namespaceである。共通フック・ヘルパー接続も `app/` 配下へ配置済み。理由と全対応表は [#52検証記録](issue-52-verification.md) を参照する。

Pythonのimportでは同名の `app.py` より `app/` が優先される。`app:app`、`from app import app, create_app, db`、必要な互換helper、Flask CLI、`python app.py` と追跡対象の補助スクリプトの入口を検証済み。単独model/service importでアプリを起動しないため、#52以降は裸の `import app` では初期化せず、公開runtime属性を最初に参照した時点で既定appを初期化する。直接起動したappはpackageへ公開し、追加生成を防ぐ。

static/open_resource/instanceの基準は元のリポジトリへ固定し、UPLOAD_FOLDERとディレクトリ作成を保持する。db/migrate/limiterはextensionsに各1個、全10モデルのmetadata・制約・リレーションを保持する。db配置に伴うモデル定義の読込順の調整と公開属性の初期化時点の違いは#52の記録を引き継ぎ、#53で再変更しない。

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
| 10 | services 層への移動と構成整理 | #12〜#17 の抽出に続き、#43〜#49 で残る route のビジネス処理を services へ**そのまま**抽出する。#50〜#52 で共通依存・factory・`app/` 配下への配置を整理し、#53 でテスト配置と全体の完了を確認する。 | ロジックの最適化・不具合修正をしない。元ソース・AST の比較と特性テストを通し、最終配置と起動・import 互換を確認する。 |
| 11 | 品質改善 | #53 完了後に #18〜#22 等で、重複した判定やシリアライズ、例外・ログ、入力検証、トランザクション境界、型・lint を対象別 Issue で改善する。修正ごとに再現テストを追加する。 | ファイル分割を含めない。意図した変更以外の API 契約を維持する。 |
| 12 | 運用上の不具合・安全性 | #53 完了後に #23〜#27 で優先度を付け、task ハンドラの呼出元認証、OAuth 時のヘッダ／セッションログ、投票対象の大会確認、画像と DB の整合性、削除時の参照整合性を調査・修正する。 | 構造変更と混ぜない。仕様変更やデータ移行が必要ならその内容と影響を個別 PR に書く。 |

順 6〜8 は実際の差分が大きければさらに分割する。順 10 の service 抽出も領域ごとに独立した PR とし、「ファイル移動」と「ロジック改善」を同一 PR にしない。現在の挙動を固定すると危険な点は、特性テストにその事実を記録し、修正 Issue を別に起こす。

### 順 10 の追加 Issue（#43〜#53）

番号順を基本とし、各 Issue の依存先の取り込みを確認して着手する。いずれも取り込み先は `master`。#43〜#49 の抽出を終えてから共通依存・factory・配置を整理し、テスト配置と最終監査を行う。

| 順 | Issue | 作業範囲 | 依存 |
| --- | --- | --- | --- |
| 10-1 | [#43 コメント処理を services 層へ抽出する](https://github.com/Megane14916/netatwi-backend/issues/43) | 一覧・追加・編集・削除、重複・所有者・審査員判定、カウンタ更新。既存の通知 service を元の位置で呼ぶ。 | #10、#17 |
| 10-2 | [#44 いいね・ブックマーク処理を services 層へ抽出する](https://github.com/Megane14916/netatwi-backend/issues/44) | 条件判定、既存行・追加／削除・件数取得、IntegrityError を含む各経路。 | #10、#17 |
| 10-3 | [#45 大会一覧・詳細・管理一覧の取得処理を services 層へ抽出する](https://github.com/Megane14916/netatwi-backend/issues/45) | 期間別分類、最新結果・予選情報、並び順・表示データ、既存キャッシュ。 | #9、#16 |
| 10-4 | [#46 大会別投稿一覧の取得処理を services 層へ抽出する](https://github.com/Megane14916/netatwi-backend/issues/46) | 投稿・閲覧者の投票・コメント情報、投稿者数、表示データ構築。 | #9、#13、#14 |
| 10-5 | [#47 プロフィールの取得・表示データ構築を services 層へ抽出する](https://github.com/Megane14916/netatwi-backend/issues/47) | 投稿・ブックマーク・いいねの取得、公開期間判定、結果・審査員賞・閲覧者情報の組み合わせ。 | #9、#15、#46 |
| 10-6 | [#48 ニュースの取得・追加・削除処理を services 層へ抽出する](https://github.com/Megane14916/netatwi-backend/issues/48) | 公開／管理一覧、投稿 ID／URL の解析、追加・削除。 | #8 |
| 10-7 | [#49 ユーザー一覧・アカウント処理を抽出し、残る API を Blueprint に移す](https://github.com/Megane14916/netatwi-backend/issues/49) | ユーザー検索・ページング・統計表示、退会処理。me・logout・退会・トップの route を移す。 | #10、#12、#17 |
| 10-8 | [#50 共通ヘルパーを移し、services 層から Blueprint への依存を解消する](https://github.com/Megane14916/netatwi-backend/issues/50) | 文字数計算、画像設定・helper、logger・scheduler の接続。遅延参照・差し替え・必要な互換名を保持する。 | #43〜#49 |
| 10-9 | [#51 application factory と登録処理を集約し、app.py を互換入口にする](https://github.com/Megane14916/netatwi-backend/issues/51) | アプリ生成・Blueprint／CLI 登録・初期化を集約し、既定 app の URL map から不足 route を補う方式を整理する。 | #49、#50 |
| 10-10 | [#52 バックエンドを app パッケージへ集約し、Blueprint を routes 配下に移す](https://github.com/Megane14916/netatwi-backend/issues/52) | `app/` 配下への機械的移動、`blueprints/` から `app/routes/` への移動、import と必要な再公開の調整。 | #50、#51 |
| 10-11 | [#53 テストを unit・api・integration に整理し、構造リファクタリングの完了を確認する](https://github.com/Megane14916/netatwi-backend/issues/53) | テスト・fixture・snapshot の配置、CI 収集、計画書・実行手順・検証記録の整合と全体監査。#18〜#27 の前提も更新する。 | #52 |

#43〜#52は上の順にPR #55〜#64でマージ済み。#53は本PRでテスト配置と完了監査を行う。
各完了commit・担当service・現在の契約テストは [#53の全体監査](issue-53-verification.md) に記録する。

### 構造リファクタリングの完了条件

- route は HTTP／セッション入力、service 呼び出し、応答変換を担当し、対象の取得・判断・更新処理を service へ移している。
- service が route モジュールを import せず、循環 import・処理本体の二重定義・db／モデル／app の二重生成・route／CLI の二重登録がない。
- 本体は `app/models/`・`app/routes/`・`app/services/`・`app/integrations/`・`app/cli/` と設定・拡張機能・共通モジュールへ配置され、`app.py` は直接起動と必要な互換入口に絞られている。旧配置に必要な再公開が残る場合は、その対象と理由を記録する。
- `tests/unit/`・`tests/api/`・`tests/integration/` の収集・共有 fixture・snapshot・fake が機能する。分類のためにテストの期待値を変更したり、削除・skip したりしない。
- ソース・AST 比較と全テスト、URL map、WSGI・CLI・直接起動・補助スクリプトの import、モデル契約・Alembic 差分ゼロを確認し、#53 で記録する。API・SQL・判定・副作用・commit／rollback・例外境界の改善はこの工程に含めない。

## 挙動を保つ service 抽出の手順

#12〜#17 で行った抽出・検証を、#43〜#53 でも作業内容に応じて引き継ぐ。特に、直近の #16・#17 では以下を実施した。

1. **基準を固定し、移動前にテストする。** 最新の `master` から分岐し、比較するコミット SHA と元ファイルを記録する。既存テストを実行し、対象の正常・異常、権限・期間境界、再実行、DB と外部副作用、commit／rollback の順序・回数の特性テストを追加する。追加テストが元コードで成功してから最初のコミットに保存する。期待値は現在の挙動に合わせ、不具合の修正を混ぜない。
2. **元ソースから機械的に切り出す。** AST の `lineno`・`end_lineno` 等で対象関数／文の範囲を特定し、コメントを含む元ソースをコピーする。関数本体を `ast.unparse` 等で再生成せず、SQL、条件式、ループ、時刻取得、通知・画像処理、commit／rollback、例外とその順序を保持する。まとめ直し・名前の一括整理・共通化・最適化は行わない。
3. **接続の変更を最小限にする。** route に HTTP 入力と応答変換を残し、元の位置から service を呼ぶ。必要な引数の受け渡し・import・再公開・外側の `jsonify` の扱いを明示的に調整する。CLI 名・callback・decorator・docstring、互換 helper、設定・logger・scheduler・client cache の解決時点を保つ。テストの固定時刻・外部 client fake は移動先へ接続し、テスト本体・期待値を保持する。
4. **ソースと AST の両方を比較する。** `git show <基準SHA>:<元ファイル>` で元コードを取得し、抽出範囲のソース（必要なインデント・改行の正規化を除く）と AST を比較する。HTTP 戻り値等の許可した調整だけを比較側にも適用し、それ以外の一致を確認する。nested helper の return や抽出対象外の except まで変更しないよう、変換範囲を抽出した文に限定する。import・定数・引数・呼出元のモジュール全体も確認し、認証・入力・commit・例外境界や他の route に意図しない変更がないことを検証する。
5. **移動後の契約・副作用を検証する。** 全テスト、URL map、起動・CLI、モデル契約・Alembic 差分を確認し、GitHub Actions の Python 3.11 でも成功を確認する。ソース・AST の一致は許可した構造変換の範囲を確認する手段であり、import 解決・初期化・設定・HTTP／DB／外部副作用の実行テストと併用する。抽出と fake の接続先変更を次のコミットに保存する。
6. **比較スクリプトと記録を残す。** `docs/refactor/verify_issue_<番号>_extraction.py` と `issue-<番号>-verification.md` に、基準 SHA・元と先の対応・許可した調整・移動前後のテスト結果・残る挙動・実行環境・対象外・戻し方を保存し、次のコミットにする。作業中はこのような検証済みの区切りで定期的にコミットし、PR には最終差分と実施した検証を記載する。

参考となる実施記録:

- [#16 の検証記録](issue-16-verification.md)／[比較スクリプト](verify_issue_16_extraction.py): CRUD・task の HTTP 戻り値だけを調整し、CLI 本体と Cloud Tasks 関数・cache をコピー。呼出元の認証・例外境界・予定作成と fake の接続を比較した。
- [#17 の検証記録](issue-17-verification.md)／[比較スクリプト](verify_issue_17_extraction.py): 通知5関数の本体を比較し、統計関数は全文ソース・AST の一致を確認。route／CLI の接続、時刻 fake の変更、追加テストと他の既存 Python ファイルの保持を確認した。

各比較スクリプトは、その Issue の抽出時点と固定した基準を対象とする。後続 Issue が同じファイルを移動・変更した場合は新しい基準と対応表を用い、古い検証記録を現在の全体検証と混同しない。

#52までの抽出/比較scriptと記録は歴史的な配置・テスト数を保持する。再確認は該当PRの
完了commitを別checkoutで行い、現在のパスに合わせて歴史的scriptを書き換えない。
#53の配置比較は `23dbc5bc8acbc070bbfdacc63626e45a55c0e184` を基準とし、
`extract_issue_53.py`、`verify_issue_53_extraction.py`、`check_issue_53_collection.py` で行う。
これらも#53時点の移動専用であり、後続の意図した挙動変更には新たな基準を用意する。

## テスト方針と各段階のゲート

- **unit**: 既に DB・HTTP・外部サービスを必要としない文字数計算等を個別に検証する。期間判定・採点・順位等は依存に応じて API／integration で特性を固定する。テスト分類のための純粋関数化・アルゴリズム再設計は構造変更に混ぜず、必要なら後の品質改善 Issue で扱う。
- **API**: Flask test client で匿名／一般／審査員／管理者を用意。投稿・投票・審査員賞・集計結果・プロフィール・コメント・ブックマーク・通知・管理の HTTP 契約を確認する。境界時刻、0 点、同点、空データ、同じリクエストの再実行を含める。
- **integration**: テスト DB 上で model metadata、制約、カウンタと行データ、commit／rollback、Cloud Tasks と CLI の経路を確認する。PostgreSQL 固有の SQL・型・制約に依存する箇所は CI で PostgreSQL の検証枠を設ける。
- **外部サービス**: X OAuth、R2、Cloud Tasks は固定レスポンスの fake／mock を使い、認可 state とセッション、アップロード／削除、タスクの URL と予定時刻を検証する。実サービスの資格情報を CI に要求しない。
- **実行環境**: ローカルでは Dockerfile に合わせた Python 3.11 の仮想環境を作り、`requirements.txt` を入れて `python -m pytest -q` を実行する方法を基本とする。最初のテストは `app` の import 前にテスト用 URI を環境変数へ設定し、一時 SQLite DB で実行する。順 4 の後は `create_app` にテスト設定を渡す。GitHub Actions でも Python 3.11 と一時 SQLite DB を使い、最初のテスト追加 PR から毎回実行する。PostgreSQL 固有の挙動や migration を検証する段階では、別途 GitHub Actions の PostgreSQL service container を使うテストを追加する。
- **構造変更 PR の必須確認**: service 抽出・配置変更の元ソースと AST の比較、`git diff --check`、`pytest` 全件、URL map の差分、`app:app` での起動、CLI 名、全モデルの metadata、Alembic の schema diff。route の差分は入力と出力・副作用が等価であることをレビューする。配置統一では直接起動・補助スクリプトの import、static／uploads の位置、拡張機能・モデルの一度だけの登録も確認する。
- **挙動変更 PR の必須確認**: 変更前に失敗する再現テスト、変更後の全件テスト、API・DB・運用への影響、必要な移行／ロールバック手順。品質ツールは最初に既存警告の範囲を記録し、以降は変更箇所から段階的に適用する。

現在の実行手順は [tests/README.md](../../tests/README.md)。unit 19・api 479・integration 147の
合計645ケースを共通conftestで収集する。保存型集計やHTTP/CLI混合テストをunit扱いせず、
分類のためにfixture・期待値・アプリのロジックを変更しない。snapshotはtests/snapshotsに集約した。
GitHub Actionsの既存 `python -m pytest -q` は全分類を再帰的に収集するため、workflowを変更しない。
#53のローカル検証はPython 3.11.16で行い、制限環境では `--basetemp` で専用のGit管理外領域を使う。

## Issue・ブランチ・PR の運用

1. バックエンド GitHub リポジトリに上表の Issue を作り、`test`、`structure`、`service`、`behavior` などのラベルと依存先を付ける。別リポジトリのフロントエンド変更が必要になった場合は、その Issue をフロントエンド側に作り、相互リンクする。
2. 取り込み先は `master` に統一し、各作業ブランチは最新の `master` から作る。`dev` を作業の起点や PR の取り込み先にしない。例: `test/123-isolated-fixtures`、`refactor/124-split-models`、`fix/125-vote-contest-check`。番号は実際の Issue 番号を使う。
3. 1 ブランチは 1 Issue の目的に絞り、1 PR で取り込む。積み重ねが必要な場合は依存 PR を明記し、前段の取り込み後に取り込み先へ追従させる。構造変更 PR と挙動変更 PR を混ぜない。レビューしやすい差分の大きさを優先する。
4. PR 説明には `Closes #番号`、変更内容、**やってないこと**、影響する API／DB／外部サービス、テスト結果、残るリスク、必要なデプロイ順と戻し方を書く。Issue は「やること／やらないこと／受け入れ条件」を持つ。PR の「やってないこと」は実際の差分と照合し、単に予定を書き写さない。
5. 最初のテスト追加と同じ PR で GitHub Actions を導入する。その PR 以降は Actions の成功とレビューを取り込み条件にする。リファクタリング中は各 PR の取り込み後にもテストを実行し、問題が出たらその PR 単位で戻せる状態を保つ。実 DB の migration や本番設定変更は別 PR・別手順として扱う。
6. 作業中は移動前の特性テスト、検証済みの抽出・接続変更、比較スクリプトと記録等の区切りで定期的にコミットする。コミット数を固定することより、元の挙動と完成した差分をレビュー・revert できることを優先する。

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

- `master` の保護ルールと既存の未取り込み PR。GitHub Actionsは導入済みで、master向けPRとmasterへのpushでPython 3.11の全テストを実行する。
- API 契約を変える個別 Issue に限り、フロントエンドが呼ぶ URL・メソッドと参照するレスポンス項目を確認し、必要なら両リポジトリのリリース順を決める。構造変更だけの PR では API 契約を維持するため、互換期間は設定しない。
- ローカルとGitHub Actionsの一時SQLite・外部通信隔離を確認する。#12〜#52のPython 3.12.14は当時の記録であり、#53ではローカルもPython 3.11.16を用意した。Dockerfileに合わせたPython 3.11を基本とし、異なる版や制約は該当検証記録に残す。
- #43〜#53 の依存先の取り込みを確認する。#18〜#27 は構造変更の完了後に着手し、#53 で既存 Issue の前提・計画書・実コードの整合を確認する。
- 本番 DB の migration 履歴と Cloud Tasks の認証／再試行設定。構造変更では本番データを書き換えず、挙動修正の Issue で必要性を判断する。
