# 1. ベースとなる公式Pythonイメージを選択
FROM python:3.11-slim

# 2. 環境変数を設定
ENV PYTHONUNBUFFERED True
ENV APP_HOME /app
WORKDIR $APP_HOME
COPY . ./

# 3. 必要なパッケージをインストール
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# 4. コンテナ実行コマンド
# Cloud Runは環境変数 $PORT でリッスンするポートを指定してくる
# gunicornを 0.0.0.0:$PORT で起動
CMD exec gunicorn --bind "0.0.0.0:${PORT}" --workers 1 --threads 8 --timeout 0 "app:app"