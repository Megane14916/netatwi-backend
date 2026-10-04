# Issue #44: いいね・ブックマーク処理の service 抽出

計画書の順10-2。PR #55の取り込みを確認し、最新の `origin/master`
(`b471c187e74b0ae3bd6ee41ab9eb3179db02fbe9`) から
`refactor/44-interaction-services` を作成した。依存する #10・#17 は取り込み済み。
着手時点で未取り込みPRはなく、`master` のブランチ保護は無効。

## 変更範囲と対応表

`blueprints/interactions.py` の元ソースから AST の `lineno` / `end_lineno` で文の範囲を
特定し、コメントを含めて切り出した。関数本体を `ast.unparse` で再生成していない。

| 元の範囲 | 抽出先 `services/interactions.py` | routeに残す処理 |
| --- | --- | --- |
| `set_bookmark` の投稿取得・存在判定 | `get_bookmark_post(post_id)` | 認証・session入力・HTTP応答 |
| メソッド読み取り後の既存行取得・更新・件数集計 | `set_bookmark(post_id, user_id, post, is_bookmarked)` | HTTPメソッド入力とJSON変換 |
| ブックマークIntegrityErrorのPUT分岐内 | `recover_bookmark(post_id)` | rollback・PUT判定・回復しない場合の500応答 |
| `set_like` の投稿取得・本人・期間・採点方式判定 | `prepare_like(post_id, user_id)` | 認証・session入力・HTTP応答 |
| メソッド読み取り後の既存票取得・更新・通知・件数集計 | `set_like(post_id, user_id, post, c, is_liked)` | HTTPメソッド入力とJSON変換 |
| いいねIntegrityErrorのrollback後の再取得・件数集計 | `recover_like(post_id, user_id)` | rollbackとJSON変換 |

HTTPメソッドを読む位置を変えないため、事前取得・判定と更新を別入口にした。
通常時のJSON変換は元のtry内に残し、IntegrityErrorの回復は元のexcept内で呼ぶ。
回復中の例外は隣の汎用exceptで捕捉しない。rollback、ログ、traceback、URL・decoratorも
routeの元の位置に残す。通知serviceは元のいいね追加分岐内、commit前で呼ぶ。
serviceからrequest/session・routeへの依存は追加していない。

## 許可した接続変更と機械比較

- 抽出したHTTP returnの `jsonify` を除き、routeで同じpayload・statusを変換する。
- ブックマーク事前取得の成功時に `(post, 200)` を返す。
- いいね事前判定の成功時に `(post, c, 200)`、失敗時に `(payload, None, 403)` を返す。
- ブックマーク回復で投稿がない場合は元どおり暗黙のNoneで終わり、routeが500を返す。
- 新しい関数定義・引数・importと抽出範囲のインデントを調整する。
- 固定時刻のfake接続先だけを、routeのdatetimeからserviceのdatetimeへ移す。

SQL、条件式、通知、commit回数・順序、件数集計・refresh、例外境界は保持した。
6つのservice関数の本体ソース・AST、service全体のimport・引数、routeモジュール全体を
基準と比較する。移動前の特性テストはコミット
`cdc83690a69246af48dd4b619138f554c7f465ff` から変更していない。
`tests/conftest.py` のfake接続変更以外の既存Pythonファイルはすべて基準と一致する。

```powershell
$pythonExe = "$env:TEMP\netatwi-issue3-venv\Scripts\python.exe"
& $pythonExe docs/refactor/extract_issue_44.py
& $pythonExe docs/refactor/verify_issue_44_extraction.py
& $pythonExe -m pytest -q -p no:cacheprovider --disable-warnings
git diff --check origin/master HEAD
```

`extract_issue_44.py` は元ソースから生成したservice・route・fake接続との全文一致を確認する。
`--write` はこの固定基準での抽出再現専用で、後続リファクタリングには使用しない。
`verify_issue_44_extraction.py` は元ASTに上記の接続変更だけを適用して別途比較する。
この記録と比較は #44 の抽出時点が対象。後続Issueの変更には新しい基準・対応表を使う。

## 検証結果

- 移動前の既存テスト: **278 passed**。
- 元コードで追加した特性テスト: **54 passed**（最初のコミットに保存）。
- 移動後の全テスト: **332 passed**。
- PUT/DELETEの初回・再実行・削除後の再作成、件数の全JSON応答と通知件数を確認。
  ブックマークは他ユーザーの元行も集計し、古いcached counterを置き換える。
- ブックマークは本人投稿・投稿開始前・一般投票方式でも操作可能。
  いいねは本人投稿、投票終了直前/時点/以後、judge/user/hybrid方式の判定順を保持。
- 保存済み審査員票はPUT/DELETEとも400。一般票の0点・2点はPUTで値・賞・コメントを
  変更せず、DELETEで削除する。件数は一般票のcount=1だけを集計する。
- ブックマークの追加/削除 → 1 commit → 元行の件数取得 → counter更新 → 1 commit →
  refreshの順を確認。何も変わらない再実行も2 commitする。
- いいねのVote追加 → 通知追加 → 1 commit → 件数取得、削除 → 1 commit → 件数取得を確認。
  再PUTは通知を増やさず、削除後の再作成では元の通知を残して増える。
  大会の投票者/審査員カウンタは変更しない。
- 一時SQLiteの実際の一意制約違反を、既存行が初回取得で見えない状況をfakeして再現。
  rollback → 既存行/件数再取得の順を確認し、通知追加はrollbackされる。
  競合先の一般票0点でもisLiked=true、審査員票ならfalseになる元の応答を保持する。
- IntegrityErrorでも元行がない場合のブックマークPUT=200/DELETE=500、いいねPUT/DELETE=200、
  ブックマーク回復時に投稿がない場合の500、回復中のquery例外の伝播を確認。
  回復経路でcounter更新・commit・refreshは追加しない。
- 1回目/2回目のcommit失敗、commit後のcount/refresh/JSON変換失敗で、既にcommitした行と
  通知が残る元の境界を確認。rollback回数、ログの文言、ブックマークのtraceback呼出も保持。
- 既存の通知作成失敗時のrollback特性テストも成功。
- 全35 route + staticのURL map、既定appとfactory、CLI名は既存契約と一致。
  Flaskの `ScriptInfo(app_import_path="app:app").load_app()` が既定appを解決し、
  WSGI経由の `/api/me` とCLI登録（`process-contests`・`update-user-stats`・`db`）も成功。
- 全10モデルのmetadata・DDL・リレーションはsnapshotと一致。
  一時SQLiteの基準スキーマに対するAlembic自動生成差分はゼロ。
- 元ソース全文比較、AST比較、`git diff --check`: 成功。

ローカルは一時仮想環境 `netatwi-issue3-venv` の **Python 3.12.14** を使用。
一時SQLite、外部サービスのfake、ネットワーク拒否fixtureで実DB・実サービスから隔離した。
競合テストは実DBの並列実行ではなく、古い取得結果と実際の一意制約で回復経路を検証した。
Windows上でGunicornプロセスは起動せず、入口解決とWSGIリクエストを確認した。
PostgreSQLや本番migrationには接続していない。既存の非推奨警告は残る。
Python 3.11の結果はPRのGitHub Actionsで確認する。

## コミットの区切り

1. 元コードで成功した特性テストを保存。
2. 検証済みのservice抽出・route接続・時刻fakeの接続先変更を保存。
3. 抽出再現・比較スクリプトと本記録を保存。

## やってないこと・戻し方

冪等性、通知件数、Vote/Bookmarkの扱い、counter、SQL、commit/rollback・例外・応答の
改善は含めない。競合処理・トランザクション・通知・入力検証・参照整合性の修正は後続Issue。
共通依存の整理、`app/` への配置移動、DB migration、フロントエンド変更は含めない。
API契約・DB schema・外部設定の変更はなく、特別なデプロイ順は不要。
問題があればこのPRのコミットをまとめてrevertし、処理本体と時刻fakeを元へ戻せる。
