# netatwi-backend リファクタリング計画

## 目的と対象

`netatwi-backend` の保守性と検証可能性を上げる。対象はバックエンドの Flask アプリ、SQLAlchemy モデル、バッチ／外部サービスとの接続、テストである。フロントエンドは別リポジトリとして扱い、バックエンドの API 契約を先に固定する。

この計画では **(1) 現行動作の記録とテスト、(2) ファイルの移動・分割、(3) services 層への責務の移動と配置統一、(4) 重大なバグの修正、(5) 移行用の互換処理を撤去する構成整理、(6) 残りのbehavior系改善** を進める。(1)〜(3)は順1〜10で完了した。重大なバグ修正を、追加の構成整理や一般的な品質改善の完了待ちにしない。

ファイル分割と業務ロジック改善は同じ PR に入れない。構造変更 PR では URL、HTTP メソッド、ステータス、JSON のキーと型、認証条件、DB スキーマ、時刻・スコア計算、外部サービスへの副作用を維持する。ただし、順12の構成整理では、旧import・endpoint名・WSGI入口・初期化時点を意図して変更し、アプリ間の状態共有とimport順依存を解消する。これらの許可する変更と検証条件は後述する。業務処理の不具合は、再現テストを伴う別 Issue／PR で修正する。

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

## 現在の進捗と次の工程（2026-10-06 更新）

- #3〜#17に続き、#43〜#52／PR #55〜#64を取り込み済み。コメント、交流、大会・投稿・プロフィール・ニュース・ユーザーの取得／更新と退会処理をserviceへ抽出し、全35 routeをBlueprintへ移した。
- #50でservicesからBlueprintへの共通依存を解消し、#51でfactory・登録処理を集約した。#52で58実装を `app/` 配下へ配置し、既存全テスト645件がローカル・GitHub Actionsで成功した。詳細は [#52検証記録](issue-52-verification.md) を参照する。
- #53／PR #65を取り込み済み。テストをunit/api/integrationへ配置し、同じ645ケース・snapshot・fixture・fakeを維持して全体監査を完了した。アプリ本体は#52の実装を保持した。[#53検証記録](issue-53-verification.md) と [実行手順](../../tests/README.md) が順10完了時点の記録である。
- #43〜#53の11件を含む順1〜10は完了した。旧import・endpoint名・runtime再公開の維持は、当時の受け入れ条件だった。これを撤去する今回の4件は、完了済み#50〜#53の後続工程として扱い、過去の完了条件を遡って変更しない。
- GitHubの未完了Issueは、既存#18〜#27と今回作成した#67〜#72の計16件。構成整理4件は#67〜#70、独立したバグ2件は#71・#72として登録済み。既存#18〜#27にも実施順と再現条件を補足した。本計画と調査資料の更新は [PR #66](https://github.com/Megane14916/netatwi-backend/pull/66) でレビューする。
- 次の推奨順は、**順11:重大なバグ修正 → 順12:構成整理4件 → 順13:#18 → #21 → #22の残り → #20 → #19**。これは優先順位と推奨順であり、すべてを厳密な直列依存にはしない。既存Issueの前提を一律に「構成整理4件の完了待ち」へ変更しない。
- 既存の権限判定の重複、route側のrollback・例外境界、OAuthログ、投票対象の大会所属、画像・削除の整合性は構造工程で改善していない。これらを構造完了と混同しない。

## 順10完了時点の構成

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

各行を原則1 Issueとし、各PR・ブランチはひとつの目的に絞る。大きくなった場合や重大な問題を先行修正する場合は、同じIssue内をAPI・処理経路ごとの複数PRに分け、残件を記録する。Issue には予定する対象外作業を **「やらないこと」**、PR には完成した差分に含まれない作業を **「やってないこと」** として記載する。PR には変更範囲と検証結果も必ず記載する。

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
| 11 | 重大なバグ修正を先行 | #23〜#27と#71・#72を影響に応じて修正する。結果保存失敗を処理済みにする問題は#22の最初のPRで先に直す。#21等の対象でも重大な問題なら先行できる。 | 構成整理と混ぜない。修正前に失敗する再現テストを用意し、運用設定・API・データへの影響を記録する。低優先度の残件を理由に後続工程を一律に止めない。 |
| 12 | 移行用互換処理の撤去とFlask構成の整理 | 12-1:旧import alias、12-2:標準Blueprint、12-3:runtime bridgeとアプリ固有の状態、12-4:通常factoryと起動入口の順に整理する。詳細は後述する。 | 業務ロジック・DB schemaを変えない。内部互換契約・初期化時点・状態分離の意図した変更は明記し、段階ごとに検証する。 |
| 13 | 残りのbehavior系改善 | 推奨順は#18 → #21 → #22の残り → #20 → #19。経路ごとに判定、入力、更新単位、例外、整形を改善する。型・lint等の追加作業は別Issueで対象を決める。 | 構成整理を混ぜない。各修正の再現テストとAPI契約への影響を記録する。独立した対象は推奨順に縛られず進められる。 |

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

#43〜#52は上の順にPR #55〜#64で、#53はPR #65でマージ済み。順10のテスト配置と完了監査は完了した。
各完了commit・担当service・現在の契約テストは [#53の全体監査](issue-53-verification.md) に記録する。

### 順1〜10の構造リファクタリングの完了条件（当時の互換維持を含む）

- route は HTTP／セッション入力、service 呼び出し、応答変換を担当し、対象の取得・判断・更新処理を service へ移している。
- service が route モジュールを import せず、循環 import・処理本体の二重定義・db／モデル／app の二重生成・route／CLI の二重登録がない。
- 本体は `app/models/`・`app/routes/`・`app/services/`・`app/integrations/`・`app/cli/` と設定・拡張機能・共通モジュールへ配置され、`app.py` は直接起動と必要な互換入口に絞られている。旧配置に必要な再公開が残る場合は、その対象と理由を記録する。
- `tests/unit/`・`tests/api/`・`tests/integration/` の収集・共有 fixture・snapshot・fake が機能する。分類のためにテストの期待値を変更したり、削除・skip したりしない。
- ソース・AST 比較と全テスト、URL map、WSGI・CLI・直接起動・補助スクリプトの import、モデル契約・Alembic 差分ゼロを確認し、#53 で記録する。API・SQL・判定・副作用・commit／rollback・例外境界の改善はこの工程に含めない。

## 順11: 重大なバグ修正と既存Issueの使い分け

既存Issueで扱える問題には再現条件と修正対象を補足し、同じ修正を新規Issueに重複登録しない。#53の完了という既存の前提は満たされている。セキュリティ・データ欠損・結果保存の失敗を、順12や一般的な共通化の完了待ちにしない。

| 対象 | 使用するIssue | 補足する内容・修正後の確認 |
| --- | --- | --- |
| Cloud Tasksの呼出元認証 | [#23](https://github.com/Megane14916/netatwi-backend/issues/23) | 本番のCloud Run／Tasks保護設定と照合し、未認証の直接呼出しを拒否する。正規taskと再試行を維持する。 |
| OAuth経路の機密ログ | [#24](https://github.com/Megane14916/netatwi-backend/issues/24) | authだけでなく`app/hooks.py`のheaders・Cookie・sessionの出力も対象にする。秘密値を含めず成功・失敗経路を検証する。 |
| 不正な投票・審査員賞 | [#25](https://github.com/Megane14916/netatwi-backend/issues/25) | 大会所属に加え、投稿の存在・自己投稿・審査員賞だけの入力を検証する。不正入力で既存票やカウンタが変わらないことを確認する。 |
| 画像とDB更新の不整合 | [#26](https://github.com/Megane14916/netatwi-backend/issues/26) | DB commit前の画像削除による欠損参照、保存後のDB失敗による不要画像を再現し、削除順序・補償・再試行を対象経路ごとに決める。 |
| 投稿・大会削除時の参照整合性 | [#27](https://github.com/Megane14916/netatwi-backend/issues/27) | bulk deleteでORM cascadeが動かない経路を含め、外部キー有効のDBで関連行・rollbackを確認する。上記の重大な問題より優先度が低ければ後続工程と独立して進める。 |
| 結果保存失敗でも処理済みになる問題 | [#22](https://github.com/Megane14916/netatwi-backend/issues/22)の先行PR | `app/services/results.py`で保存失敗が握りつぶされ、ライフサイクル側が通知フラグを処理済みにする経路を修正する。結果なし・成功応答・再試行不可の状態を防ぎ、taskとCLIの失敗・再試行を検証する。必要な例外伝播もこのPRで直し、#20を待たない。 |
| 投稿文字数・画像必須条件・画像枚数 | [#21](https://github.com/Megane14916/netatwi-backend/issues/21) | 作成・編集の実際の保存画像と文字数の検証を補足する。入力改善全体は順13で扱い、影響が大きいケースは先行できる。 |

追加のバグ修正は次の2件として登録済み。構成整理4件とは別Issue／PRで扱う。

- **[#71 投稿画像の保持・削除で所有関係を検証し、他人の画像削除を防ぐ](https://github.com/Megane14916/netatwi-backend/issues/71)**: `app/services/posts.py`の`kept_images`へ他人の画像URLを指定し、次の編集で削除できる経路を閉じる。保持できる画像を対象投稿の既存画像に限定し、削除対象の所有関係も検証する。#26のDB失敗時の整合性とは別の問題である。
- **[#72 退会済みユーザーの既存セッションからの操作を拒否する](https://github.com/Megane14916/netatwi-backend/issues/72)**: 退会時に現在のsessionだけを消しても、別sessionのuser_idが有効な経路を修正する。DB上のユーザー状態に基づいて保護された操作を拒否し、複数sessionで再現・検証する。後続#18の共通化では、この修正済みの条件を維持する。

ひとつのIssueを複数PRで進める場合は残件を明記する。#22の結果保存問題など、先行PRが一部分だけを解決した時点ではIssue全体をcloseしない。例外処理は#20、入力検証は#21などの関連先を記載するが、修正の担当Issueは一つにする。

## 順12: 移行用互換処理を撤去する構成整理4件

### 目的・依存・許可する変更

今回の目的は、旧monolithic app.pyの互換性を保つために残した仕組みを撤去し、**通常のBlueprintと明示的なApplication Factoryを中心にすること**である。`app/__init__.py`だけを短くする作業ではない。呼出元・設定・fake・状態・起動入口まで移行して初めて完了とする。

調査の基準は順10完了時のmaster `ef81f1b1e33193ceeaf6cfc292717a2b5baddbd5`。根拠・使用箇所・隔離実験は [構成単純化の調査](factory-simplification-investigation.md) を参照する。標準Blueprintの差し替え実験や旧root import禁止実験は移行可能性の根拠であり、実装完了後の全体テストを代替しない。

以下の12-1〜12-4は計画上の工程番号で、対応するGitHub Issueは#67〜#70である。完了済み#50・#51・#52・#53の後続として登録し、作業範囲・受け入れ条件・依存関係を各Issueへ反映した。

| 順 | Issue | 依存・切り分け |
| --- | --- | --- |
| 12-1 | [#67 未使用の旧import aliasを撤去し、app配下のimportへ統一する](https://github.com/Megane14916/netatwi-backend/issues/67) | #53完了後。root `app`のruntime再公開・遅延初期化は12-4まで維持する。 |
| 12-2 | [#68 LegacyEndpointBlueprintを標準Blueprintへ置き換える](https://github.com/Megane14916/netatwi-backend/issues/68) | 原則#67の後。endpoint名の変更をこの工程に限定する。 |
| 12-3 | [#69 runtime互換bridgeを撤去し、依存と状態をアプリ単位に整理する](https://github.com/Megane14916/netatwi-backend/issues/69) | 原則#68の後。旧helperへの依存とfakeの接続を先に移し、#70がnamespaceなしで動ける状態にする。 |
| 12-4 | [#70 create_app中心の構成へ移行し、packageの遅延初期化を撤去する](https://github.com/Megane14916/netatwi-backend/issues/70) | #69完了後。factory、package公開、WSGI・CLI・補助scriptを同時に整合させる。 |

順1〜10と異なり、次の内部契約を意図して変更する。PRごとに実際に変更した契約を記載する。

- 旧`blueprints.*`／`services.*`／`models.*`等のimportを廃止し、canonicalな`app.*`へ移す。
- endpoint名にBlueprint接頭辞を付ける。HTTP URL・methodは変えない。
- `from app import app, db, helper`等の旧再公開と、`app.save_file`等へのmonkeypatchを廃止する。
- package属性の取得で既定appを生成する挙動を廃止する。設定検証・アプリ初期化は明示的な`create_app`で行う。
- WSGI入口を`app:app`から`wsgi:app`へ移し、CLI・scriptもfactoryを明示して使う。
- アプリ固有の設定・cache・fakeを分離し、OAuth資格情報のimport順依存を解消する。これは初期化・状態管理の意図した修正であり、変更前に失敗する再現テストを用意する。

業務ロジックの計算式、順位、進出条件、期間判定、SQLの意味、通知条件、画像検証・削除順序、commit／rollback・例外境界は変更しない。先行バグ修正後の最新masterを基準にし、修正済みの契約を維持する。構成整理中に別のバグを見つけた場合は、担当Issueを明記して別PRで修正する。

### 12-1: 旧import aliasの撤去

**重要点: Git追跡中のアプリだけでなく、Git管理外の補助スクリプトと実際の運用入口を確認してから削除する。** `sys.modules`のalias実装を単に消すだけでは不十分である。

やること:

- `blueprints/`、`services/`、`integrations/`、`cli/`と、`app_config.py`・`app_extensions.py`・`app_factory.py`・`app_hooks.py`・`runtime_dependencies.py`の使用箇所を洗い出す。直接importに加え、動的import・テスト・起動設定を確認する。
- 呼出元を`app.routes`・`app.services`・`app.integrations`・`app.cli`・`app.config`・`app.extensions`等へ移し、未使用になったaliasファイルと互換namespaceを削除する。
- `models/`は`generate_dummy_data.py`、`generate_dummy_gp_result.py`、`scripts/sync_comment_count.py`、`scripts/recalculate_contest_stats.py`の旧importも先に移してから撤去する。Git管理外の変更はCIやPR差分に出ないため、対象・変更手順を記録し、運用側への適用まで確認する。
- aliasの同一オブジェクト性だけを要求するテストは、canonical moduleのcold import・実際の動作・fakeの差し替えを確認するテストへ置換する。業務契約を確認するケースを失わない。

対象外:

- root `app`のruntime再公開・遅延初期化、`LegacyEndpointBlueprint`、helper bridgeはこのIssueでは撤去しない。
- 歴史的な`docs/refactor/`の抽出・比較scriptを現在のパスへ書き換えない。`patch.py`等の旧monolith書換えscriptを現在対応として実行しない。データ更新scriptの検証で本番データを操作しない。

受け入れ条件:

- 削除対象について、アプリ・テスト・現在使用するscript・運用入口が旧importへ依存していない。残す互換名が必要なら具体的な利用者・理由・撤去工程を記録し、未確認のまま削除しない。
- canonical importのcold起動と全体テストが成功し、db・model・実装が二重に生成されない。
- 削除ファイル、旧→新import対応、Git管理外scriptへの適用手順がレビューできる。

### 12-2: 標準Blueprintへの置換

**重要点: 維持するのはHTTP契約であり、旧endpoint名の維持条件はここで明示的に解除する。** 現在の`app/routes/legacy.py`は標準の登録処理を迂回して接頭辞のないendpointを登録している。

やること:

- route定義を通常の`flask.Blueprint`へ切り替え、`LegacyEndpointBlueprint`と`legacy.py`を削除する。旧endpointの互換aliasを二重登録しない。
- `url_for`・`request.endpoint`・`view_functions`・動的参照を再確認する。例えば`get_current_user`は`account.get_current_user`へ変更するが、`/api/me`は維持する。
- URL map snapshotと登録テストをnamespaced endpointへ更新する。変更前後のURL／methodとendpoint名の対応表を記録する。

対象外:

- URL prefix・API URL・HTTP応答・認証条件の変更、routeの再分類、業務処理の修正を含めない。

受け入れ条件:

- 全35 APIとstaticのURL・methodが同等で、endpointの変更は意図した接頭辞だけである。routeの欠落・二重登録がない。
- APIの正常・異常応答、`url_for`、`request.blueprint`、共通hook、CORS、明示的・既定のLimiter制限を確認する。審査員認証の5/min制限も実際の連続リクエストで確認する。
- 全体テストが成功する。旧endpoint名を要求するテストは新契約へ置換し、skipや一括snapshot更新だけで変更を通さない。

### 12-3: runtime bridge・依存・アプリ固有の状態の整理

**重要点: 関数の再公開だけでなく、namespaceをclosureで参照するcallbackとテストfakeも移す。** 同じmodule内の共有変数へ移し直すだけでは、複数appの設定・状態の混在が残る。

| 現在の参照 | 移行先 |
| --- | --- |
| 文字数計算 | `app.services.text`の純粋関数を直接import。app contextを要求しない。 |
| 結果生成・保存済み結果取得 | `app.services.results`を直接呼ぶ。既存のDB・例外・副作用の境界を維持する。 |
| 画像設定・保存・削除・R2 client | `app.integrations.images`とアプリごとのconfig／integration。clientは必要時に生成し、fakeは実際の呼出先へ接続する。 |
| scheduler・Cloud Tasks client | `app.integrations.cloud_tasks`。アプリ固有の設定に依存する接続・fakeはアプリ単位にする。 |
| route／serviceのlogger | request／CLIでは`current_app.logger`、その他は責務に応じたmodule loggerを使う。 |
| 大会一覧cache | `current_app.extensions`等にアプリ単位で保持する。期限・一覧分類・並び順は維持する。 |
| OAuth資格情報 | 設定読み込み後のアプリ設定から解決する。module import時の環境変数の値へ固定しない。 |

やること:

- `app/runtime_dependencies.py`を使うservice／routeを上記の依存へ移し、`legacy_route_helpers`とnamespace参照callbackを撤去する。不要になる`app/routes/dependencies.py`も削除する。
- `app.save_file`・`app.USE_R2`・`app.logger`等へのmonkeypatchを、integration・app config・アプリ単位のfakeへ変更する。どこを差し替えれば外部接続を隔離できるかを明確にする。
- `app.services.contests`のmodule global cache、既定appから共有される画像設定、`app.integrations.x_oauth`のimport時の資格情報を移行する。

対象外:

- 採点・順位・文字数の計算法、画像規則、通知条件、OAuthプロトコル、commit回数・失敗応答の変更を含めない。旧namespaceを別の巨大な汎用registryとして再実装しない。
- packageの全再公開とWSGI入口の最終切替は12-4で行う。12-3で不要になるbridgeへの再公開は、呼出元を移したうえで外す。

受け入れ条件:

- 異なるSQLite DBの2アプリで、2番目の大会一覧に1番目の大会が出ない。画像設定・frontend設定・外部fakeも、生成順・呼出順によらず各アプリの値を使う。
- OAuth moduleを設定読み込み前にimportしても、factory生成後のloginが正しい設定を使う。資格情報が文字列`None`等の不正な値へ固定されない。
- 純粋な文字数計算はapp contextなしで動作する。画像・Cloud Tasks・結果処理の実際の呼出先をfakeにでき、全体テストで通信隔離が維持される。
- runtime bridge・旧callbackに依存する呼出元がなく、循環importがない。入力・戻り値・HTTP／DB／外部副作用の契約が、許可した状態分離以外で変わらない。

### 12-4: 通常factory・package公開・起動入口への移行

**重要点: `create_app`を取得するために既定appを作らない。** 現在は`from app import create_app`でも`initialize_application(globals())`が設定なしの既定appを先に生成する。この初期化と約60のruntime名の公開をなくす。

やること:

- `app/factory.py`にトップレベルの`create_app(config=None)`を置く。設定読み込み、Flask生成、config反映、extensions初期化、モデル登録、アプリ固有の状態・integration、Blueprint・CLI・hookの登録を明示して返す。
- `app/__init__.py`を通常の`create_app`の再公開に絞り、`_RUNTIME_EXPORTS`・`RLock`・`__getattr__`・`__dir__`・`_publish_entry`・namespace injectionとnested factoryを撤去する。互換目的の`sys.modules`書換えを残さない。
- **dbは既存の`app.extensions.db`へ統一する。** `db = SQLAlchemy()`は既にここに1つあるため、新しい専用moduleの追加を必須にしない。modelsはextensionsのdbを参照し、services／routesもdbをmodels経由で取得しない。不要な`app/models/base.py`等の再公開を整理する。factoryごとにSQLAlchemyやモデルを再定義しない。
- `wsgi.py`で`app = create_app()`を作り、Dockerfile等のGunicorn入口を`wsgi:app`へ変更する。Flask CLIは`flask --app app:create_app ...`へ揃える。`app.py`は必要な`python app.py`用の薄い直接起動入口として扱い、生成したappをpackageへ注入しない。
- `sync_comment_counts.py`、Git管理外の`calc_result.py`等の`from app import app, db, helper`を、factory・`app.extensions.db`・担当serviceのimportと明示的なapp contextへ移す。残ったaliasや再公開があれば呼出元を移して撤去する。
- リポジトリ外のWSGI・ジョブ・運用scriptの入口も切替一覧に含める。入口・Docker設定・使用手順を同じリリースで整合させ、戻す場合も一緒に戻す。

対象外:

- DB schema・migration・既存データを変更しない。factory内で`create_all`やmigrationを自動実行しない。直接起動時の既存`create_all`を維持する場合は、直接起動入口だけに置く。
- `Flask(__name__)`への変更でstatic／open_resource／instance／uploadsの基準を移さない。保存場所・公開URLを維持する。

受け入れ条件:

- `import app`、`from app import create_app`、model／serviceのcold importが、app生成・設定の必須値検証・DB接続・外部接続を行わない。
- 必須の環境変数を設定せず、完全なconfigだけを渡して`create_app`が成功する。設定不足時の検証はfactory実行時に行い、先に既定appを生成しない。
- factoryを2回呼んでも、各appにroute・CLI・hook・extensionsが正しく登録される。アプリ間の状態が混ざらず、同じappへの二重登録やプロセス共通hookの重複がない。
- 単一dbと全10モデルのmetadata・テーブル・制約・リレーションを保持し、Alembic schema diffがゼロである。
- 新WSGI・Flask CLI・直接起動・補助scriptの入口、設定とstatic／instance／uploadsの位置を隔離環境で確認する。全体テストとCIが成功する。

### 順12完了後の構成と依存方向

```text
wsgi.py                   # 明示的に app = create_app() を生成するWSGI入口
app.py                    # 必要な場合だけ残す薄い直接起動入口
app/
  __init__.py             # create_appの通常の再公開だけ
  factory.py              # トップレベルのcreate_app、初期化・登録
  config.py
  extensions.py           # 単一の未初期化db・migrate・limiter
  hooks.py
  models/                 # extensions.dbを参照する全10モデル
  routes/                 # 標準Blueprint
  services/
  integrations/           # アプリの設定に基づく外部境界
  cli/
tests/                    # unit・api・integration、canonicalなfake接続
```

```text
models          -> extensions.db
services/routes -> extensions.db + models + 必要なservice/integration
factory         -> config, extensions, models, routes, CLI, hooks, integration初期化
WSGI/実行入口   -> create_app
```

`app/__init__.py`は原則として次の程度にする。importを軽くするために別の遅延初期化機構を追加せず、依存先のmodule自体をimport時にアプリ生成しない構成にする。

```python
from .factory import create_app

__all__ = ["create_app"]
```

4件共通の検証では、修正済みの業務契約を維持した全体テスト、35 APIのURL／method、HTTP／DB／外部副作用、起動・CLI、モデル契約・Alembic差分ゼロを確認する。互換実装だけを要求するテストは新しい契約の検証へ置換し、テスト件数を645へ機械的に固定しない。追加・置換・廃止したケースとその理由を記録する。

## 順13: 残りのbehavior系改善の推奨順

| 順 | Issue | 実装方針・この順にする理由 |
| --- | --- | --- |
| 13-1 | [#18 権限・期間判定の重複を整理する](https://github.com/Megane14916/netatwi-backend/issues/18) | 先行バグ修正で正しい条件を固めてから共通化する。退会済みユーザー・所有者・審査員・期間境界等の条件を意図せず変えない。 |
| 13-2 | [#21 入力検証を改善する](https://github.com/Megane14916/netatwi-backend/issues/21) | 判定の置き場所が整理された状態で、型・欠損・境界値をAPIごとに修正する。先行した投票・画像等の検証を重複実装しない。 |
| 13-3 | [#22 DB更新のトランザクション境界を改善する](https://github.com/Megane14916/netatwi-backend/issues/22)の残り | 検証失敗と更新処理を分けてから、commit・rollback・通知作成の単位を整理する。順11の結果保存修正を保持する。 |
| 13-4 | [#20 例外処理とログの品質を改善する](https://github.com/Megane14916/netatwi-backend/issues/20) | 更新単位が固まった後、例外の伝播・捕捉・HTTP応答・ログを揃える。#24の機密ログ修正を戻さない。 |
| 13-5 | [#19 APIレスポンス整形の重複を整理する](https://github.com/Megane14916/netatwi-backend/issues/19) | 正常・失敗系の挙動が落ち着いた後に、既存のキー・型・日時・公開条件を保って共通化する。 |

この順序は推奨であり、独立したAPI・処理は別々に進められる。#18と#21も一律の直列依存にはしない。#22の修正に必要な例外伝播・rollbackはそのPRで直し、#20の完了を待たない。Issue内を複数PRに分ける場合は、API・更新経路単位で目的と残件を明記する。

## 挙動を保つ service 抽出の手順（順1〜10の記録）

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
- **実行環境**: ローカルでは Dockerfile に合わせた Python 3.11 の仮想環境を作り、`requirements.txt` を入れて `python -m pytest -q` を実行する方法を基本とする。初期の隔離方式と順10完了時点のfixtureは、app import前にテスト用環境変数を設定し、一時SQLite DBを使う。追加appには`create_app`で設定を渡すが、設定だけでのcold起動は12-4で保証する。GitHub ActionsでもPython 3.11と一時SQLite DBを使い、毎PRで実行する。PostgreSQL固有の挙動やmigrationを検証する段階では、別途GitHub ActionsのPostgreSQL service containerを使うテストを追加する。
- **構造変更 PR の必須確認**: `git diff --check`、全体pytest、URL map、WSGI・CLI・直接起動・補助script、static／uploads／instanceの位置、全モデルのmetadata・Alembic schema diffを確認する。順1〜10の機械的移動には元ソース・AST比較と旧`app:app`等の互換性維持を適用する。順12では各工程の許可する変更を明記し、12-2のendpoint変更、12-3の状態分離・fake、12-4のcold factory・新`wsgi:app`を検証する。互換処理を撤去する工程に過去のAST完全一致や旧endpoint／入口の維持を要求しない。業務処理の入力・出力・DB／外部副作用の等価性と、拡張機能・モデル・routeの登録を確認する。
- **挙動変更 PR の必須確認**: 変更前に失敗する再現テスト、変更後の全件テスト、API・DB・運用への影響、必要な移行／ロールバック手順。品質ツールは最初に既存警告の範囲を記録し、以降は変更箇所から段階的に適用する。

現在の実行手順は [tests/README.md](../../tests/README.md)。順10完了時点ではunit 19・api 479・integration 147の
合計645ケースを共通conftestで収集した。これは検証基準の記録であり、後続工程でのケース追加・意図した契約の置換を禁止する件数ではない。保存型集計やHTTP/CLI混合テストをunit扱いせず、分類だけのためにfixture・期待値・アプリのロジックを変更しない。snapshotはtests/snapshotsに集約した。
GitHub Actionsの既存 `python -m pytest -q` は全分類を再帰的に収集する。順12の入口・fixture変更に応じてCI設定や実行手順の更新が必要なら、同じPRで整合させる。
#53のローカル検証はPython 3.11.16で行い、制限環境では `--basetemp` で専用のGit管理外領域を使う。

## Issue・ブランチ・PR の運用

1. バックエンド GitHub リポジトリに上表の Issue を作り、`test`、`structure`、`service`、`behavior` などのラベルと依存先を付ける。別リポジトリのフロントエンド変更が必要になった場合は、その Issue をフロントエンド側に作り、相互リンクする。
2. 取り込み先は `master` に統一し、各作業ブランチは最新の `master` から作る。`dev` を作業の起点や PR の取り込み先にしない。例: `test/123-isolated-fixtures`、`refactor/124-split-models`、`fix/125-vote-contest-check`。番号は実際の Issue 番号を使う。
3. 1ブランチ・1PRは1 Issue内のひとつの目的に絞る。Issueが複数PRにまたがる場合は残件と依存を明記する。積み重ねが必要な場合は依存PRを記載し、前段の取り込み後に取り込み先へ追従させる。構成整理と業務ロジックのバグ修正を混ぜない。順12で許可した内部契約・初期化・状態分離の変更は、その工程の目的として記録する。
4. PR説明には変更内容、**やってないこと**、影響するAPI／DB／外部サービス、テスト結果、残るリスク、必要なデプロイ順と戻し方を書く。Issue全体を完了させるPRだけ`Closes #番号`を使い、一部の先行修正は`Refs #番号`と残件を記載する。Issueは「やること／やらないこと／受け入れ条件」を持つ。PRの「やってないこと」は実際の差分と照合し、単に予定を書き写さない。
5. 最初のテスト追加と同じ PR で GitHub Actions を導入する。その PR 以降は Actions の成功とレビューを取り込み条件にする。リファクタリング中は各 PR の取り込み後にもテストを実行し、問題が出たらその PR 単位で戻せる状態を保つ。実 DB の migration や本番設定変更は別 PR・別手順として扱う。
6. 作業中は移動前の特性テスト、検証済みの抽出・接続変更、比較スクリプトと記録等の区切りで定期的にコミットする。コミット数を固定することより、元の挙動と完成した差分をレビュー・revert できることを優先する。

### Issue 記述例（順1〜10のAPI移動・旧endpoint維持）

```text
タイトル: 大会一覧 API を Blueprint に移動する
やること: GET /api/contests と関連フックの登録位置を移し、URL map と API 特性テストで同等性を確認する。
やらないこと: レスポンス形式、キャッシュ時間、集計方法、DB クエリ、エラー処理の仕様は変えない。
受け入れ条件: URL・メソッド・endpoint 名が同じで、対象テストと全体テストが通る。
```

### PR 記述例（順1〜10のAPI移動・旧入口維持）

```text
Closes #<Issue 番号>
変更内容: 大会一覧 route を contests Blueprint に移動した。
やってないこと: API 仕様変更、キャッシュ／SQL の改善、モデル変更は行っていない。
検証: pytest、URL map 比較、app:app 起動確認。
影響・戻し方: URL／DB 変更なし。この PR を revert して元の登録位置に戻せる。
```

## 着手前に確認する事項

- `master` の保護ルールと既存の未取り込み PR。GitHub Actionsは導入済みで、master向けPRとmasterへのpushでPython 3.11の全テストを実行する。
- API契約を変える個別Issueでは、フロントエンドが呼ぶURL・メソッドと参照するレスポンス項目を確認し、必要なら両リポジトリのリリース順を決める。順12ではHTTP契約を維持しつつ旧import・起動入口を変更するため、運用script・ジョブ・デプロイ設定の利用者と切替手順を確認する。互換期間を設ける場合は必要な対象だけに限定し、撤去条件を明記する。
- ローカルとGitHub Actionsの一時SQLite・外部通信隔離を確認する。#12〜#52のPython 3.12.14は当時の記録であり、#53ではローカルもPython 3.11.16を用意した。Dockerfileに合わせたPython 3.11を基本とし、異なる版や制約は該当検証記録に残す。
- 順1〜10と#53は完了済み。順11は重大なバグを先行し、順12は#67〜#70の依存、順13は各処理の実際の依存を確認する。#18〜#27の前提を一律に追加の構成整理待ちへ変えない。GitHub Issue・本計画・実コードの整合は、各実装PRで更新する。
- 本番 DB の migration 履歴と Cloud Tasks の認証／再試行設定。構造変更では本番データを書き換えず、挙動修正の Issue で必要性を判断する。
