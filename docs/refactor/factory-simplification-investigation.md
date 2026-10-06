# Flask構成・互換処理の単純化に関する調査

調査日: 2026-10-06。対象: master `ef81f1b1e33193ceeaf6cfc292717a2b5baddbd5`。
アプリ本体の変更・aliasの削除・デプロイは実施していない。

## 結論

通常のBlueprintとApplication Factoryを中心とした構成へ移行できる。
現在の特殊な処理は、旧app.pyの再公開名・endpoint名・monkeypatch先・直接起動と
importの同一性を維持するための移行用の仕組みであり、APIの業務処理が必要とする仕組みではない。

ただし、`app/__init__.py`だけを短くすると起動と補助スクリプトとテストが壊れる。
factoryのnamespace経由の依存解決、入口、test fake、アプリ固有の状態も一緒に移す必要がある。
HTTPのURL・method・応答・認証条件・DB構造・計算式・commit/rollbackの順序は維持する。

## 1. LegacyEndpointBlueprint

- `app/routes/legacy.py:6-25`はBlueprint.routeを上書きし、
  `state.app.add_url_rule`でendpoint名のBlueprint接頭辞を付けずに登録する。
- アプリ本体には旧endpointを使う`url_for()`、`request.endpoint`、`view_functions`参照がない。
  frontend/formにも今回のendpoint名を使う参照は見つからなかった。
- 旧endpoint名を要求する主な呼出元はテストとURL map snapshotである。
- 通常のBlueprintでは、例えば`get_current_user`が`account.get_current_user`になる。
  URL `/api/me`とHTTP methodは変わらない。
- 現在のoverrideはBlueprintのurl_prefix等をstateから適用する標準の登録処理も迂回している。
  将来Blueprint単位のprefix・hook等を利用する上でも通常の登録へ戻す方が自然。

**判断:** 通常のBlueprintへ置換し、`legacy.py`を削除できる。
旧endpointの別名を二重登録する必要は見つからなかった。
endpoint名の変更は内部契約の意図した変更として記録し、snapshotと登録テストを更新する。
構造工程で要求した「旧endpoint名を維持する」という条件は、今回の移行では変更する。

隔離実験で標準Blueprintを使用し、35 APIとstatic routeのURL/methodをsnapshotと照合した。
`url_for('account.get_current_user')`と`request.blueprint == 'account'`を確認した。
API/unitテストは497件成功、旧endpoint名を直接要求する1件を除外した。
審査員ログインの5/min制限も、6連続リクエストで `[401, 401, 401, 401, 401, 429]` を確認した。
これは調査用の差し替えであり、移行実装後の全体検証の代わりではない。

## 2. 旧import aliasの削除候補

Git追跡中のPythonをASTで確認した。歴史的な`docs/refactor/`の再現scriptを除き、
アプリ本体・補助スクリプト・テストに、alias実装の外から旧rootを直接importするコードはない。
動的な旧importは、主に互換性を検証するテストに残る。
`sys.modules`を書き換える互換ファイルは26件ある。

| 対象 | 現在の依存 | 削除条件 |
| --- | --- | --- |
| `blueprints/` | alias契約テスト | テストをcanonicalな`app.routes`へ変更して削除できる |
| `services/` | alias契約・cold importテスト | `app.services`のimport/動作を検証するテストへ置換して削除できる |
| `integrations/` | alias契約・fake共有のテスト | fakeを`app.integrations`へ接続して削除できる |
| `cli/` | alias契約・cold importテスト | CLI名と`app.cli`登録の検証を維持して削除できる |
| `app_config.py`, `app_extensions.py`, `app_factory.py`, `app_hooks.py`, `runtime_dependencies.py` | 旧importの互換テスト | canonicalモジュールを検証するテストへ変更して削除できる |
| `models/` | 互換テストに加え、Git管理外の補助スクリプト | 補助スクリプトのimportを先に移してから削除する |

旧rootのimportを禁止した隔離実験は626件成功した。
`test_package_alias_contract.py`の7件を対象外とし、
`test_package_entry_contract.py`の旧rootのcold importに関する12件を除外した。
この実験ではrootの`app`再公開とruntime bridgeは維持しているため、
factoryや再公開を削除する変更まで検証した結果ではない。

**Git管理外も移行対象にする必要がある。** 次のスクリプトが旧`models`をimportしている。

- `generate_dummy_data.py:3-4`
- `generate_dummy_gp_result.py:3-4`
- `scripts/sync_comment_count.py:7-8`
- `scripts/recalculate_contest_stats.py:9-10`

これらは`.gitignore`対象で、通常の`git ls-files`やCIだけでは検出できない。
`calc_result.py:1`は`from app import app, generate_contest_results`に依存するため、
packageの再公開を撤去する前に移行する。
追跡中の`sync_comment_counts.py:7`も`from app import app, db`を移す。
`patch.py`は旧monolithic app.pyを書き換える歴史的scriptで、import置換だけで現在対応にしない。
今回これらのデータ更新scriptは実行していない。

リポジトリ外の運用script・ジョブ設定については、この調査から利用がないとは断定できない。
切替時に実際のジョブ・起動設定で使用する入口を一覧化する。
歴史的な抽出/比較scriptは過去commitの資料なので、現在の配置に合わせて書き換えない。

## 3. app/__init__.pyとruntime bridge

### 現在の接続

`app/__init__.py:85-105`の`__getattr__`は、create_app等の取得でも
`initialize_application(globals())`を実行する。
`app/factory.py:85`が先に設定なしの既定アプリを生成し、その後にnested create_appを再公開する。

`initialize_application(namespace)`はモデル、Flask関数、時刻、helper、route関数まで
namespaceへ注入する。helperはその辞書をclosureで参照し、
`app/runtime_dependencies.py:43-57`がさらにapplication.extensions内のcallback経由で参照する。
`app.py`直接起動のnamespaceも`_publish_entry`でpackageへ公開している。

このため、テストは`app.save_file`、`app.get_r2_client`、`app.USE_R2`、`app.logger`等の
旧差し替え先を使える。その接続の維持が、特殊なfactoryの主な役割になっている。

### 移行先

| 現在の再公開/bridge | 移行先 |
| --- | --- |
| `app.db` | `app.extensions.db` |
| `app.User`, `app.Post`等 | `app.models` |
| `app.calculate_weighted_length` | `app.services.text.calculate_weighted_length`を直接使用 |
| `app.generate_contest_results`, `app.get_cached_contest_results` | `app.services.results` |
| `app.logger`, `route_logger` | request/CLI内の`current_app.logger`、必要なmodule logger |
| `app.USE_R2`等の画像設定 | `current_app.config`、またはアプリ単位の画像integrationの設定 |
| `app.save_file`, `app.delete_file`, `app.get_r2_client` | `app.integrations.images`。fakeは呼出先かアプリ単位のintegrationへ接続 |
| `app.schedule_contest_task` | `app.integrations.cloud_tasks`。必要なfake/clientを明示的に接続 |
| `app.get_current_user`等のroute再公開 | `app.routes.*`。登録テストは通常のnamespaced endpointを確認 |

`app/routes/dependencies.py`は本体から参照されず、互換テストが参照している。
runtime bridgeを撤去する段階で合わせて削除できる。
純粋な文字数計算にapp contextを要求する現在の制約も不要になる。

### factoryに関係する実際の問題

1. **設定を渡す前に既定アプリの環境変数検証が走る。**
   `from app import create_app`の時点で設定なしのappを生成するため、
   完全なtest configを渡す予定でも環境変数がないとimportに失敗する。
2. **OAuthの設定がimport順序に依存する。**
   `app.integrations.x_oauth:15-20`が.env読み込み前の資格情報を固定し得る。
   factoryが設定を読み込んでintegrationへ渡すか、呼出時に有効な設定を解決する。
3. **大会一覧cacheが別アプリ間で共有される。**
   `app.services.contests:13-14`のmodule global cacheにより、異なるSQLite DBの
   2アプリを作って連続で一覧を取得すると、第2アプリも第1アプリの大会名を返す。
   factoryを中心にするならcacheを`app.extensions`等のアプリ単位の状態へ移す。
4. **画像設定は既定namespaceから共有される。**
   `create_app(config)`はbase設定だけを作り直し、画像設定は既定namespaceを利用する。
   新factoryではアプリ単位で設定を確定し、別アプリへ流れない形で接続する。

通常のPythonのimportと明示的なcreate_appでこれらを扱えば、
`_RUNTIME_EXPORTS`、RLock、`__getattr__`、`__dir__`、`_publish_entry`、namespace injectionを撤去できる。
aliasファイルも削除すれば、互換用の`sys.modules`操作も撤去できる。

## 4. dbとextensionsの配置

`db = SQLAlchemy()`は既に`app/extensions.py:17`に1つだけある。
extensions.pyに未初期化のdb/limiter/migrateを置いてfactoryからinit_appする構成は自然で、
新しいDB専用モジュールを必須とはしない。

推奨は次の依存方向に統一すること。

```text
models ────────> extensions.db
services/routes -> extensions.db + models
factory ───────> config, extensions, models, routes, CLI, hooks, integrations
wsgi/実行入口 ─> create_app
```

`app/models/base.py`は現在`SQLAlchemy`まで再公開しているが、モデルで必要なのはdbだけ。
モデルのdb importを`app.extensions`に揃えればbase.pyを削除できる。
services/routesもdbをmodels経由で取得する必要はない。

モデルimport時にLimiter/CORS/Migrate等まで読み込まれることを避けたい場合は、
`app/database.py`にdbだけを置き、modelsとextensionsがそこを参照する構成も選べる。
いずれの場合もdbは1つだけ定義し、create_app内で毎回SQLAlchemyを生成しない。
この調査では標準性と変更量からextensions.pyに統一する案を推奨する。
モデルのカラム・制約・リレーションは変更せず、metadataとAlembic差分ゼロで検証する。

## 5. 推奨する最終入口

```text
netatwi-backend/
  app/
    __init__.py        # create_appの通常の再公開だけ
    factory.py         # トップレベルのcreate_app(config=None)
    config.py
    extensions.py     # 未初期化のdb、limiter、migrate
    hooks.py
    models/
    routes/           # 標準Blueprint
    services/
    integrations/
    cli/
  wsgi.py             # app = create_app()
  app.py              # 必要ならpython app.py用の薄い直接起動入口
```

packageの入口は次の程度で十分。

```python
from .factory import create_app

__all__ = ["create_app"]
```

create_appは、設定読み込み、Flask生成、config反映、extensions初期化、
モデル登録、アプリ固有のintegration/cache設定、Blueprint/CLI/hook登録を行って返す。
importだけで既定アプリを生成しない。モデルimportはcreate_all/migration利用前に完了させる。
通常のfactory内でテーブルを自動作成せず、直接起動時の既存create_allを維持する場合は入口に残す。

WSGI入口は`from app import create_app; app = create_app()`とし、
Dockerfileの`app:app`を`wsgi:app`へ移す。
Flask CLIは`flask --app app:create_app ...`へ揃えられる。
補助scriptはcreate_appとcanonicalなdb/serviceをimportし、明示的なapp contextで実行する。
`app/`packageと`app.py`に両方の互換appを公開する必要がなくなる。

既存のrepository-rootのstatic/instance pathsは維持する。
単に`Flask(__name__)`へ変更してstatic/instanceの位置まで変えない。

## 6. 移行順序と受け入れ条件

1. **未使用aliasの撤去**
   models以外の旧rootを削除し、互換import/identityテストをcanonicalなimportと動作の検証へ変更する。
   models用のGit管理外scriptもこの段階で調査一覧に基づき移行する。
2. **通常Blueprintへの置換**
   legacy.pyを撤去。35 URL/methodとHTTP契約を保持し、endpoint mapを意図して更新する。
   explicit/default rate limit、hook、CORS、CLI、URL生成を検証する。
3. **helper/fakeとアプリ固有の状態の移行**
   文字数・結果helperを直接import、画像とschedulerの設定/fakeをintegrationへ接続、
   loggerと大会cacheをアプリに合わせる。runtime_dependencies/routes.dependenciesを撤去する。
4. **通常factoryと入口への移行**
   create_appをトップレベルにし、package再公開を最小化。WSGI/Docker/直接起動/補助scriptを切り替える。
   遅延初期化、namespace injection、packageへの直接起動appの公開を撤去する。
   残るroot appのimportを移した後にmodels aliasを撤去する。

段階ごとにHTTP/DB/外部副作用のテストを維持する。
互換実装そのものの同一性を要求するテストは、今回の意図に合う内部契約へ変更する。
業務ロジックの不具合修正は別の変更として扱う。

新しい構成で最低限必要な確認:

- 環境変数を用意せず、完全なconfigだけでcreate_appが成功する。
- `import app`とモデル/serviceのimportがアプリ生成・DB接続・外部接続を行わない。
- 2アプリのDB・frontend設定・画像設定・大会cache・fakeが混ざらない。
- .env読み込みとOAuth設定がimport順に依存しない。
- 35 APIのURL/method・応答・認証・期間・commit/rollback・外部副作用を維持する。
- モデル10件のschema/relationship snapshotを維持し、Alembic差分ゼロ。
- WSGI、Flask CLI、直接起動、補助scriptがcanonicalなdbとfactoryを使用する。
- static/instance/uploadsの保存場所とURLを維持する。

## 調査に用いた資料・確認範囲

- 追跡中のPython、現在の実ファイル、Git管理外の補助script、Dockerfile、CI、tests、frontend/formの関連参照。
- 標準Blueprintの差し替え: 497 passed / 1 deselected、35 APIとstaticのURL/method一致、judge rate limit維持。
- 旧root import禁止: 626 passed / 12 deselected、alias契約7件を対象外。
- 異なる一時SQLite DBの2アプリで大会cache混在を再現。
- 実サービス・本番DBへの接続なし。隔離実験はGit管理外の`.venv/architecture-investigation/`で実施。
- [Flask: Application Factories](https://flask.palletsprojects.com/en/stable/patterns/appfactories/)
- [Flask: Modular Applications with Blueprints](https://flask.palletsprojects.com/en/stable/blueprints/)
- [Flask-SQLAlchemy: Quick Start](https://flask-sqlalchemy.palletsprojects.com/en/stable/quickstart/)
