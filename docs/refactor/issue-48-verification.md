# Issue #48: ニュースの取得・追加・削除処理の service 抽出

計画書の順10-6。PR #59のマージを確認し、最新の `origin/master`
(`52f1ad79ea8d67d717fbdbe6d4f486794d4448da`) から
`refactor/48-news-services` を作成した。依存する #8 は取り込み済み。
着手時点で未取り込みPRはなく、`master` のブランチ保護は無効。

## 抽出範囲と接続

`blueprints/news.py` のASTの `lineno` / `end_lineno` を使って元ソースをコピーした。
処理本体を `ast.unparse` で再生成していない。

| 元の範囲 | 抽出先 `services/news.py` | routeに残す処理 |
| --- | --- | --- |
| 公開一覧の取得・整形 | `get_news()` | JSON変換・元のtry/except/print/500 |
| 管理一覧の取得・整形 | `get_admin_news()` | 元の管理者認証・JSON変換・例外境界 |
| 追加の必須判定・URL解析・News作成・add/commit・戻り値構築 | `add_news(tweet_id)` | 管理者認証・request.json/data.get・JSON変換・except内rollback/print/500 |
| 削除の取得・存在判定・delete/commit・戻り値構築 | `delete_news(id)` | 管理者認証・URLのid入力・JSON変換・except内rollback/print/500 |

許可した変更は外側のHTTP returnから `jsonify` を外してpayload/statusを返すこと、
serviceの引数・import・抽出範囲のインデント、routeからの呼び出し接続のみ。
404/400のJSON変換も元のtry内に残す。例外処理をserviceへ移していない。
`re` は元の位置で遅延importし、必須判定より前に読み込まない。
SQL・limit・並び順・入力の真偽判定・正規表現・保存/削除・commit/rollback・ID再取得・
日時変換・JSONキー/型・ステータス・print文言を保持する。
管理者認証を共通化せず、3つの元の認証ブロックをそのまま残す。
serviceはモデル/dbのみをimportし、HTTPやrouteへの依存を追加していない。

## 機械比較

`extract_issue_48.py` は固定基準の元ソース行からservice・routeを生成し、ファイル全文の
一致を確認する。`--write` はこの抽出の再現専用で、後続Issueの変更には使わない。
`verify_issue_48_extraction.py` は独立して元ASTの対象returnだけを変換し、4関数の本体
ソース・AST・引数、service全体のimport、routeモジュール全体を比較する。
認証・HTTP入力・except内rollback/printも含め、許可した接続以外が一致する。

追加テストの本体・期待値は、元コードで成功したコミット
`5304acdd8cc9700e2425ae043b2b7ef21a88f62e` と全文一致する。
テストのfake接続は同じモデル/dbを使用し、遅延re importの観測は移動前後を対象にする。
fixtureを含む、`blueprints/news.py` 以外の既存Pythonファイルはすべて基準と全文一致する。
この比較・記録は #48 の抽出時点を対象とし、後続Issueでは新しい基準を用いる。

```powershell
$pythonExe = "$env:TEMP\netatwi-issue3-venv\Scripts\python.exe"
& $pythonExe docs/refactor/extract_issue_48.py
& $pythonExe docs/refactor/verify_issue_48_extraction.py
& $pythonExe -m pytest -q -p no:cacheprovider --disable-warnings --tb=short
git diff --check origin/master HEAD
```

## 検証結果

- 移動前の既存テスト: **455 passed**。
- 元コードで追加した特性テスト: **72 passed**。移動前の全テスト: **527 passed**。
- 移動後の全テスト: **527 passed**。
- 公開一覧は作成時刻降順で20件、管理一覧は同じ順序で無制限。25件の実DBデータで
  JSONキー・型・日時を確認し、日時は元の `isoformat()` で返す。空一覧は200/空配列。
- 数字ID・X/Twitter URL・query付きURLを保存。最初の `status/(\d+)` の一致を採用する。
  他ドメイン・部分一致・Unicode数字、数字のないURL・大文字STATUS・任意文字列・
  前後空白・空白だけの文字列も元の解釈を保持し、検証やtrimを追加していない。
- None/空文字/0/False/空配列/空辞書/欠損IDは400。re importや更新・rollbackを行わない。
  truthyな数値・真偽値・配列・辞書は元のre失敗で500/rollbackとなる。
- JSON null/配列/文字列、壊れたJSON、JSON以外のContent-Type、空本文は元の500/rollback。
  重複した同じIDを2回登録できる挙動も保持する。
- 一覧・追加・削除の匿名/非管理者/管理者を確認し、認証がqueryとHTTP入力読取より先に
  実行される。user_idの真偽でなくキーの存在を見る元の扱いを保持する。
  管理者名のtrim・環境変数未設定時の既定値・空設定・大文字小文字の扱いも確認。
- 削除成功はdelete/commit各1回。再削除は404で更新・commit/rollbackを行わない。
- 一覧のquery・整形・JSON失敗は元の500/printでrollbackしない。
  追加/削除の取得・更新・commit失敗は元の500/rollback/printで、未commitの変更を戻す。
- commit後のJSON変換失敗でもrollbackを呼ぶが、追加/削除済みの変更は残る。
  commit後のnew_news.id再取得失敗も500/rollbackで、追加済みの行は残る。
  rollback自体の失敗は元のexceptの外へ伝播する。
- 必須入力/対象なしのJSON変換失敗も元のtryに捕捉され、500/rollbackとなる。
  transactionの順序・回数、元のprintとtracebackを追加しない扱いを確認する。
- 全35 route + staticのURL map、factory・既定app・CLI名は既存契約と一致。
  `ScriptInfo(app_import_path="app:app").load_app()` が既定appを解決し、WSGI経由の
  `/api/me` とCLI登録（`process-contests`・`update-user-stats`・`db`）も成功。
- 全10モデルのmetadata・DDL・リレーションはsnapshotと一致し、一時SQLite基準スキーマに
  対するAlembic自動生成差分はゼロ。
- 元ソース全文比較・独立AST比較・`git diff --check`: 成功。

ローカルは一時仮想環境 `netatwi-issue3-venv` の **Python 3.12.14**。
一時SQLite・外部サービスfake・ネットワーク拒否fixtureで実DBと実サービスから隔離した。
WindowsではGunicornプロセスを起動せず、入口解決とWSGIリクエストを確認した。
PostgreSQLや本番migrationには接続していない。既存の非推奨警告は残る。
Python 3.11の結果はPRのGitHub Actionsで確認する。

## コミット・対象外・戻し方

1. 元コードで成功した特性テストを保存。
2. 検証済みのservice抽出・HTTP接続を保存。
3. 抽出再現・比較スクリプトと本記録を保存。

20件制限・並び順・ID/URL解釈・入力検証・保存/削除・transaction・JSONの変更、権限共通化、
重複登録対策、URL検証・例外処理の改善、他APIの抽出、共通依存整理、`app/` への配置移動、
DB migration、フロントエンド変更は含めない。
API契約・DB schema・外部設定に変更はなく、特別なデプロイ順は不要。
問題があればこのPRをまとめてrevertし、処理本体をrouteへ戻せる。
