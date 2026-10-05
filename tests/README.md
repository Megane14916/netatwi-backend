# テストの実行

Dockerfile と同じ Python 3.11 を使い、新しい仮想環境を作成する。既存の `venv` は別の場所で作られている場合があるため、再利用を前提にしない。

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
```

macOS／Linux では `python3.11 -m venv .venv` を実行し、以後は `.venv/bin/python` を使う。テストは `app` の import 前に安全な環境変数を設定し、fixture で `create_app` に一時 SQLite DB などの設定を渡す。外部ネットワーク接続を拒否し、X API、R2、Cloud Tasks には fake を使うため、本番の `.env` や実サービスの資格情報は不要。

GitHub Actions も Python 3.11 で同じ `python -m pytest -q` を実行する。

## 配置と収集

リポジトリ直下から実行する。pytestは下記3ディレクトリを再帰的に収集する。
`tests/conftest.py` は全分類に共通で、環境変数・一時SQLite・固定時刻・外部fake・
ネットワーク拒否の設定を保持する。分類ごとにfixtureを複製しない。

| 配置 | 対象 | #53時点のケース数 |
| --- | --- | --- |
| tests/unit/ | 文字数計算の正常入力・従来の例外。計算自体はHTTP・DB・外部clientを使わない | 19 |
| tests/api/ | Flask test clientによるHTTP・session・権限・期間・JSON・DB副作用の契約 | 479 |
| tests/integration/ | factory/WSGI/CLI/直接起動/import、モデル・Alembic、保存型集計、外部境界・cache・複数経路 | 147 |
| tests/snapshots/ | URL map、DDL、リレーションの固定資料。pytestのケースではない | — |

HTTPとCLI、画像保存等の複数の境界を扱う混合ファイルはintegrationに置く。
集計テストはDBへ結果を保存するためintegrationに置き、分類のために純粋関数へ書き換えない。
unitも共通conftestの安全なアプリ初期化は読み込むが、各ケースでDB fixtureを要求しない。
全体で **645件**。既存のテストを削除・skipせず、パラメータ・本体・期待値を保持している。

```powershell
.\.venv\Scripts\python.exe -m pytest --collect-only -q tests
.\.venv\Scripts\python.exe -m pytest -q tests/unit
.\.venv\Scripts\python.exe -m pytest -q tests/api
.\.venv\Scripts\python.exe -m pytest -q tests/integration
.\.venv\Scripts\python.exe -m pytest -q
```

一時ディレクトリを作れない制限環境では、Git管理外の専用領域を明示できる。
`--basetemp`の指定先はpytestが再作成するため、必要なファイルを置かない。

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.venv/pytest-temp
```

## 配置変更の検証と履歴

#53の比較はマージ済み#52の `23dbc5bc8acbc070bbfdacc63626e45a55c0e184` を基準とする。

```powershell
.\.venv\Scripts\python.exe docs/refactor/extract_issue_53.py
.\.venv\Scripts\python.exe docs/refactor/verify_issue_53_extraction.py
.\.venv\Scripts\python.exe docs/refactor/check_issue_53_collection.py
```

抽出scriptの通常実行は39ファイルの全文再現を確認する。独立比較はsource/AST・
snapshot・共通fixtureとアプリ本体の保持を確認する。収集比較は分類前のnode IDへ正規化し、
645ケースのID全体のhashと元ファイルごとの件数を照合する。
`--write`は移動の再現、`--record-baseline`は移動前コミットでの記録専用であり、通常は使わない。

#3〜#52の抽出・比較scriptは各Issue完了時点の配置を対象にした歴史的資料である。
現在のcheckoutで古いscriptを実行して、旧パスが存在しないことを回帰と判断しない。
必要なら該当PRの完了commitを別checkoutで検証する。元の基準SHA・実行環境・許可した
変更は各 `docs/refactor/issue-<番号>-verification.md` に残している。
現在の配置・全体監査は [#53検証記録](../docs/refactor/issue-53-verification.md) を参照する。
