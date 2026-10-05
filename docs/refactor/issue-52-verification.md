# Issue #52: appパッケージへの配置統一

計画書の順10-10。PR #63のマージを確認し、最新の `origin/master`
(`0c71ecf9780dc75e5fa60e4b5f255a6bb77b0b59`) から
`refactor/52-app-package` を作成した。依存する #50・#51は取り込み済み。
着手時に未取り込みPRはなく、masterのブランチ保護は無効。

## 配置と互換接続

58個の実装ファイルを元ソースのまま `app/` 配下へコピーし、内部importを更新した。
factory・Blueprint/CLI登録の本体は `app/factory.py`、設定は `app/config.py`、
拡張機能は `app/extensions.py`、共通hook/helper接続は `app/hooks.py` と
`app/runtime_dependencies.py` に置く。`app/__init__.py` がfactory・登録関数・
WSGIのappと以前の公開helperを提供する。処理本体のコピーを旧配置に残さない。

調整した接続は以下に限定する。

- AST上のimport位置のmoduleパスを置換する。元のlocal名・aliasは保持する。
  関数、SQL、条件、時刻、外部副作用、例外境界、commit/rollbackを再生成しない。
- `models/base.py` の唯一のSQLAlchemy生成文を全文コピーして `app/extensions.py` へ置く。
  `app/models/base.py` はそのSQLAlchemy/dbを再公開するだけにし、循環importを避ける。
  拡張機能のモジュールをimportする際のモデル定義読込順は変わるが、factoryは
  全モデルのmetadata登録後にアプリを構築する。db/migrate/limiterの生成は各1回。
- `Flask("app")` に元のリポジトリroot_path/instance_pathを指定する。
  同名packageへの移行でstatic・open_resource・instanceの基準が移るのを防ぐ。
  UPLOAD_FOLDERの相対値とmakedirsの処理は変更しない。
- `app.py` の直接起動本体は維持し、初期化した公開属性をpackageにも公開する。
  直接起動後の `from app import app` が別のappを生成しないようにする。
- テストと追跡対象の `sync_comment_counts.py` のimport/fake接続先を新配置へ更新する。
  `__module__` 等のmodule名ラベルは新配置に合わせるが、HTTP・時刻・DB・副作用の
  期待値は変更しない。conftestでは最初の公開app参照を明示する。

### 同名packageと初期化時点

Pythonは `app.py` より `app/__init__.py` を優先する。このためpackageでの即時初期化を
採用すると、以前は単独でimportできたmodels・services・config等のimportでも
親package経由でアプリを起動してしまう。環境変数検証・Flask生成・画像初期化の
副作用を単独importへ持ち込まないことを優先し、公開runtime属性の初回参照時に
既存の `initialize_application` を呼ぶ薄いadapterとした。

**裸の `import app` だけでは既定appを初期化しなくなる点は、移動前との違いである。**
`app.app`、`app.create_app`、`from app import app, create_app, db`、WSGIの `app:app`
は初回参照時に同じ初期化を行う。設定読取→Flask→logging→extensions→hooks→画像→
callback→15 Blueprint→CLIというアプリ初期化の順序・回数は維持する。
公開属性の一覧は旧factoryから機械的に取得し、旧互換helperも提供する。
初回factory参照の並行実行はlockで直列化し、初期設定の失敗時は公開属性を復元して
再試行可能にする。既定appを先に解決した後の別名app.py実行は旧entryテストと同様に
別のentryを初期化し、既存のpackageの既定appを上書きしない。

### 残した旧importと理由

| 旧import | 薄い再公開の方式・理由 |
| --- | --- |
| app_config / app_extensions / app_factory / app_hooks / runtime_dependencies | sys.modulesの別名でcanonical moduleと同一オブジェクトを返す。設定・拡張機能・hook・factoryの旧参照や差し替えを維持 |
| models と全child module | app.modelsと同一module。全10モデル・db・metadataの二重定義を防ぎ、既存の公開model importを維持 |
| blueprints と全child module | app.routesと同一module。旧Blueprint・callback参照を維持。旧childファイルの処理本体は削除 |
| cli と全child module | app.cliと同一module。旧command参照を維持。旧childファイルの処理本体は削除 |
| services / integrationsの各child module | childごとの薄い別名。元の遅延import時点を保ち、fake差し替え・Cloud Tasks client cacheをcanonical側と共有 |

services/integrationsの旧rootは処理も状態も持たない互換namespaceとして残す。
childを全て先読みするroot aliasにはしない。models/routes/CLIは元の__init__で既に
childを読むため、rootとchildの両方を同一moduleとして公開する。
旧ファイル30個を削除し、残る旧配置はimportの再公開だけである。
canonical実装は旧配置をimportせず、servicesからroutesへの依存もない。

## 全ファイル対応表

| 移動前 | 移動後 |
| --- | --- |
| app_config.py | app/config.py |
| app_extensions.py | app/extensions.py |
| app_factory.py | app/factory.py |
| app_hooks.py | app/hooks.py |
| blueprints/__init__.py | app/routes/__init__.py |
| blueprints/account.py | app/routes/account.py |
| blueprints/admin.py | app/routes/admin.py |
| blueprints/auth.py | app/routes/auth.py |
| blueprints/comments.py | app/routes/comments.py |
| blueprints/contests.py | app/routes/contests.py |
| blueprints/core.py | app/routes/core.py |
| blueprints/dependencies.py | app/routes/dependencies.py |
| blueprints/interactions.py | app/routes/interactions.py |
| blueprints/legacy.py | app/routes/legacy.py |
| blueprints/news.py | app/routes/news.py |
| blueprints/notifications.py | app/routes/notifications.py |
| blueprints/posts.py | app/routes/posts.py |
| blueprints/profile.py | app/routes/profile.py |
| blueprints/results.py | app/routes/results.py |
| blueprints/tasks.py | app/routes/tasks.py |
| blueprints/users.py | app/routes/users.py |
| blueprints/voting.py | app/routes/voting.py |
| cli/__init__.py | app/cli/__init__.py |
| cli/process_contests.py | app/cli/process_contests.py |
| cli/user_stats.py | app/cli/user_stats.py |
| integrations/__init__.py | app/integrations/__init__.py |
| integrations/cloud_tasks.py | app/integrations/cloud_tasks.py |
| integrations/images.py | app/integrations/images.py |
| integrations/x_oauth.py | app/integrations/x_oauth.py |
| models/__init__.py | app/models/__init__.py |
| models/base.py | app/models/base.py |
| models/bookmark.py | app/models/bookmark.py |
| models/comment.py | app/models/comment.py |
| models/contest.py | app/models/contest.py |
| models/contest_result.py | app/models/contest_result.py |
| models/news.py | app/models/news.py |
| models/notification.py | app/models/notification.py |
| models/post.py | app/models/post.py |
| models/user.py | app/models/user.py |
| models/user_stats.py | app/models/user_stats.py |
| models/vote.py | app/models/vote.py |
| runtime_dependencies.py | app/runtime_dependencies.py |
| services/__init__.py | app/services/__init__.py |
| services/auth.py | app/services/auth.py |
| services/comments.py | app/services/comments.py |
| services/contest_lifecycle.py | app/services/contest_lifecycle.py |
| services/contest_posts.py | app/services/contest_posts.py |
| services/contests.py | app/services/contests.py |
| services/interactions.py | app/services/interactions.py |
| services/news.py | app/services/news.py |
| services/notifications.py | app/services/notifications.py |
| services/posts.py | app/services/posts.py |
| services/profile.py | app/services/profile.py |
| services/results.py | app/services/results.py |
| services/text.py | app/services/text.py |
| services/user_stats.py | app/services/user_stats.py |
| services/users.py | app/services/users.py |
| services/voting.py | app/services/voting.py |

app.pyは直接起動入口として残す。新規app/__init__.pyは上記の公開adapterであり、
移動元の処理本体は持たない。sync_comment_counts.pyと既存テストは配置を変更しない。

## 機械比較

`extract_issue_52.py` は固定SHAのファイル全文を取得し、ASTのUTF-8 byte位置にある
importパスだけを編集する。db生成・Flaskリソースパス・薄い再公開は明示したadapter。
`ast.unparse` は使わず、コメント・文字列・docstring・処理本体を保持する。
デフォルト実行で119ファイルの全文再現一致と旧ファイル削除を確認する。
`--write` はこの移動を再現する専用オプションで、通常の検証には不要。

`verify_issue_52_extraction.py` は抽出scriptに依存しない逆import変換と独立AST変換で、
全58実装のソース全文・モジュール全体のASTを比較する。db移動とFlaskパス指定以外の
本体変更を許可しない。旧aliasの全文、直接起動の元ソース、公開adapterのレビュー済み
hash・旧factoryから導いた公開名一覧も確認する。
既存テストのimport/module名/fake接続とconftestの公開属性参照以外は基準と一致する。
その他の既存ファイルはGitの改行filterを適用したblobで比較する。
移動前に追加した15テストのソースも最初のコミットと一致する。

```powershell
$pythonExe = "$env:TEMP\netatwi-issue3-venv\Scripts\python.exe"
& $pythonExe docs/refactor/extract_issue_52.py
& $pythonExe docs/refactor/verify_issue_52_extraction.py
& $pythonExe -m pytest -q -p no:cacheprovider --disable-warnings --tb=short
git diff --check origin/master HEAD
```

## 検証結果

- 移動前の既存全テスト: **623 passed**。
- 追加したcold import・直接起動・公開entry・リソースパスの15件: **15 passed**。
  これらは移動前に成功し、コミット `a9619f00cc1852398c742c14ad775cc5ec963318` に保存した。
  移動前の全テスト: **638 passed**。
- 移動後の接続・factory・helper等の対象テスト: **62 passed**。
  遅延importを観測するfakeのmodule名を更新後、関連テスト: **249 passed**。
- 最終全テスト: **645 passed, 371 warnings**（130.50秒）。既存警告は同じ。
  新配置と旧aliasの同一性・cache共有・直接起動後の公開・依存方向・失敗後再試行・
  並行初回factory参照を確認する7件を追加した。削除・skipしたテストはない。
- 全35 route + staticのURL map、endpoint・handler、CLI名・順序・同一性は既存snapshotと一致。
  移動したhandlerのmodule名だけ新配置に合わせる。既定appと複数factoryでも確認。
- 全10モデルのregistry・metadata・DDL・制約・リレーションを保持。
  一時SQLite基準スキーマに対するAlembic自動生成差分はゼロ。
- 新規Pythonプロセスの旧config/extensions/factory/hooks/dependencies・models・
  Blueprint・service・integration・CLIの単独importでFlask生成や外部client生成がない。
  必須環境変数を除き、Flask生成・ネットワーク・外部clientを拒否して確認。
- `app/__init__.py` のimport優先、`app:app`、`app:create_app(...)`、WSGIの/api/me、
  Flask CLI、sync_comment_counts.pyの公開app/dbとの同一性を確認。
- fakeによる直接起動でdb.create_all→print→server、PORT・host・debug・logger名を保持。
  cold起動後のpackage参照でもapp生成は1回。画像ディレクトリ作成も1回。
- repository root/static/instance/open_resourceの基準は移動前と同じ。
- 全文再現、独立ソース/AST比較、git diff --checkは成功。

ローカルは一時仮想環境の **Python 3.12.14**。テスト用環境変数・一時SQLite・
外部fake・ネットワーク拒否fixtureで隔離した。WindowsではGunicorn自体を起動せず、
Flaskの入口解決・WSGI・fakeの直接起動を検証した。本番DB・実外部サービスは利用しない。
Python 3.11はPRのGitHub Actionsで確認する。

## コミット・対象外・戻し方

1. 元配置で成功する15件の特性テストを保存。
2. 58実装の配置移動、公開adapter・旧import互換、テスト接続と新配置の7件を保存。
3. 抽出・独立比較scriptと本記録を保存。

やってないこと: API/CLI・SQL・認証・設定値・時刻・画像/Cloud Tasks・commit/rollback・
例外処理の改善、DB migration、frontendの変更、テストのunit/api/integration分類。
テスト分類と構造リファクタリングの全体監査は #53で行う。
公開属性を解決する前の裸のimportの初期化時点は上記の通り変更する。
問題があればPRをまとめてrevertし、実装ファイル配置・import・互換adapterを元へ戻せる。
