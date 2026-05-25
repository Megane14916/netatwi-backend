import os
import sys
from unittest.mock import MagicMock
# マイグレーションのみ実行するため、boto3が存在しなくてもエラーにならないようモック化します
sys.modules['boto3'] = MagicMock()

neon_db_url = os.environ.get('NEON_DB_URL')
if not neon_db_url:
    print("エラー: 環境変数 NEON_DB_URL が設定されていません。")
    sys.exit(1)

# ★ app をインポートする前に環境変数を上書きして、確実にNeon DBに向けさせる
os.environ['SQLALCHEMY_DATABASE_URI'] = neon_db_url

from sqlalchemy import create_engine, text
from app import app
from models import db
from flask_migrate import stamp

def create_tables():
    print("データベースのスキーマをリセットしています...")
    engine = create_engine(neon_db_url)
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE;"))
        conn.execute(text("CREATE SCHEMA public;"))
        conn.commit()

    with app.app_context():
        print("テーブルを新規作成しています...")
        db.create_all()
        
        try:
            # 今後も flask db migrate が使えるように履歴を最新状態にスタンプする
            stamp()
            print("Alembicのマイグレーション履歴を最新に更新しました。")
        except Exception as e:
            print(f"Alembicスタンプ中に警告: {e}")
            
        print("✅ すべてのテーブルの作成が完了しました！")

if __name__ == "__main__":
    create_tables()
