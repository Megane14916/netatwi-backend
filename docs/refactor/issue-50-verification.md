# Issue #50: 共通ヘルパーの移動とservicesからBlueprintへの依存解消

計画書の順10-8。PR #61のマージを確認し、最新の `origin/master`
(`46d312ee22f1990e6ab194c26f8ba941621f18e7`) から
`refactor/50-shared-helper-dependencies` を作成した。
依存する #43〜#49 はすべて取り込み済み。着手時に未取り込みPRはなく、
`master` のブランチ保護は無効。

## 調査と抽出範囲

画像の保存・削除・R2 client生成の処理本体は #13で `integrations/images.py` に移動済み。
app.pyの画像関数は現在の設定・logger・client callbackを渡す薄い互換入口なので維持する。
文字数計算、画像設定の初期化、アプリごとの遅延callback接続を以下へ配置した。
処理本体はASTの行範囲で特定し、コメントを含む元ソースをコピーした。
`ast.unparse` による処理本体の再生成は行っていない。

| 元の範囲 | 移動先・接続 | 保持する性質 |
| --- | --- | --- |
| app.py:calculate_weighted_length | services/text.py、app.pyで同じ名前を再公開 | 正規表現・URL23文字・改行正規化・文字重み・例外 |
| app.py:UPLOAD_FOLDER〜R2_PUBLIC_URLの初期化 | integrations/images.py:initialize_image_settings | 元の場所で一度実行し、5値をappのglobalsへ返す |
| blueprints/dependencies.pyの全文 | runtime_dependencies.py | current_app経由の呼出しとLocalProxy logger |
| services/contest_lifecycle.py:schedule_contest_task | runtime_dependencies.py、service側で同じ名前を再公開 | アプリのextension callbackを呼出し時に取得 |
| app.py:_register_extracted_routesの先頭2文 | runtime_dependencies.py:register_helper_bindings | logger・helper・schedulerの遅延解決、extensionのキーと登録順 |
| posts/voting service、voting routeの共通依存import | runtime_dependenciesへ向ける | 同じhelper/proxyを共有し、servicesからBlueprintをimportしない |
| blueprints/dependencies.pyの旧入口 | runtime_dependenciesから薄く再公開 | private _callも含む既存のhelper名・オブジェクト同一性 |

許可した構造変更は、上記の移動・import先変更・再公開、画像初期化結果のtuple返却と受取、
callbackの名前参照を `namespace[名前]` に置き換える接続だけ。
app.pyは `globals()` の辞書そのものをbinderへ渡し、各lambda内で呼出し時に値を取得する。
登録時にlogger/helper/schedulerをキャプチャせず、app.pyの後からの差し替えや
直接起動時の `__main__` に相当する名前空間を保持する。
loggerの生成元・生成時点、文字数計算で使う標準re、画像保存先・拡張子集合を保持する。

画像の環境変数は `create_base_app()` とlogger/JST設定の後、元と同じ位置で読み込む。
makedirs → USE_R2 → R2_BUCKET_NAME → R2_PUBLIC_URLの順序を維持する。
`create_app(config)` で画像設定を読み直したり、ディレクトリを作り直したりしない。
画像のapp側設定値とR2 client callback・loggerは各画像呼出し時に渡す。
R2処理・Cloud Tasks処理、client cache、結果helper、CLI、全routeの本体は変更しない。
factoryの整理は #51、appパッケージへの配置は #52で扱う。

## 機械比較

`extract_issue_50.py` は固定した基準の元ソース行から9ファイルを生成し、全文一致を確認する。
`--write` はこの抽出の再現専用で、後続Issueの変更には使用しない。
`verify_issue_50_extraction.py` は独立して元ASTへ上記の許可した変更だけを適用する。
文字数関数・画像初期化・共通helper・scheduler・binderの本体ソースとAST、
app/common/text/image/service/routeのモジュール全体を比較する。
画像の既存ファイル全体が元と一致するprefixであること、互換ラッパー・factoryの
全文一致、servicesにBlueprint importがないことも確認する。

新しい特性テストは元コードで成功したコミット
`771211d25e37889700d64d703b614b34f9146d9b` と全文一致し、移動に合わせた期待値変更はない。
変更対象の既存7ファイルを除くすべての既存Pythonファイルは基準と全文一致する。
この比較は #50の抽出時点に対応し、後続Issueでは新しい基準を使う。

```powershell
$pythonExe = "$env:TEMP\netatwi-issue3-venv\Scripts\python.exe"
& $pythonExe docs/refactor/extract_issue_50.py
& $pythonExe docs/refactor/verify_issue_50_extraction.py
& $pythonExe -m pytest -q -p no:cacheprovider --disable-warnings --tb=short
git diff --check origin/master HEAD
```

## 検証結果

- 移動前の既存テスト: **581 passed**。
- 元コードで追加した特性テスト: **34 passed**。移動前の全テスト: **615 passed**。
- 移動後の全テスト: **615 passed**、371件の既存警告。
- 文字数計算のfalsy入力、truthy非文字列の例外、ASCII/日本語/emoji、
  0x80・0x81、0xF8F0と隣接文字、半角範囲境界、改行正規化、URLの長さ/大小文字/
  Unicodeと区切り文字を確認。
- 6つのhelper、posts/votingからの文字数・画像呼出し、logger・schedulerの
  登録後差し替えを確認。現在のアプリに応じたextensionの切り替え、contextなしの
  RuntimeError、loggerのアクセスごとの解決を確認。
- 画像ラッパーが現在の5設定値・client callback・loggerをそのまま渡し、
  接続時にclientを生成しないことを確認。
- app.pyを別の名前空間で実行し、初期化順と回数、USE_R2の大小文字・空白の扱い、
  公開URLの末尾slash除去、factoryでの非再初期化、名前空間内の後からの差し替え、
  loggerの元のモジュール名を確認。
- 既存の画像ローカル保存/削除、R2 fake、Cloud Tasks fake・キャッシュ・時刻・URL・
  例外、各APIのHTTP/DB/commit/rollback/副作用の契約テストも成功。
- 新規Pythonプロセスでposts/voting/contest_lifecycleだけをimportし、
  appやBlueprintをimportしないことを確認。schedulerの互換aliasも同一。
- app.pyの文字数関数と移動先、旧dependenciesと共通moduleの全helper/proxyは同一。
- 全35 route + staticのURL map、factory、CLI名は既存snapshotと一致。
  Flaskのapp:app入口解決、WSGIの/api/meリクエストとCLI登録を別途確認。
- 全10モデルのmetadata・DDL・リレーションはsnapshotと一致し、
  一時SQLite基準スキーマに対するAlembic自動生成差分はゼロ。
- 再現スクリプトの全文比較・独立ソース/AST比較・git diff --checkは成功。

ローカルは一時仮想環境 `netatwi-issue3-venv` の **Python 3.12.14**。
一時SQLite・外部fake・ネットワーク拒否fixtureで実DB・実サービスから隔離した。
WindowsではGunicornプロセスは起動せず、入口解決とWSGIリクエストを確認した。
PostgreSQLや本番migrationには接続していない。Python 3.11はPRのGitHub Actionsで確認する。

## コミット・対象外・戻し方

1. 元コードで成功した34件の特性テストを保存。
2. 検証済みの共通依存・文字数・画像初期化の抽出と互換接続を保存。
3. 抽出再現・独立比較スクリプトと本記録を保存。

文字数・画像規則・SQL・時刻・ログ・例外・callback/client cacheの仕様変更、
画像とDBの整合性改善、権限/期間判定の共通化、DIの全面再設計、factory再設計、
appパッケージ移動、DB migration、フロントエンド変更は含めない。
API契約・DB schema・外部設定の変更はなく、特別なデプロイ順は不要。
問題があればこのPRをまとめてrevertして処理本体と接続を元の位置へ戻せる。
