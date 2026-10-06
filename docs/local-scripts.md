# ローカルの補助スクリプト

個人用のデータ生成・調査・補正スクリプトは、リポジトリ直下の `scripts/` にまとめる。
このディレクトリはGit管理とDockerのビルドコンテキストから除外する。
新しいcloneやCI・コンテナには補助スクリプトを配布しない。

## 今回の移動と追跡解除

以下のルート直下のファイルを、名前を変えずに `scripts/` へ移動した。

- `sync_comment_counts.py`
- `generate_dummy_data.py`
- `generate_dummy_gp_result.py`
- `calc_result.py`
- `patch.py`

既存の `scripts/sync_comment_count.py`、`scripts/recalculate_contest_stats.py`、
`scripts/audit_image_ownership.py` も同じ場所に残す。
コメント数同期の2本は今回統合せず、各処理を保持する。

追跡済みだった `sync_comment_counts.py` と `scripts/audit_image_ownership.py` は、
ローカルのファイルを残してGitの追跡だけを解除した。
残りは元からGit管理外のため、移動後の内容はPRの差分に含まれない。
今回のローカル変更は配置とimport用のパスだけで、データ処理を変更しない。

## 他のcheckoutへの適用

この変更を取り込む前に、追跡済みだった2本をGit管理外の場所へコピーして保存する。
取り込み後、保存したファイルを `scripts/` に置き、ルートに残る管理外の4本も移動する。
取り込みによって追跡対象の2本が削除されるため、手元に残したい場合は先に退避する。
元の追跡ファイルはコミット `27e062aba467897340548f045e399d680387078a` の
`sync_comment_counts.py` と `scripts/audit_image_ownership.py` からも復元できる。

ルートから移した `sync_comment_counts.py`、データ生成の2本、`calc_result.py` は、
`app` をimportする前にリポジトリルートをPythonの検索パスへ追加する。
既存の `sync_comment_counts.py` のパス追加処理は、次の処理に置き換える。

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
```

## 実行と検証

作業ディレクトリは `netatwi-backend` のルートにする。
例えばコメント数同期は `python scripts/sync_comment_counts.py`、
画像所有記録の調査は `python scripts/audit_image_ownership.py` で実行する。
DBへ接続するスクリプトは、実行前に接続先と対象データを確認する。
`patch.py` は旧monolithic `app.py` を書き換える過去の作業用スクリプトであり、
現在のアプリを保守する入口として使わない。

CIは配布対象のアプリ・WSGI・CLI・業務契約を検証する。
Git管理外のスクリプトの存在を必須にしていたテスト1件は撤去した。
補助スクリプトの変更時は、手元で構文・importを確認し、データ更新の検証には
一時DBなどの隔離環境を使う。
過去の `docs/refactor/` の検証記録・移行パッチは、その時点の配置を示す資料として保持する。
