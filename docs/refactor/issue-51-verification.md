# Issue #51: application factoryと登録処理の集約

計画書の順10-9。PR #62のマージを確認し、最新の `origin/master`
(`2c69378a995c27c7e2d999e56560a7d36426fc9f`) から
`refactor/51-application-factory` を作成した。依存する #49・#50は取り込み済み。
着手時に未取り込みPRはなく、masterのブランチ保護は無効。

## 抽出と互換接続

全35 routeは #49でBlueprintへ移動済みで、CLIも既存の登録関数がある。
このためfactoryで既定appのURL mapとCLIを走査して不足項目をコピーする処理を外し、
既定appと各factoryインスタンスを同じBlueprint/CLI登録で構築する。
アプリ生成・runtime設定・画像初期化・helper接続・登録の本体をapp_factory.pyへ移動する。

| 元の範囲 | 移動先 | 保持・調整 |
| --- | --- | --- |
| app_factory.py:create_base_app | 同じ関数・同じ場所 | 全文ソース・AST一致。設定→Flask→config→logging→extensions→hooksを保持 |
| app.pyのapp/runtime_settings〜画像設定 | app_factory.py:initialize_application | 元の順序でentryの名前空間に値を設定。画像設定は起動時に一度だけ |
| app.pyの画像/結果/Cloud Tasks互換ラッパー | initialize_application内の関数 | app.pyの現在の設定・module・callbackを呼出し時に参照 |
| app.pyの文字数関数の再公開 | initialize_application内の元のimport | services.textの同じ関数を再公開 |
| app.py:_register_extracted_routesと既定appへの2つの登録呼出し | initialize_application内の関数と同じ呼出し | callback設定→15 Blueprint→CLIの順序、キー、関数オブジェクトを保持 |
| app.py:create_app | initialize_application内の関数 | create_base_app→Blueprint登録→CLI登録→return。旧appの不足項目コピーを除去 |
| app.pyの直接起動 | app.pyに保持 | app contextでdb.create_all→print→PORT→app.runの全文一致 |

app.pyはfactoryの `initialize_application(globals())` を呼び、必要な互換名を公開する。
元のimport名、設定、helper、create_app、privateな登録helperを明示的に再公開し、
既存の `from app import app, create_app, db` と補助スクリプトの入口を維持する。
factoryはapp.pyをimportせず、factoryのimportだけでは既定appを生成しない。
BlueprintとCLIのimportも元と同じruntime・画像・helper設定後に行う。

許可した構造変更:

- 処理本体をASTの行範囲からコピーし、外側のfactory初期化関数へ配置する。
- runtimeの代入先と、移動したラッパー/factory内の元のglobal名を `namespace[名前]` にする。
  `globals()` は渡されたentryのnamespaceに置換する。引数・keyword名・属性名は変更しない。
- 元のimportと新しい関数をentryへ公開する辞書を挿入し、元の名前を維持する。
- loggerの生成にはentryの `__name__` を使い、通常import・別名実行・__main__の名前を維持する。
- create_appの `registered_endpoints` 代入と不足route/CLIを補う2つのloopだけを除去する。
  既定appへ後から動的に追加したroute/CLIをfactoryへ複製する旧fallbackは残さない。

各factoryアプリの設定は引き続き個別だが、Blueprint・CLI・db/migrate/limiterと
runtime設定・画像・helper/logger/schedulerのentry経由の共有方法は元のまま。
登録時に値を固定せず、app.pyのcreate_base_app/登録関数やcallbackの後からの差し替えも保つ。
factoryごとに画像設定を読み直さず、ディレクトリ作成やclient初期化を追加しない。
ディレクトリ配置のappパッケージ統一は #52で扱う。

## 機械比較と特性テスト

`extract_issue_51.py` は固定SHAから元のソース行を取得し、Nameとglobals()の
AST位置だけを置換する。処理本体をast.unparseで生成しない。
ネスト位置に合わせてコードをindentするが、multiline STRING tokenの内容はindentせず、
元の複数行docstringの値も完全に保持する。--writeはこの抽出の再現専用。

`verify_issue_51_extraction.py` は独立したAST変換でfactoryとentryの全体を比較する。
base factory、移動したruntime/helper/登録/factoryの本体ソース、直接起動のソースを比較し、
許可したnamespace接続とfallback除去以外の変更がないことを確認する。
app.py/app_factory.py以外の既存Pythonは、下記のテストharnessを除き基準と全文一致する。

#50の名前空間テストは、runpyが返す辞書のcopyと関数.__globals__に依存していた。
factoryへの移動前に、同じ別名entryをimportlibで実行してmodule.__dict__を取得する
harnessへ変更した。テスト本体の初期化順・回数・値・logger・差し替えの期待値は変えない。
この変更と追加10件は元コードで成功するコミット
`81cf3259485a4b47f161d2bf0971b99c34dae46a` に保存した。
CIでGit管理対象外のscripts/内の2ケースが存在しないため失敗したので、
最終テストでは追跡対象のsync_comment_counts.pyだけを必須にする。
比較スクリプトはこのparameterリスト変更だけを許可し、テスト本体・期待値の一致を確認する。

```powershell
$pythonExe = "$env:TEMP\netatwi-issue3-venv\Scripts\python.exe"
& $pythonExe docs/refactor/extract_issue_51.py
& $pythonExe docs/refactor/verify_issue_51_extraction.py
& $pythonExe -m pytest -q -p no:cacheprovider --disable-warnings --tb=short
git diff --check origin/master HEAD
```

## 検証結果

- 移動前の既存テスト: **615 passed**。
- 追加10件と既存共通helper34件: **44 passed**。移動前の全テスト: **625 passed**。
- 移動直後の同44件と全テスト: **625 passed**。
  CI対象を追跡ファイルへ修正後の追加8件・共通helper34件は **42 passed**、
  最終全テストは **623 passed**。既存警告371件。
- 設定読取→Flask→logging→extensions→hooks→画像初期化→callback→
  元の順の15 Blueprint→CLIを実行記録で確認。factoryでは画像初期化を繰り返さない。
- 既定appとfactory2個のroute登録順、endpoint/handler、CLI順とオブジェクト同一性、
  hookの順・数、error handler、設定分離、db/migrate/limiterの共有を確認。
- entry側のcreate_base_app、Blueprint登録helper、CLI登録関数の登録後差し替えを確認。
  各アプリで画像・logger・schedulerの後からの差し替えが同じentryに解決する。
- Flaskのapp:appとapp:create_app(...)を解決し、WSGIの/api/me、CLI名を確認。
- __main__で実行し、db.create_all→print→serverの順と、PORT既定5001/指定8123、
  host/debug引数を確認。DB作成とサーバー起動はfakeで、実接続はしない。
- 追跡対象のsync_comment_counts.pyをmain以外の名前で実行し、app/dbが同じ公開
  オブジェクトと確認。ローカルだけのscripts/内2ファイルも同様に確認したが、
  .gitignore対象なのでCIの必須ケースには含めない。
- 新規Pythonプロセスでapp_factoryのみをimportし、app/Blueprint/既定appの
  初期化がないことを確認。既定appをNoneに差し替えてもfactoryは全route/CLIを登録し、
  旧appのURL mapやcommandsを参照しないことを別途確認。
- 全35 route + static、10モデルのmetadata/DDL/リレーションは既存snapshotと一致。
  一時SQLite基準スキーマに対するAlembic自動生成差分はゼロ。
- 全文再現、独立ソース/AST比較、git diff --checkは成功。

ローカルは一時仮想環境netatwi-issue3-venvの **Python 3.12.14**。
一時SQLite、外部fake、ネットワーク拒否fixtureで隔離した。
WindowsではGunicorn自体は起動せず、Flask入口解決・WSGI・fakeによる直接起動を確認した。
本番DB・PostgreSQL・実外部サービスは利用していない。
Python 3.11はPRのGitHub Actionsで確認する。

## コミット・対象外・戻し方

1. 元コードで成功する特性テストと既存テストharnessの接続変更を保存。
2. 検証済みのfactoryへの移動・互換名公開とfallback除去を保存。
3. 機械抽出・独立比較スクリプトと本記録を保存。
4. CIの失敗原因だったGit管理対象外の補助スクリプト2ケースを必須対象から外し、記録を修正。

設定解釈、DB初期化、CORS/Limiter/hooks/エラー応答、URL/CLI、画像・Cloud Tasks・
client cache、複数app間の状態共有、SQL/時刻/commit/rollback/認証の改善は含めない。
appパッケージへの配置、DB migration、フロントエンド変更も含めない。
API/DB schema/外部設定に変更はなく、特別なデプロイ順は不要。
問題があればPRをまとめてrevertし、factory本体・互換接続・test harnessを元へ戻せる。
