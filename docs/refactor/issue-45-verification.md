# Issue #45: 大会一覧・詳細・管理一覧の取得処理の service 抽出

計画書の順10-3。PR #56の取り込みを確認し、最新の `origin/master`
(`4f6f70c05b3455f80927cbedc9979e58bda23248`) から
`refactor/45-contest-query-services` を作成した。依存する #9・#16 は取り込み済み。
着手時点で未取り込みPRはなく、`master` のブランチ保護は無効。

## 変更範囲と対応表

元ソースのASTの `lineno` / `end_lineno` で文の範囲を特定し、コメントを含めて切り出した。
関数本体を `ast.unparse` で再生成していない。

| 元の範囲 | 抽出先 `services/contests.py` | routeに残す処理 |
| --- | --- | --- |
| `blueprints/contests.py` のキャッシュ有効判定 | `get_cached_contests(time)` | 元のtime import、命中時のJSON変換（tryの外） |
| `get_contests` の取得・分類・整形・キャッシュ更新 | `get_contests(time)` | JSON変換と元の500例外境界 |
| `get_contest_details` の大会取得・時刻取得・最初のログ | `get_contest_for_details(id, start_time, time)` | 元の計測起点、その後のsession入力 |
| 詳細の予選情報・時刻取得・ログ・payload構築 | `get_contest_details(contest, user_id, start_time, time)` | JSON変換と元の404例外境界 |
| `blueprints/admin.py` の管理一覧try内 | `get_management_contests()` | 管理者認証・JSON変換・500応答・ログとtraceback |

元のlogger（`logging.getLogger("app")`）・JST定数と、キャッシュの初期値None/0をserviceへ移す。
キャッシュはプロセス内の同じモジュール変数で共有し、factoryごとに生成・初期化し直さない。
詳細のsession読み取りは大会取得と最初のログの後に残す。
`time` は元のrouteの位置で一度だけimportし、その参照をserviceへ渡す。
serviceからHTTPのrequest/session・routeへの依存は追加していない。

## 許可した接続変更と機械比較

- 抽出した外側のHTTP returnの `jsonify` を除き、routeで同じpayloadを変換する。
- キャッシュ有効判定は元の条件式を維持し、命中時は `(True, cached_payload)`、
  非命中時は `(False, None)` を返す。routeはこの判定結果を使い、payloadの真偽を再判定しない。
- 詳細の取得helperは元の `contest` を返す。
- cacheのglobal宣言、元のtime参照・計測起点、必要な引数・import・抽出範囲のインデントを調整する。
- cacheリセット・datetime fakeをserviceへ接続し、不要になったadmin側のdatetime fakeを除く。
  追加テストはquery/cache/loggerの接続先importのみ変更する。

5つのservice関数の本体ソース・AST、service全体のimport・logger・JST・cache初期値・引数、
public/adminのrouteモジュール全体を基準と比較する。管理の作成・更新・削除・schedulerは
変更していない。追加テストの本体と期待値は、移動前のコミット
`a5bbf9950f4f3d055d335edb65139b8ab0490dbc` と一致する。
fixtureの接続変更以外の既存Pythonファイルはすべて基準と一致する。

```powershell
$pythonExe = "$env:TEMP\netatwi-issue3-venv\Scripts\python.exe"
& $pythonExe docs/refactor/extract_issue_45.py
& $pythonExe docs/refactor/verify_issue_45_extraction.py
& $pythonExe -m pytest -q -p no:cacheprovider --disable-warnings
git diff --check origin/master HEAD
```

`extract_issue_45.py` は固定した基準と移動前テストから生成したファイルとの全文一致を確認する。
`--write` はこの抽出の再現専用で、後続リファクタリングには使わない。
`verify_issue_45_extraction.py` は元ASTに上記の接続変更だけを適用して別途比較する。
この比較・記録は #45 の抽出時点が対象。後続Issueでは新しい基準・対応表を使う。

## 検証結果

- 移動前の既存テスト: **332 passed**。
- 元コードで追加した特性テスト: **38 passed**（最初のコミットに保存）。
- 最終の移動後全テスト: **370 passed**。
- 一覧・詳細・管理一覧の全JSON項目・型、JST表現、modelのカウンタを直接使う扱いを確認。
  公開側ではhasTheme=falseでもthemeを返し、管理側ではNoneにする元の扱いを保持。
- 投稿開始・投稿終了・投票終了の直前/時点/直後の分類と、管理一覧の `voting_end_time >= now`
  による投票終了時点の包含を確認。
- 公開のongoing/voting/closedは開始時刻降順、upcomingだけ逆順、管理も開始時刻降順。
  最新結果は投票終了時刻でなく、開始時刻順のclosed先頭を選ぶ。
- None日時の既存ガードはquery fakeで確認。DBのNOT NULL制約は変更していない。
- 匿名・親大会なし・結果なし・進出/非進出の詳細応答、他ユーザーの結果を使わない扱いを確認。
  hasQualifierではなくparentContestIdを使う元の条件も保持。
- cacheの初期値None/0、空DBでもtruthyなpayloadをcacheする扱い、factoryをまたぐ同じdictの
  再利用、空dict/Noneでは期限判定のclockを読まない扱いを確認。
- 4.999秒は命中、5秒ちょうどから期限切れ。clockが過去へ戻る場合も元どおり命中する。
  命中時はqueryなしでclockを1回、期限切れは判定と保存で2回読む。
- 期限切れ後のquery失敗は古いcacheを保持。保存時のclock失敗は新payloadと古いtimestampを
  残す。命中時のclock/JSON変換失敗は例外を伝播し、非命中のJSON変換失敗は500を返す。
  非命中のJSON変換前にcacheが保存される元の順序も保持。
- 一覧cacheが残る間にDBを変更しても、詳細・管理一覧は最新の行を読む。
- 詳細のclock取得3回、ログの順序・文言と計測起点を確認。query/JSON失敗時は元の404、
  管理一覧は元の500・ログ・tracebackとなる。管理者名のtrimと認証がqueryより先に実行される。
- 取得処理にcommit/rollbackや集計countを追加していないことを確認。
- 全35 route + staticのURL map、既定appとfactory、CLI名は既存契約と一致。
  Flaskの `ScriptInfo(app_import_path="app:app").load_app()` が既定appを解決し、
  WSGI経由の `/api/me` とCLI登録（`process-contests`・`update-user-stats`・`db`）も成功。
- 全10モデルのmetadata・DDL・リレーションはsnapshotと一致。
  一時SQLiteの基準スキーマに対するAlembic自動生成差分はゼロ。
- 元ソース全文比較、AST比較、`git diff --check`: 成功。

ローカルは一時仮想環境 `netatwi-issue3-venv` の **Python 3.12.14** を使用。
一時SQLite、外部サービスのfake、ネットワーク拒否fixtureで実DB・実サービスから隔離した。
Windows上でGunicornプロセスは起動せず、入口解決とWSGIリクエストを確認した。
PostgreSQLや本番migrationには接続していない。既存の非推奨警告は残る。
Python 3.11の結果はPRのGitHub Actionsで確認する。

## コミットの区切り・対象外・戻し方

1. 元コードで成功した特性テストを保存。
2. 検証済みのservice抽出とHTTP/fakeの接続変更を保存。
3. 抽出再現・比較スクリプトと本記録を保存。

期間条件、表示対象、管理用フィールド、並び順、日時・JSON表現、cacheの寿命・共有範囲・
有効判定、SQL・権限・ログの改善は含めない。cacheの無効化やappごとの分離は追加しない。
他のAPIの抽出、共通依存の整理、`app/` への配置移動、DB migration、フロントエンド変更は
含めない。API契約・DB schema・外部設定に変更はなく、特別なデプロイ順は不要。
問題があればこのPRのコミットをまとめてrevertし、処理本体とfakeを元へ戻せる。
