# Issue #16: 大会ライフサイクルの service 抽出

計画書の「順 10」の大会ライフサイクル領域。PR #40 取り込み後の `origin/master`
(`77b88fc`) から `refactor/16-contest-lifecycle` を作成した。

## 変更範囲

- `services/contest_lifecycle.py`: 大会作成・更新・削除、更新前の大会取得、予定作成の
  調整、task のイベント処理、`process-contests` の大会イベント・通知・cleanup 処理。
- `integrations/cloud_tasks.py`: Cloud Tasks の予定時刻・URL・request 作成と SDK 呼び出し。
  元の遅延生成・再利用する client cache を関数と一緒に移す。
- `blueprints/admin.py`: 元の認証・HTTP 入力・JSON 応答・例外処理を保持し service を呼ぶ。
  更新前の大会取得は元と同じく JSON 読取と try より前。管理一覧 API は変更しない。
- `blueprints/tasks.py`: service の返す payload・ステータスを JSON 応答へ変換する。
- `cli/process_contests.py`: 元の CLI 名・callback・docstring を保ち service を呼ぶ。
- `app.py`: `schedule_contest_task` の引数・戻り値を保つ互換 wrapper。それ以外の
  文・初期化順序を保持し、アプリに登録した予定作成 callback も保持する。
- 時刻と client cache の fake を service／integration に移す。

元のソースを AST の行番号で機械的に切り出した。AST から処理を再生成していない。
CRUD・task の本体はコメントもコピーし、`jsonify` の除去だけを HTTP 戻り値の境界
として調整する。CLI 本体と予定作成関数は元の処理をそのままコピーする。
予定作成の service 内の接続は、元のアプリ callback を使う遅延参照 helper を
コピーして維持する。既存の `app.py` の scheduler 差し替えも引き続き有効。
通知・結果集計・flag 更新をまとめ直さず、task と CLI それぞれの処理を維持する。

## 同等性の比較

```powershell
python docs/refactor/verify_issue_16_extraction.py
python -m pytest -q -p no:cacheprovider
```

基準コミットと比較し、5つの CRUD・task・CLI 関数は HTTP 戻り値の明示的な調整
以外の本体ソース・AST の一致を確認する。予定作成の遅延参照 helper と大会取得
helper の境界も比較する。Cloud Tasks の関数は全文・AST が一致し、client cache の
初期値・service／integration の import が明示したものと一致することを確認する。
管理認証・HTTP 入力・応答変換・例外境界、管理一覧、task URL・デコレータ、CLI 名・
callback・docstring、`app.py` の互換 wrapper とそれ以外の文も比較する。
テストは、固定時刻と client cache の fake の接続先だけの変更であることを確認する。

## 検証結果

- 移動前の既存テスト: **203 passed**。
- 移動前に追加した大会・予定作成の特性テスト: **22 passed**。
- 移動後の全テスト: **225 passed**。
- 通常／予選・決勝の作成、親子リンク、全設定、予選時刻の fallback と明示指定を確認。
  通常大会作成では進出率を保存しない元の扱いも保持。
- commit 後に3予定、予選ありでは予選の3予定から決勝の3予定へ進む順序を確認。
- 不正入力・JSON `null`・commit 失敗は rollback し予定を作成しない。commit 後の
  scheduler 例外は500と rollback になるが、先に commit された大会は残ることを確認。
- 更新可能フィールド、theme と hasTheme の組み合わせ、数値0／文字列0、審査員賞の
  alias の優先順序、結果コメント、通知 flag をリセットしない扱いを確認。
- 空の更新でも commit・3予定の再作成を行い、大会なしは JSON の解析より先に404と
  なることを確認。更新・削除の commit 失敗時は元の DB データを維持することを確認。
- 削除は Vote、Post、ORM による ContestResult、大会の順。画像は削除せず、
  SQLite fixture では Bookmark・Comment と子大会が残る元の扱いを確認。
  本番 DB の参照整合性の改善は含まない。
- 予定時刻の10秒加算、naive／時差付き日時、過去時刻の補正、補正後が現在時刻と
  同じ場合は再補正しない境界、URL・POST・headers・protobuf Timestamp を確認。
- 設定欠落時の skip、GCR_URL fallback と末尾 slash、client の遅延生成と再利用を確認。
  create_task 失敗は標準出力後に戻り、queue_path 失敗は伝播する元の境界を確認。
- 既存 task／CLI の時刻境界、通知・結果保存・flag 更新・commit 回数・再実行・
  cleanup の境界・失敗・CLI 自身の app context の特性テストを通過。
- 全35 route と static の URL map、factory、`app:app`、CLI 名が既存契約と同等。
- 全10モデルの metadata・DDL・リレーションが snapshot と一致。
  一時 SQLite の基準スキーマに対する Alembic 差分ゼロ。
- 機械比較スクリプト、`git diff --check`: 成功。

ローカルは一時仮想環境 `netatwi-issue3-venv` の Python 3.12.14 を使用。
外部通信は fake とネットワーク拒否 fixture で隔離した。
Python 3.11 は PR の既存 GitHub Actions で確認する。
既存の SQLAlchemy・protobuf の非推奨警告は残る。

## コミットの区切り

1. 大会・予定作成の特性テストを追加し、移動前に成功を確認。
2. service／integration 抽出と fake の接続先変更を保存し、全テストを確認。
3. 機械比較スクリプトと検証記録を保存。

## やってないこと・戻し方

大会の状態遷移、通知時刻、タスク再スケジュール、削除対象、commit 境界を変更しない。
task 認証、二重実行対策、参照整合性、通知処理の統合、エラー処理・入力検証の改善は
含まない。管理一覧や公開大会一覧 API の抽出も含まない。
DB migration、フロントエンド変更、特別なデプロイ順は不要。
問題があれば PR の3コミットをまとめて revert し、元の配置と接続先に戻せる。
