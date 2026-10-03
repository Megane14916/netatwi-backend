# Issue #13: 投稿・画像処理の service 抽出

計画書の「順 10」の投稿・画像領域。PR #37 取り込み後の `origin/master`
(`7586a37`) から `refactor/13-post-image-services` を作成した。

## 変更範囲

- `services/posts.py`: 作成・編集の入力検証、期間・進出・重複・所有者判定、
  画像保存／削除の調整、DB 更新と投稿数カウンタ更新。
- `integrations/images.py`: 拡張子判定、R2 client 作成、R2／ローカル画像保存・削除。
- `blueprints/posts.py`: HTTP 入力、service 呼び出し、JSON 応答への変換。
  元の例外処理・rollback と成功時の応答式を保持。投稿一覧の関数は変更しない。
- `app.py`: 4つの画像ヘルパーを互換入口として保持。呼び出しごとに元の設定・
  logger・R2 client callback を integration に渡す。設定読み込みとディレクトリ
  作成のタイミングは保持し、Flask context 外での画像ヘルパー呼び出しも可能。
- 時刻の fake の差し替え先を投稿 service に移す。画像操作は既存の遅延参照
  adapter を通すため、`app.py` の helper／設定の差し替え方を保持する。

元のソースを AST の行番号で機械的に切り出した。AST から処理を再生成していない。
画像ヘルパーの本体はコメントを含めてコピーし、元の識別子を保つため設定を
同名の keyword 引数として受け取る。service では `jsonify` を除去して戻り値の
境界を調整し、成功時の Post または応答用の値・ステータスを route に返す。
移動前に try の外にあった検証は移動後も try の外から呼ぶ。

## 同等性の比較

```powershell
python docs/refactor/verify_issue_13_extraction.py
python -m pytest -q -p no:cacheprovider
```

検証スクリプトは基準コミットと比較し、5つの service 関数について戻り値の
明示的な調整だけを許容して AST の一致を確認する。4つの画像 integration 関数は
引数追加を除いた AST と、本体のソーステキストが一致することを確認する。
route の引数・デコレータ・HTTP 入力・応答式・例外ハンドラ、投稿一覧の全処理も
比較する。`app.py` は4つの互換 wrapper と関連 import の変更だけを許容し、
それ以外の文・初期化順序・ストレージ設定が一致することを確認する。

## 検証結果

- 移動前の既存テスト: **119 passed**。
- 移動前に追加した投稿・画像の特性テスト: **29 passed**。
- 移動後の全テスト: **148 passed**。
- ログイン、入力、期間の開始／終了境界、必須画像、進出、重複、所有者の判定を確認。
- 作成時は4枚を超える画像を拒否し、編集時は5枚でも保存する元の扱いを確認。
- 作成時の文字数・改行の扱い、編集時の文字数検証・改行正規化を確認。
- 画像必須でも名前のある不許可拡張子は保存されず作成が成功する元の扱いを確認。
- 編集時の不正な `kept_images` JSON の扱い、R2／ローカル保存・削除を確認。
- 編集時は画像アップロード、古い画像削除、commit の順序を確認。
- 削除時は画像、Vote、Comment、Notification、Bookmark、ContestResult、Post、
  カウンタ更新の順序と、画像削除例外を無視して継続する扱いを確認。
- 作成・編集・削除の commit 失敗時は DB を rollback し、先行した画像の副作用は
  元のまま残ることを確認。投稿数ゼロ時に削除してもカウンタを負にしない。
- R2 アップロード例外は再送出、R2 削除例外はログ記録して終了する扱いを確認。
- 全35 route と static の URL map、factory、`app:app`、CLI 名が既存契約と同等。
- 全10モデルの metadata・DDL・リレーションが snapshot と一致。
  一時 SQLite の基準スキーマに対する Alembic 差分ゼロ。
- 機械比較スクリプト、`git diff --check`: 成功。

ローカルは一時仮想環境 `netatwi-issue3-venv` の Python 3.12.14 を使用。
外部通信は fake とネットワーク拒否 fixture で隔離した。
Python 3.11 は PR の既存 GitHub Actions で確認する。
既存の SQLAlchemy・protobuf の非推奨警告は残る。

## コミットの区切り

1. 投稿・画像の特性テストを追加し、移動前に成功を確認。
2. service／integration への抽出と時刻 fake の差し替え先を更新し、全テストを確認。
3. 機械比較スクリプトと検証記録を保存。

## 対象外・戻し方

画像検証ルール、保存先、削除順序、カウンタ更新、トランザクション境界は変更しない。
画像と DB の整合性改善、バリデーション改善、投稿一覧の抽出は含まない。
DB migration、フロントエンド変更、特別なデプロイ順は不要。
問題があれば PR の3コミットをまとめて revert し、元の配置に戻せる。
