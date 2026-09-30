# Issue #10: 投票・結果・交流 API の Blueprint 移動

対象は計画書の「順 8」。最新の `origin/master` (`900cbaa`) から
`refactor/10-voting-results-interactions-blueprints` を作成した。

## 変更範囲

12 ハンドラを `voting`、`results`、`interactions`、`comments`、
`notifications`、`users` の 6 モジュールへ移動した。
既存の `LegacyEndpointBlueprint` で URL と非修飾の endpoint 名を維持する。
文字数計算と保存済み結果の読み取りは既存の依存アダプタを利用する。
投票ハンドラの logger は元の `app.py` の logger を遅延参照する。
時刻固定 fixture の差し替え先を移動後のモジュールにも追加した。

## 機械的な抽出と同等性確認

一時 Python スクリプトで AST の行番号から元ソースを切り出し、
`@app.route` を `@bp.route` に置換した。関数本体を AST から再生成していない。
関数定義・本体・内部コメントの文字列は元ソースと一致する。

次の読み取り専用スクリプトで、12 関数の文字列、デコレータ以外の AST、
route の引数が `900cbaa:app.py` と一致することを再確認できる。
残る 17 関数も logger の依存登録 1 行を除き AST が一致する。

```powershell
python docs/refactor/verify_issue_10_extraction.py
python -m pytest -q -p no:cacheprovider
```

## 検証結果

- 変更前の既存テスト: **72 passed**。
- 移動前に追加した API 特性テスト: **8 passed**。
- 移動後の全テスト（Blueprint 登録元の検証 1 件を含む）: **81 passed**。
- URL map: 全 35 route と static route が既存 snapshot と一致。
- `app:app` の import、factory 生成、CLI 名を既存の起動契約テストで確認。
- 全 10 モデルの metadata・DDL・リレーションが既存 snapshot と一致。
- 一時 SQLite の基準スキーマに対する Alembic 差分: **ゼロ**。
- `git diff --check`: 成功。

ローカル実行は既存の一時仮想環境 `netatwi-issue3-venv` の Python 3.12.14 を使用。
Python 3.11 の GitHub Actions はこの作業では未実行。
既存の SQLAlchemy と protobuf の非推奨警告が残る。

## やってないこと・戻し方

サービス層への抽出、採点式・投票条件・カウンタ・SQL・例外処理の変更、
モデル・DB migration・外部サービス設定の変更は含まない。
フロントエンド変更や特別なデプロイ順は不要。
変更をまとめたコミットを revert することで元の登録場所に戻せる。
