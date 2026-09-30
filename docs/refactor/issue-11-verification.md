# Issue #11: Cloud Tasks ハンドラと CLI コマンドの分割

計画書の「順 9」。PR #35 取り込み後の `origin/master` (`6f52a0d`) から
`refactor/11-tasks-cli-modules` を作成した。

## 変更範囲

- `handle_contest_task` を `blueprints/tasks.py` へ移動。
- `process_contests_command` を `cli/process_contests.py` へ移動。
- `update_user_stats` を `cli/user_stats.py` へ移動。
- task は既存の `LegacyEndpointBlueprint`、CLI は元と同じ
  Flask の `AppGroup.command` を使い、production app と factory app に登録する。
- `app.py` の3つの互換名は import で維持。集計は既存の依存アダプタを通じて
  `app.py` の関数を実行時に参照し、既存の差し替え方も維持する。
- 時刻固定 fixture に移動先を追加。

Cloud Tasks の送信・スケジュール設定と集計関数は `app.py` に残す。

## 機械的な抽出と再検証

一時 Python スクリプトで AST の行番号から元ソースを切り出し、
デコレータの登録先だけを変更した。AST から関数本体を再生成していない。
定義・本体・内部コメントの文字列、デコレータ以外の AST、登録引数が一致する。
残る14関数とその他の `app.py` の文も、明示した import・依存登録・CLI 登録の
追加を除き AST が一致する。

```powershell
python docs/refactor/verify_issue_11_extraction.py
python -m pytest -q -p no:cacheprovider
```

## 検証結果

- 変更前の既存テスト: **81 passed**。
- 移動前に追加した特性テスト: **15 passed**。
- 移動後の全テスト（登録元・互換名の検証1件を含む）: **97 passed**。
- 副作用の実行順、task のイベント別コミット回数、CLI の結果保存・大会通知・
  古い通知削除のコミット順を確認。再実行時に余分なコミットがないことも確認。
- 全イベントの時刻境界、通知削除の30日境界、削除失敗時の rollback、
  集計失敗の伝播、ユーザー統計の集計・同順位・再実行・空データを確認。
- 事前のアプリケーションコンテキストなしでも両 CLI が正常に実行される。
- URL map（task を含む全35 route と static）、`app:app`、factory、CLI 名が同等。
- 全10モデルの metadata・DDL・リレーションが snapshot と一致。
  一時 SQLite の基準スキーマに対する Alembic 差分ゼロ。
- `git diff --check`: 成功。

ローカルは既存の一時仮想環境 `netatwi-issue3-venv` の Python 3.12.14 を使用。
Python 3.11 は PR の既存 GitHub Actions で確認する。
既存の SQLAlchemy・protobuf の非推奨警告は残る。

## やってないこと・戻し方

サービス層への抽出、通知タイミング・受信者・冪等性・コミット回数・SQL・
統計の集計式・例外処理の改善、task の呼出元認証追加は含まない。
モデル・migration・外部サービス設定・フロントエンドの変更も含まない。
特別なデプロイ順や DB migration は不要。本変更を revert すれば元の登録位置に戻せる。
