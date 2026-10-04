# Issue #46: 大会別投稿一覧の取得処理の service 抽出

計画書の順10-4。PR #57のマージを確認し、最新の `origin/master`
(`be9957eaaf83721ab65db013724949cf4a1937fb`) から
`refactor/46-contest-post-query-services` を作成した。依存する #9・#13・#14 は取り込み済み。
着手時点で未取り込みPRはなく、`master` のブランチ保護は無効。

## 抽出範囲と接続

ASTの `lineno` / `end_lineno` で元の文を特定し、コメントを含むソース行をコピーした。
処理本体を `ast.unparse` で再生成していない。

| 元の `blueprints/posts.py:get_posts_for_contest` の範囲 | 抽出先 `services/contest_posts.py` |
| --- | --- |
| 大会取得、投稿取得、各時刻・ログ（session読み取りの直前まで） | `get_posts_for_listing(id, start_time, time)` |
| 閲覧者の投票・審査員賞・コメント取得、投稿者数、表示データ、残る時刻・ログ | `get_posts_for_contest(id, c, posts, user_id, t2, start_time, time)` |

routeは元の位置で `time` を一度だけimportし、計測起点の `time.time()` をtryの外で実行する。
大会・投稿取得と2つのログの後に `session.get("user_id")` を読み、後半のserviceを呼ぶ。
JSON変換・元のexcept・print・500応答はrouteに残す。
投稿CRUDの本体・HTTP接続、既存の `services/posts.py` は変更していない。
追加serviceはHTTPのrequest/session・routeをimportしない。

許可した構造上の変更:

- 前半helperは `(c, posts, t2)` を返し、元のローカル変数を後半へ渡す。
- 最後のHTTP returnだけから `jsonify` を外し、routeで同じpayloadを変換する。
- 引数・import・抽出範囲のインデントを調整する。loggerとJSTは元の定義をコピーする。
  CRUD用のrouteのJSTは維持する。`Comment` の遅延importは元の分岐・位置に残す。
- 追加テストのlogger接続先importだけをserviceへ変更する。

元のSQL・順序・条件・日時変換・画像デコード・ログ文言と計測式を保持した。
return直後の既存コメントもコピーしている。

## 機械比較

`extract_issue_46.py` は基準SHAの元ソース行からservice・route・追加テストを生成し、
ファイル全文の一致を確認する。`--write` はこの固定した抽出の再現専用とする。
`verify_issue_46_extraction.py` は別途元ASTに上記の接続変更だけを適用し、2関数の本体ソース・
AST・引数、service全体のimport・定数、routeモジュール全体を比較する。

追加テストの本体・期待値は、元コードで成功したコミット
`96fc9365070215e20d3cc39aa70dc59a572e81e5` と一致する。
`blueprints/posts.py` 以外の既存Pythonファイルはすべて基準と全文一致する。
この比較・記録は #46 の抽出時点を対象とし、後続Issueでは新しい基準を用いる。

```powershell
$pythonExe = "$env:TEMP\netatwi-issue3-venv\Scripts\python.exe"
& $pythonExe docs/refactor/extract_issue_46.py
& $pythonExe docs/refactor/verify_issue_46_extraction.py
& $pythonExe -m pytest -q -p no:cacheprovider --disable-warnings --tb=short
git diff --check origin/master HEAD
```

## 検証結果

- 移動前の既存テスト: **370 passed**。
- 元コードで追加した特性テスト: **38件**。移動前の全テスト: **408 passed**。
- 移動後の全テスト: **408 passed**。
- 匿名・ログイン済み・審査員・投稿者の全JSON項目と型、JST表現、作成時刻降順、
  大会ごとの取得対象、閲覧者ごとの投票・賞・コメントを確認。
- 0点と小数点の投票、審査員賞、nullableコメント、未投票のNone/False、他人・他大会の
  情報の除外を確認。sessionの審査員認証状態にかかわらず保存済みの情報を返す。
- 大会の開始・終了・投票終了時刻を変えても、`is_voting_visible=False` でも投稿を返す。
  閲覧制限を追加していない。
- None/0/空文字のuser_idは匿名と同じ分岐、存在しないtruthyなuser_idではVote/Commentを
  取得する。匿名はPostのみ、ログイン済みはPost/Vote/Commentの順に取得する。
- 投稿者数は行数やdistinct数ではなく保存済みの `c.post_count`。空大会でもその値を返す。
  一覧外のpostに結びつく大会内Voteがある場合も `userHasVotedInContest=True` を保持。
- 画像フィールドはモデルの既存デコードを使用し、None/壊れたJSON/辞書形式も元どおり。
  キャッシュを追加せず、2回目の取得でDBの変更を反映する。
- 匿名6回・ログイン済み7回の時刻取得、ログの順序と文言、セッション読み取り位置を確認。
  最初のclock失敗はtry外で伝播し、その後のclock失敗は元の500応答となる。
- 大会なしは元の500・print。大会/Post/Vote/Comment取得、ログ、セッション、整形、JSON
  変換の失敗も元の500・print。取得処理にcommit/rollback/countを追加していない。
- 全35 route + staticのURL map、factory・既定app・CLI名は既存契約と一致。
  `ScriptInfo(app_import_path="app:app").load_app()` が既定appを解決し、WSGI経由の
  `/api/me` とCLI登録（`process-contests`・`update-user-stats`・`db`）も成功。
- 全10モデルのmetadata・DDL・リレーションはsnapshotと一致し、一時SQLiteの基準スキーマに
  対するAlembic自動生成差分はゼロ。
- 元ソース全文比較・独立AST比較・`git diff --check`: 成功。

ローカルは一時仮想環境 `netatwi-issue3-venv` の **Python 3.12.14**。
一時SQLite・外部サービスfake・ネットワーク拒否fixtureで実DBと実サービスから隔離した。
Windows上ではGunicornプロセスを起動せず、入口解決とWSGIリクエストを確認した。
PostgreSQLや本番migrationには接続していない。既存の非推奨警告は残る。
Python 3.11の結果はPRのGitHub Actionsで確認する。

## コミット・対象外・戻し方

1. 元コードで成功した特性テストを保存。
2. 検証済みのservice抽出・HTTP/logger fake接続を保存。
3. 抽出再現・比較スクリプトと本記録を保存。

SQL・表示条件・投票やカウンタの判定・ログ・例外応答の改善、投稿CRUDのロジック変更、
他のAPIの抽出、共通依存整理、`app/` への配置移動、DB migration、フロントエンド変更は
含めない。API契約・DB schema・外部設定に変更はなく、特別なデプロイ順は不要。
問題があればこのPRをまとめてrevertし、処理本体とテスト接続を元へ戻せる。
