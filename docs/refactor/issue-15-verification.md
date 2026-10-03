# Issue #15: 結果集計と表示データ構築の service 抽出

計画書の「順 10」の集計・結果表示領域。PR #39 取り込み後の `origin/master`
(`bd07352`) から `refactor/15-results-service` を作成した。

## 変更範囲

- `services/results.py`: `generate_contest_results`、`get_cached_contest_results`、
  結果 API の期間判定と表示データ構築。
- `blueprints/results.py`: セッション読取、service 呼び出し、JSON 応答への変換。
  元の例外処理・標準出力・traceback を保持。
- `blueprints/tasks.py` と `cli/process_contests.py`: 同じ結果 service の集計関数を呼ぶ。
  通知・flag・commit・再実行の処理は変更しない。
- `blueprints/profile.py`: 保存済み結果の取得先を同じ service に切り替える。
  表示ロジックは変更しない。
- `app.py`: 2つの集計・取得ヘルパーの引数・docstring・戻り値を保つ互換 wrapper。
  それ以外の文と初期化順序を保持。
- 固定時刻と既存 task／CLI テストの集計 fake の差し替え先を service に移す。

元のソースを AST の行番号で機械的に切り出した。AST から処理を再生成していない。
集計・取得の2関数は全文をコピーし、表示データ構築はコメントを含めてコピーする。
表示処理から `jsonify` を除去し、元の通常応答に既定の200を明示した tuple を
返すことだけを戻り値の境界として調整する。route の try 内から呼ぶ位置を保持し、
集計内の bulk 保存・commit／rollback の境界もそのまま保持する。
service は Flask の HTTP 応答やセッションに依存せず、呼び出し元が利用中の
共通 DB session を使う。

## 同等性の比較

```powershell
python docs/refactor/verify_issue_15_extraction.py
python -m pytest -q -p no:cacheprovider
```

検証スクリプトは基準コミットと比較し、集計・取得の2関数が全文・AST とも一致する
ことを確認する。表示データ構築は、明示した HTTP 戻り値調整以外は本体ソース・AST
が一致することを確認する。service module の import・JST 定義も比較する。
route の引数・デコレータ・セッション読取・JSON 変換・例外ハンドラ、`app.py` の
互換 wrapper とそれ以外の文・初期化順序も比較する。
task・CLI・プロフィールは import と service 呼び出し先だけ、既存テストは
時刻・集計 fake の差し替え先だけが変わったことを比較する。

## 検証結果

- 移動前の既存テスト: **187 passed**。
- 移動前に追加した集計・表示の特性テスト: **16 passed**。
- 移動後の全テスト: **203 passed**。
- 既存の採点方式、一般投票者のユニーク数、スコア丸め、同点順位、進出、審査員賞、
  再実行の特性テストを通過。丸め後の同点順位と整数の進出 cutoff の扱いも追加確認。
- 大会なし・一部でも結果保存済みの場合は書き込まず、空大会は毎回 bulk 保存と
  commit を行う元の扱いを確認。
- bulk 保存失敗は伝播し、commit 失敗は rollback・標準出力後に戻ることを確認。
- 集計 commit 失敗を握りつぶした後も、task／CLI が通知・flag を別 commit で
  保存することを確認。既存の通知順序・commit 回数・再実行テストも通過。
- 結果 API は終了時刻から公開する。空大会の JSON はカウンタを0にし、
  `totalJudges` を含まない元の形を保持することを確認。
- 結果が一部未保存でも HTTP は集計せず、保存済みの順位・点数・進出フラグと
  未保存投稿の `rank: null`・`score: 0` を返す。結果の順序、JST、カウンタ、
  匿名閲覧の反応フラグを確認。
- 既存の審査員賞・投票者・ブックマーク・コメントを含む JSON の特性テストを通過。
  審査員賞タブには別大会の投稿も含み、`is_judge_vote` で絞らない元の扱いを確認。
- 大会なしの結果 API は元どおり500と標準出力・traceback を返す。読取経路に
  新しい commit／rollback を追加していないことを確認。
- 全35 route と static の URL map、factory、`app:app`、CLI 名が既存契約と同等。
- 全10モデルの metadata・DDL・リレーションが snapshot と一致。
  一時 SQLite の基準スキーマに対する Alembic 差分ゼロ。
- 機械比較スクリプト、`git diff --check`: 成功。

ローカルは一時仮想環境 `netatwi-issue3-venv` の Python 3.12.14 を使用。
外部通信は fake とネットワーク拒否 fixture で隔離した。
Python 3.11 は PR の既存 GitHub Actions で確認する。
既存の SQLAlchemy・protobuf の非推奨警告は残る。

## コミットの区切り

1. 集計・表示の特性テストを追加し、移動前に成功を確認。
2. service 抽出・呼び出し先と fake の変更を保存し、全テストを確認。
3. 機械比較スクリプトと検証記録を保存。

## やってないこと・戻し方

採点式、同点順位、進出条件、commit 境界、結果 JSON は変更しない。
集計の再設計・最適化、保存済み結果の再集計、対象投稿・参照整合性、
例外処理の改善、task／CLI のライフサイクル処理の抽出は含まない。
DB migration、フロントエンド変更、特別なデプロイ順は不要。
問題があれば PR の3コミットをまとめて revert し、元の配置と呼び出し先に戻せる。
