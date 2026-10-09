# テスト

pytest を使い、API・業務処理・DB 更新などを検証します。

## セットアップ

Python 3.11 を使用します。以下のコマンドは `netatwi-backend` のリポジトリ直下で実行してください。

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

macOS / Linux では `python3.11 -m venv .venv` で作成し、`source .venv/bin/activate` で有効化します。

## 実行方法

全テスト:

```sh
python -m pytest -q
```

ディレクトリやファイルを指定して実行できます。

```sh
python -m pytest -q tests/unit
python -m pytest -q tests/api
python -m pytest -q tests/integration
python -m pytest -q tests/unit/test_text_contract.py
```

## テスト構成

| パス | 対象 |
| --- | --- |
| `unit/` | 文字数計算・権限などの単体テスト |
| `api/` | HTTP レスポンス・認証・入力検証・DB 更新 |
| `integration/` | アプリ起動・CLI・モデル・集計・外部連携 |
| `snapshots/` | ルート・DB スキーマなどの比較用データ |
| `conftest.py` | 共通のテスト設定・fixture |

## CI

[GitHub Actions](../.github/workflows/tests.yml) で全テストを実行します。PostgreSQL の並行処理テストは、専用ジョブの使い捨て PostgreSQL 16 で検証します。

ローカルでは `TEST_POSTGRESQL_URI` が未設定の場合、PostgreSQL 専用テストはスキップされます。
