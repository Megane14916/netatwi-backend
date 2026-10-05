# Issue #49: ユーザー一覧・退会のservice抽出と残るrouteのBlueprint移動

計画書の順10-7。PR #60のマージを確認し、最新の `origin/master`
(`5708ab6431b63a541aa256cb5feb980d2aa167ec`) から
`refactor/49-user-account-services` を作成した。依存する #10・#12・#17 は取り込み済み。
着手時点で未取り込みPRはなく、`master` のブランチ保護は無効。

## 抽出範囲・対応表

ASTの行範囲で元ソースを特定し、コメントを含めてコピーした。
処理本体を `ast.unparse` で再生成していない。

| 元の範囲 | 移動先 | HTTP側に残す処理 |
| --- | --- | --- |
| `blueprints/users.py` の遅延import 2文 | `services/users.py:get_directory_dependencies()` | HTTP入力を読む前に依存を取得 |
| 一覧の100件指定・join・検索・ページング・統計整形 | `services/users.py:get_users_list(search_query, page, User, UserStats, asc)` | q/page読取・JSON変換・200 |
| `app.py:withdraw_user` のユーザー取得・存在判定・日時設定・commit | `services/users.py:withdraw_user(user_id)` | 認証・session読取・エラーJSON・成功後のsession.clear・成功JSON |
| `app.py:get_current_user/logout` | `blueprints/account.py` | 元の関数本体をそのまま移動 |
| `app.py:withdraw_user` のHTTP接続 | `blueprints/account.py` | 上記のserviceを元の位置で呼ぶ |
| `app.py:index` | `blueprints/core.py` | 元のテキスト応答をそのまま移動 |

許可した構造上の変更:

- 一覧の遅延importをhelperに移し、元と同じHTTP入力前に一度実行する。
  その時点で解決したUser/UserStats/ascを取得処理に渡す。未使用のdesc/funcのimportも保持。
- 一覧の外側returnからjsonifyを外し、payload/statusをrouteへ返す。
- 退会のユーザーなしreturnからjsonifyを外し、成功時はNoneを返す。
  routeはエラーなら元の404、成功なら元のsession.clearとJSON応答を実行する。
- 移動する4つのdecoratorのappをbpへ変更し、LegacyEndpointBlueprintでendpoint名を維持。
- account/coreをBLUEPRINTSの先頭に追加する。既定appでは元の4 routeと既存routeの登録順を維持。
- app.pyで4つの元の関数名を移動先から再公開し、重複定義しない。
- 固定時刻fakeをserviceにも接続し、追加テストのaccount/withdrawal importだけを変更する。

元のSQL・条件・順序・eager load・100件・error_out=False・JSONキー/型、管理者名判定、
セッション読取/更新、UTC日時設定・commitを保持する。退会にexcept/rollbackを追加しない。
新serviceはHTTP・route・appをimportしない。
app.pyのfactory、登録helper、CLI、画像helper、文字数計算、直接起動の本体は変更しない。
factoryの不足routeコピー方式を整理する #51 や、配置をappパッケージに統一する #52 は別作業。

## 機械比較

`extract_issue_49.py` は固定した元ソース行から8ファイルを生成し、全文一致を確認する。
`--write` はこの抽出の再現専用で、後続Issueの変更には使わない。
`verify_issue_49_extraction.py` は独立して元ASTへ上記の接続変更だけを適用する。
3つのserviceの本体ソース・AST・引数、service全体、account/core/usersのroute全体、
app.py全体とBLUEPRINTS登録全体を比較し、対象外のfactory等も含めて保持を確認する。
me/logoutの本体ソースも元と一致する。

追加テストの本体・期待値は、元コードで成功したコミット
`36e46765c16d3dc18a37f18237a55cb61d299fef` と一致する。
対象の4つの既存Pythonファイル以外はすべて基準と全文一致する。
この比較・記録は #49 の抽出時点を対象とし、後続Issueは新しい基準を使う。

```powershell
$pythonExe = "$env:TEMP\netatwi-issue3-venv\Scripts\python.exe"
& $pythonExe docs/refactor/extract_issue_49.py
& $pythonExe docs/refactor/verify_issue_49_extraction.py
& $pythonExe -m pytest -q -p no:cacheprovider --disable-warnings --tb=short
git diff --check origin/master HEAD
```

## 検証結果

- 移動前の既存テスト: **527 passed**。
- 元コードで追加した特性テスト: **54 passed**。移動前の全テスト: **581 passed**。
- 移動後の特性テスト: **54 passed**。移動後の全テスト: **581 passed**。
- 実DBの205ユーザーでrank昇順/name昇順、100件/100件/5件、範囲外ページを確認。
  0/負数/不正値/空pageは元の1扱い、複数page値は先頭を使う。
  deleted_at非NULLと統計なしユーザーは元のinner join/filterで除外する。
- name/screen_name/twitter_idの検索、大文字小文字、SQL wildcard、空白をtrimしない扱い、
  検索後の空ページ・空結果を確認。全JSON項目と7つの統計項目を保持。
  統計なしの整形guardはpaginate fakeで確認し、実DBのjoinを変更しない。
- 遅延import → q → page → paginateの順序とpage/per_page/error_outを確認。
  一覧のquery/JSON失敗は元どおり伝播し、commit/rollbackを追加しない。
- meはDBを読まずsessionを返す。user_idの真偽でなくキーの存在を見て、
  judge_for_contest_idsの値をそのまま返す。screen_name欠損のKeyErrorも維持。
  管理者の既定値/空設定/trim/大小文字、sessionの任意値保持を確認。
- logoutはログイン有無にかかわらずOAuth・審査員情報等を含むsession全体を消す。
- 退会は匿名401・ユーザーなし404でsessionを保持し、commitしない。
  None/0のIDでも元のキー存在判定を経てユーザー取得する。
- 退会成功は固定UTC時刻を設定しcommit1回、その後session全体を消す。
  退会済みでも時刻を更新する。投稿・票・BM・コメント・結果・統計・通知と
  大会/投稿のカウンタを保持する。
- 退会のquery/datetime/commit失敗は元どおり例外が伝播し、sessionを消さない。
  commit後のsession.clear/JSON失敗でも退会更新は残る。rollbackを追加していない。
- トップは元の日本語テキスト・200・text/htmlを返す。
  4関数のappからの互換importは、既定app/factoryに登録された同じ関数オブジェクト。
  url_forの結果も維持する。
- 全35 route + staticのURL mapは既存snapshotと一致。
  既定app/factory両方で全35 handlerがBlueprintモジュール由来であることを確認。
  factory・CLI名、app:appの入口解決、WSGIの/api/meも成功。
- 全10モデルのmetadata・DDL・リレーションはsnapshotと一致し、一時SQLite基準スキーマに
  対するAlembic自動生成差分はゼロ。
- ソース全文比較・独立AST比較・git diff --check: 成功。

ローカルは一時仮想環境 `netatwi-issue3-venv` の **Python 3.12.14**。
一時SQLite・外部fake・ネットワーク拒否fixtureで実DBと実サービスから隔離した。
WindowsではGunicornプロセスを起動せず、入口解決とWSGIリクエストを確認した。
PostgreSQLや本番migrationには接続していない。既存の非推奨警告は残る。
Python 3.11の結果はPRのGitHub Actionsで確認する。

## コミット・対象外・戻し方

1. 元コードで成功した特性テストを保存。
2. 検証済みのservice抽出・Blueprint移動・互換公開とfake接続を保存。
3. 抽出再現・比較スクリプトと本記録を保存。

検索対象・soft delete・統計なし・ページング・並び順・認証・退会・sessionの仕様変更、
認証再設計・データ削除や整合性改善・権限共通化、factory再設計、共通依存整理、
appパッケージ移動、DB migration、フロントエンド変更は含めない。
API契約・DB schema・外部設定に変更はなく、特別なデプロイ順は不要。
問題があればこのPRをまとめてrevertし、処理本体・route・登録・fakeを元へ戻せる。
