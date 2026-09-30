# テストの実行

Dockerfile と同じ Python 3.11 を使い、新しい仮想環境を作成する。既存の `venv` は別の場所で作られている場合があるため、再利用を前提にしない。

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
```

macOS／Linux では `python3.11 -m venv .venv` を実行し、以後は `.venv/bin/python` を使う。テストは `app` の import 前に安全な環境変数を設定し、fixture で `create_app` に一時 SQLite DB などの設定を渡す。外部ネットワーク接続を拒否し、X API、R2、Cloud Tasks には fake を使うため、本番の `.env` や実サービスの資格情報は不要。

GitHub Actions も Python 3.11 で同じ `python -m pytest -q` を実行する。
