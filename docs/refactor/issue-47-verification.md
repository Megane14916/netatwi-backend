# Issue #47: プロフィールの取得・表示データ構築の service 抽出

計画書の順10-5。PR #58のマージを確認し、最新の `origin/master`
(`b523da12e4d7650329b3e21d217578122ed79221`) から
`refactor/47-profile-services` を作成した。依存する #9・#15・#46 は取り込み済み。
着手時点で未取り込みPRはなく、`master` のブランチ保護は無効。

## 抽出範囲と対応

元の `blueprints/profile.py:get_user_profile_updated` のAST行範囲を使い、
コメントを含むソースをコピーした。処理本体を `ast.unparse` で再生成していない。

| 元の範囲 | 抽出先 `services/profile.py` | routeに残す処理 |
| --- | --- | --- |
| 計測開始・前回時刻・内部 `log_step` 定義 | `prepare_profile_timing(time)` | 元の位置でtimeをimport、helper呼び出し後にsessionを読む |
| ユーザー取得・退会判定、投稿/ブックマーク/いいね、公開判定、閲覧者情報、結果・整形 | `get_user_profile(screen_name, viewer_id, log_step)` | screen_nameとviewer_idを渡す、JSON/HTTP変換 |

内部の `log_step` は時刻・nonlocal更新・printをそのまま保持し、クロージャとして返す。
計測開始、session読み取り、target_user取得の順序を維持する。
`filter_posts`・`format_posts_fast` も元の内部関数のままコピーし、共通化・再設計しない。
JST・モデル・joinedload・results serviceの参照を移し、新しいserviceからHTTPやrouteを
importしていない。元のtry・except・print・`traceback.print_exc()` はrouteに残す。

許可した構造上の変更:

- 計測準備helperから元の `log_step` を返し、後半の処理へ渡す。
- 元の404 returnと最後の成功returnだけから `jsonify` を外し、payload/statusを返す。
  成功時の暗黙200を明示200にする。routeで同じpayloadをJSON変換する。
- 必要な引数・import・抽出範囲のインデントを調整する。
- 既存fixtureのdatetime fakeと追加テストのquery_module importをserviceへ接続する。

内部helperのreturnは変換しない。SQL・eager load・順序・条件式・日時変換・画像参照・
結果取得・request内cache・ログ文言と計測式を保持する。

## 機械比較

`extract_issue_47.py` は固定した元ソース行から生成するservice・route・fixture・追加テストと
ファイル全文を比較する。`--write` はこの抽出の再現専用で、後続Issueの変更には使わない。
`verify_issue_47_extraction.py` は独立して元ASTに上記の接続変更だけを適用し、2関数の
本体ソース・AST・引数、service全体のimport・JST、routeモジュール全体を比較する。
内部関数・そのreturn・routeの例外境界も含めて一致を確認する。

追加テストの本体・期待値は元コードで成功したコミット
`fed9d0657709e0d56d759a0e8dd16a44d02248c5` と一致する。
routeとfixture以外の既存Pythonファイルはすべて基準と全文一致し、結果serviceや他のAPIを
変更していない。この比較・記録は #47 の抽出時点を対象とし、後続Issueは新しい基準を使う。

```powershell
$pythonExe = "$env:TEMP\netatwi-issue3-venv\Scripts\python.exe"
& $pythonExe docs/refactor/extract_issue_47.py
& $pythonExe docs/refactor/verify_issue_47_extraction.py
& $pythonExe -m pytest -q -p no:cacheprovider --disable-warnings --tb=short
git diff --check origin/master HEAD
```

## 検証結果

- 移動前の既存テスト: **408 passed**。
- 元コードで追加した特性テスト: **47件**。移動前の全テスト: **455 passed**。
- 移動後の全テスト: **455 passed**。
- 匿名・本人・他ユーザー・審査員・退会済み閲覧者の応答を確認。
  投稿・ブックマーク・いいねの各リスト、JSONキー・型・JST、保存済みカウンタを保持。
- 投稿は投稿時刻降順、ブックマークはBookmark作成時刻降順、いいねはVote作成時刻降順。
  いいねは一般投票かつ正のcountだけを表示し、0・負数・審査員投票は除く。
- 投票終了の1マイクロ秒前は非公開、時点と直後は公開。3リストに同じ条件を適用する。
  本人でも結果期間前の投稿を公開しない。
- 対象ユーザーが存在しない・退会済み・大文字小文字が違う場合は元の404で止まり、
  投稿以降のqueryを実行しない。退会済みの関連投稿者・投票者の情報は元どおり表示する。
- None/0/空文字のviewer_idでは閲覧者queryを省略し、存在しないtruthyなIDでは取得する。
  myVotesは閲覧者本人の票だけを返し、0点をNoneに置き換えない。
  ブックマークも対象ユーザーと閲覧者を分けて取得する。
- 投票者は審査員を先頭に並べる。審査員賞は保存済み結果のフラグでなくVoteの賞フラグを
  読み、一般投票者の賞フラグも元どおり表示する。has_theme=Falseでもthemeを返す。
- 結果なしの投稿はrank=None・score=0。保存結果のrank/scoreを返し再集計しない。
  同じ大会の結果取得は3リストで1回にまとめ、request内だけ再利用する。
  次のrequestではDBの結果変更を反映する。
- 全リストが空または結果期間前だけの場合、投票・賞・閲覧者BMのbulk取得と結果取得を
  省略する。queryとresults service呼び出しの順序・回数を確認。
- 計測開始後・最初のquery前にsessionを読む。表示データありのrequestのclock取得10回と
  9段階の性能ログ文言・時間差の計算を確認。
- 最初を含む各clock、対象/投稿/BM/いいね/投票/賞/閲覧者BMのquery、保存結果、datetime、
  filter、整形、session、JSON（404の変換を含む）、性能printの失敗は元の500・print・
  tracebackとなる。commit/rollback/countを追加していない。
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
2. 検証済みのservice抽出・HTTP/datetime fake接続を保存。
3. 抽出再現・比較スクリプトと本記録を保存。

公開範囲・soft delete・並び順・結果/票/賞の表示規則・JSONの変更、queryや結果cacheの改善、
整形の共通化、性能ログ・例外処理の改善、他APIの抽出、共通依存整理、`app/` への配置移動、
DB migration、フロントエンド変更は含めない。
API契約・DB schema・外部設定に変更はなく、特別なデプロイ順は不要。
問題があればこのPRをまとめてrevertし、処理本体とfakeの接続を元へ戻せる。
