# Issue #53: テスト配置と構造リファクタリングの完了監査

計画書の順10-11。PR #64のマージを確認し、最新の `origin/master`
(`23dbc5bc8acbc070bbfdacc63626e45a55c0e184`) から
`test/53-test-layout` を作成した。#43〜#52はclosed、PR #55〜#64はマージ済み。
着手時の未取り込みPRはなく、masterのブランチ保護は無効。
本PRのマージで#43〜#53の11件の構造工程を完了とし、その後に#18〜#27へ進む。

## テスト分類と移動

既存31モジュールのうち15をapi、16をintegrationへ移した。
shared-helper契約の文字数テスト2関数（19パラメータケース）だけをunitへコピーした。
decorator・コメント・文字列・本体・期待値は元ソースをそのまま使い、純粋関数化しない。
保存型集計はDBを使用するためintegration、HTTP/CLIや画像等を含む混合ファイルも
integrationとした。APIテストはHTTP契約を中心にDB副作用や失敗境界も確認する。

| 分類 | ファイル数 | ケース数 | 内容 |
| --- | --- | --- | --- |
| unit | 1 | 19 | weighted lengthの入力と従来の例外 |
| api | 15 | 479 | HTTP/session/権限/期間/JSONと付随するDB副作用 |
| integration | 16 | 147 | 起動/import/factory/WSGI/CLI、model/schema、保存型集計・外部境界と複数経路 |
| 合計 | 32 | 645 | 分割でファイルは1増加、ケース数は不変 |

unitでも共通conftestの安全なアプリ初期化は読み込むが、計算ケースにDB/HTTP fixtureは不要。
既存の `tests/conftest.py` は全文不変。環境変数を公開app参照前に設定し、一時SQLite・
固定時刻・外部fake・ネットワーク拒否を全分類で共有する。fixtureを複製しない。
testsと3分類の__init__.pyはpackageを識別するdocstringだけで、初期化処理は持たない。

### 全ファイル対応表

| 移動前 | 移動後 |
| --- | --- |
| tests/test_api_access.py | tests/api/test_api_access.py |
| tests/test_api_activity.py | tests/api/test_api_activity.py |
| tests/test_application_factory_contract.py | tests/integration/test_application_factory_contract.py |
| tests/test_auth_characterization.py | tests/api/test_auth_characterization.py |
| tests/test_blueprint_contract.py | tests/api/test_blueprint_contract.py |
| tests/test_bootstrap_contract.py | tests/integration/test_bootstrap_contract.py |
| tests/test_comment_service_contract.py | tests/api/test_comment_service_contract.py |
| tests/test_contest_jobs.py | tests/integration/test_contest_jobs.py |
| tests/test_contest_lifecycle_contract.py | tests/integration/test_contest_lifecycle_contract.py |
| tests/test_contest_post_profile_contract.py | tests/api/test_contest_post_profile_contract.py |
| tests/test_contest_post_query_service_contract.py | tests/api/test_contest_post_query_service_contract.py |
| tests/test_contest_query_service_contract.py | tests/api/test_contest_query_service_contract.py |
| tests/test_external_boundaries.py | tests/integration/test_external_boundaries.py |
| tests/test_interaction_service_contract.py | tests/api/test_interaction_service_contract.py |
| tests/test_model_contract.py | tests/integration/test_model_contract.py |
| tests/test_news_service_contract.py | tests/api/test_news_service_contract.py |
| tests/test_notification_stats_contract.py | tests/integration/test_notification_stats_contract.py |
| tests/test_package_alias_contract.py | tests/integration/test_package_alias_contract.py |
| tests/test_package_entry_contract.py | tests/integration/test_package_entry_contract.py |
| tests/test_post_service_contract.py | tests/api/test_post_service_contract.py |
| tests/test_post_vote_effects.py | tests/integration/test_post_vote_effects.py |
| tests/test_profile_service_contract.py | tests/api/test_profile_service_contract.py |
| tests/test_results_service_contract.py | tests/integration/test_results_service_contract.py |
| tests/test_routes.py | tests/integration/test_routes.py |
| tests/test_scoring.py | tests/integration/test_scoring.py |
| tests/test_scoring_characterization.py | tests/integration/test_scoring_characterization.py |
| tests/test_shared_helper_contract.py | tests/integration/test_shared_helper_contract.py |
| tests/test_tasks_cli_contract.py | tests/integration/test_tasks_cli_contract.py |
| tests/test_user_account_service_contract.py | tests/api/test_user_account_service_contract.py |
| tests/test_voting_results_interactions_contract.py | tests/api/test_voting_results_interactions_contract.py |
| tests/test_voting_service_contract.py | tests/api/test_voting_service_contract.py |
| tests/test_shared_helper_contract.py: weighted text / truthy non-stringの2関数 | tests/unit/test_text_contract.py |
| tests/fixtures/url_map.json | tests/snapshots/url_map.json |
| tests/fixtures/model_schema.sql | tests/snapshots/model_schema.sql |
| tests/fixtures/model_relationships.json | tests/snapshots/model_relationships.json |

### 変更した参照だけ

- bootstrap/model契約のsnapshot参照2箇所:
  `Path(__file__).parent / "fixtures"` → `Path(__file__).parents[1] / "snapshots"`。
- package entry/alias契約のrepository ROOT参照2箇所:
  `Path(__file__).resolve().parents[1]` → `parents[2]`。
- alias契約の共有subprocess helperのimport1箇所:
  `tests.test_package_entry_contract` → `tests.integration.test_package_entry_contract`。
- url_map.json、model_schema.sql、model_relationships.jsonは
  `tests/fixtures/` → `tests/snapshots/`へ内容を変えずに移動。
- 文字数テストの2関数はASTのdecorator開始〜end_linenoで元ソースを切り出す。
  unitに必要なpytest/app importは同じlocal名で用意し、integration側から同じ範囲だけを除く。

これ以外のテスト本体・パラメータ・期待値・fake接続は変えず、削除・skip・新規ケースはない。
API・アプリ本体・旧互換入口・schema/migrations・requirements・Dockerfile・CIは基準と一致する。
GitHub Actionsの既存 `python -m pytest -q` は新配置を再帰収集するためworkflow変更は不要。

## 機械比較・収集比較

移動前の収集645件をPython 3.11.16で記録し、移動前の成功と対応表を最初のコミット
`198f89f25c9b3cd04607cbd5d0aa4a66a40a76ce` に保存した。
`issue-53-collection-baseline.json` に全parametrized node IDのhashと元ファイルごとの件数を残す。
移動先から元ファイルへの対応とunitの元の関数名でIDを正規化し、全体hashと各件数を照合する。
単に合計が同じだけでは成功としない。基準hashは
`a1c953ebde87f55a0a32e8c88b23396f500b76945032bfdb65264c5e7d32a4b1`。

`extract_issue_53.py` は固定SHAから全文コピーし、上の5箇所だけを置換する。
2つのunit関数もdecoratorを含むソース行の切り出しで、ast.unparseは使用しない。
通常実行で39ファイルを全文再現して比較し、旧31テストファイルと3 snapshotの削除を確認する。
`verify_issue_53_extraction.py` は抽出scriptに依存しない逆置換・AST比較で
全モジュールと切り出した2関数の全文/ASTを確認する。その他の基準ファイルはGitの
改行filterを適用したblob比較で確認し、アプリや歴史的scriptの変更を許可しない。
新規監査scriptは下記の構造をASTから読み取るもので、アプリを実行・変更しない。

```powershell
$pythonExe = ".\.venv\issue53-env\Scripts\python.exe"
& $pythonExe docs/refactor/extract_issue_53.py
& $pythonExe docs/refactor/verify_issue_53_extraction.py
& $pythonExe docs/refactor/check_issue_53_collection.py
& $pythonExe docs/refactor/audit_issue_53_structure.py
& $pythonExe -m pytest -q -p no:cacheprovider --disable-warnings --tb=short --basetemp=.venv/issue53-pytest-final
git diff --check origin/master HEAD
```

通常の仮想環境作成・分類別実行・歴史的検証の扱いは [tests/README.md](../../tests/README.md) を参照。

## #43〜#53の完了監査

| Issue | 取り込みPR | 完了commit | 現在の本体・担当 |
| --- | --- | --- | --- |
| #43 | #55 | b471c187e74b0ae3bd6ee41ab9eb3179db02fbe9 | services/comments: 一覧・追加・変更・削除とカウンタ/通知接続 |
| #44 | #56 | 4f6f70c05b3455f80927cbedc9979e58bda23248 | services/interactions: いいね/ブックマークと既存IntegrityError経路 |
| #45 | #57 | be9957eaaf83721ab65db013724949cf4a1937fb | services/contests: 公開/詳細/管理一覧、従来のcache |
| #46 | #58 | b523da12e4d7650329b3e21d217578122ed79221 | services/contest_posts: 大会別投稿と閲覧者情報 |
| #47 | #59 | 52f1ad79ea8d67d717fbdbe6d4f486794d4448da | services/profile: 投稿/交流/結果を組み合わせた表示データ |
| #48 | #60 | 5708ab6431b63a541aa256cb5feb980d2aa167ec | services/news: 取得/追加/削除とID/URL解析 |
| #49 | #61 | 46d312ee22f1990e6ab194c26f8ba941621f18e7 | services/users: 検索/ページング/統計/退会。account/core/users routeを配置 |
| #50 | #62 | 2c69378a995c27c7e2d999e56560a7d36426fc9f | runtime_dependencies、services/text、integrations/images: 共通helper/logger/schedulerの遅延接続 |
| #51 | #63 | 0c71ecf9780dc75e5fa60e4b5f255a6bb77b0b59 | factory: 初期化・15 Blueprint/CLI登録。既定appのURL map/command走査による不足補完を除去 |
| #52 | #64 | 23dbc5bc8acbc070bbfdacc63626e45a55c0e184 | 58実装をapp/配下へ統一、旧importは薄いalias、共有dbと10モデル |
| #53 | 本PR | 本PRのhead | テスト分類、全体監査、計画/手順と#18〜#27の前提の整合 |

上記の本体パスはすべて `app/` 配下。#12〜#17で先に抽出したauth/posts/voting/results/
contest_lifecycle/notifications/user_statsとintegrationも同じ配置に到達した。

### 責務・依存・互換入口

- 59 canonical module、141の明示的import依存をASTで確認。明示的な循環と
  services→routes依存はない。遅延importも検査し、実行時のcold import/alias/factory契約を併用する。
- 35個の一意なroute handlerは15 Blueprintに所属する。HTTP/form/JSON/session入力、
  service呼出し、jsonify/redirect/HTTP応答の組立を担当する。routeにmodelの.queryや
  DB追加/削除/commitはなく、元のrollback例外境界だけを保持する。
- accountのme/logoutとcoreのトップはsession表示・消去・HTTP応答だけであり、
  DB業務処理を新たにserviceへ移す必要はない。認可や表示の重複の共通化は#18/#19で扱う。
- serviceは既存の取得・判定・表示データ・DB更新・画像/通知/予定処理を調整する。
  API・CLIの例外境界、sessionや環境設定参照、単独生成/キャッシュ解決の時点を引き継ぐ。
  純粋serviceへの再設計やトランザクションの整理はこの工程の完了条件に含めない。
- SQLAlchemy/Migrate/Limiterの生成箇所はextensionsに各1箇所、Flask生成はfactoryに1箇所。
  factoryは明示的に複数appを生成できるが、既定app/直接起動の追加生成やモデル二重定義はない。
  10モデルの共有db/metadata、route/CLI登録順と同一性は実行テストで確認。
- 旧models/blueprints/CLIとflat moduleはcanonical moduleの同一オブジェクトを再公開する。
  旧services/integrations rootは状態を持たず、childごとの遅延aliasでcache/fakeを共有する。
  理由と全58実装の対応表は [#52記録](issue-52-verification.md) に保持する。
- #52の公開adapterを変更していない。裸のimport appでは起動せず、最初の公開runtime属性
  参照で初期化する既存の調整を引き継ぐ。WSGI app:app、from-import、Flask CLI、
  直接app.py起動、追跡対象sync_comment_counts.pyの入口を検証する。
  static/open_resource/instance基準とUPLOAD_FOLDER、初期化順/回数・loggerを保持する。

## 検証結果と環境

- 移動前の全件: **645 passed, 369 warnings**（Python 3.11.16、83.52秒）。
  最初の実行では644件成功・1件がsandbox TEMPのmkdirでエラーになったため、
  `--basetemp=.venv/issue53-pytest-baseline` を指定して全件を再確認した。テストは変更していない。
- 移動後の全件: **645 passed, 369 warnings**（同環境、86.79秒）。削除/skip/新規ケースなし。
- 収集比較: **645 normalized node IDsと全31元ファイルの件数が完全一致**。
- 39ファイルの全文再現、独立ソース/AST・scope比較、構造監査、git diff --checkに成功。
- URL map: 35 route + staticが既存snapshotと一致。methods/endpoint/handlerと
  CLI名process-contests/update-user-stats/db、factoryごとの登録順・callback同一性を保持。
- 10モデルのregistry・metadata/DDL・制約・リレーションは不変。一時SQLite基準schemaの
  Alembic compare_metadataの差分はゼロ。
- WSGI/Flask CLIのapp:app/app:create_app、HTTP /api/me、fakeによる直接起動の
  db.create_all→print→serverとPORT/host/debug、補助スクリプトimportを確認。
- 冷たいcomponent import、旧moduleとcanonicalの同一性、cache共有、初期化失敗後の再試行と
  並行初回factory参照、画像ディレクトリ作成1回・元のリソースパスを確認。
- GitHub ActionsのPython 3.11は本PRで実行し、結果をPR本文に記録する。

Python 3.11.16とrequirements.txtの依存をGit管理外の `.venv/issue53-runtime` /
`.venv/issue53-env` に用意した。テスト環境変数・一時SQLite・外部fakeとsocket接続拒否を共有。
本番DB・実外部サービス・migration・本番設定は変更しない。WindowsのためGunicornの
実プロセスは起動せず、入口解決とWSGI/fake直接起動で確認する。PostgreSQL固有の挙動を
今回のSQLite契約と同一と主張せず、必要な検証/修正は後続Issueで扱う。

## 歴史的比較と次の工程

#52の独立比較を移動前checkoutでも再実行し、58実装の全文/AST・互換adapterの一致を確認した。
#3〜#52の比較script/記録はそれぞれの抽出完了時点を対象とする歴史的資料として変更しない。
上表の完了commitを別checkoutして再検証できる。古いscriptの旧パスや当時のケース数を
現在の全体ゲートと混同しない。#53のscriptも本Issueの固定基準を対象とし、以後の
意図した変更はそのIssueで新しい再現テスト・基準・記録を作る。

#18〜#27は目的・やらないこと・受け入れ条件・state/labelを保持し、
前提を#53のPRマージ後へ更新する。現在のcanonical調査対象とapi/integrationの特性テスト、
共通fixture/snapshotの参照を追加する。変更前/後の本文を
[issue-53-followup-issues.json](issue-53-followup-issues.json) に保存した。
権限/期間、整形、例外/入力/トランザクション、Tasks認証、OAuthログ、他大会投票、
画像/削除の整合性の改善はここでは実装せず、当該Issueの再現テストと意図した変更に分離する。

## コミットと戻し方

1. 移動前645ケースの収集記録・比較と配置対応を保存。
2. 検証済みの機械移動、必要な参照調整、再現/独立比較scriptとテスト実行手順を保存。
3. 計画・構造監査・検証記録と後続Issueの更新本文を保存。

やってないこと: アプリ本体・API/CLI・SQL・認証・時刻・副作用・例外・commit/rollback・
schema/migration・本番設定・frontend・requirements/CIの変更。分類のためのロジック再設計。
アプリのデプロイ順やデータ移行は不要。PRをまとめてrevertすればテスト配置とドキュメントを戻せる。
GitHubのIssue本文更新はGitのrevertとは別なので、必要なら保存したbefore_bodyへ復元する。
