import os
import sys
import csv
from unittest.mock import MagicMock

# app.pyのインポート前にモック化と環境変数の設定を行う
sys.modules['boto3'] = MagicMock()
neon_db_url = os.environ.get('NEON_DB_URL')
if not neon_db_url:
    print("エラー: 環境変数 NEON_DB_URL が設定されていません。")
    sys.exit(1)
os.environ['SQLALCHEMY_DATABASE_URI'] = neon_db_url

from app import app
from models import db, User

def import_csv(file_path):
    if not os.path.exists(file_path):
        print(f"エラー: {file_path} が見つかりません。ファイル名を '{file_path}' にするか、スクリプト内のファイル名を修正してください。")
        return

    print(f"'{file_path}' からデータを読み込んでいます...")
    with app.app_context():
        try:
            with open(file_path, mode='r', encoding='utf-8-sig') as f: # utf-8-sig はBOM付きUTF-8(Excel等)にも対応
                reader = csv.DictReader(f)
                count = 0
                for row in reader:
                    # CSVのヘッダー名が完全に一致していることを前提としています
                    # 万が一ヘッダー名が異なる場合（大文字など）は row.get('カラム名') を調整してください
                    user = User(
                        id=int(row['id']) if row.get('id') else None,
                        twitter_id=row.get('twitter_id'),
                        screen_name=row.get('screen_name'),
                        name=row.get('name'),
                        profile_image_url=row.get('profile_image_url')
                    )
                    db.session.add(user)
                    count += 1
            
            db.session.commit()
            print(f"✅ {count} 件のユーザーデータをNeon DBにインポートしました！")
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ インポート中にエラーが発生しました: {e}")

if __name__ == '__main__':
    # 同じディレクトリに配置したCSVファイルの名前を指定
    csv_file = 'users.csv' 
    import_csv(csv_file)
