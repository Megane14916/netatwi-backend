import os
import sys

# アプリケーションのルートディレクトリをパスに追加
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.extensions import db
from app.models import Post, Comment

def sync_comment_counts():
    print("コメント数の同期処理を開始します...")
    application = create_app()
    with application.app_context():
        # 全ての投稿を取得
        posts = Post.query.all()
        updated_count = 0

        for post in posts:
            # 該当投稿のコメント数を取得
            actual_comment_count = Comment.query.filter_by(post_id=post.id).count()
            
            # ズレがある場合のみ更新
            if post.comment_count != actual_comment_count:
                print(f"投稿ID {post.id}: {post.comment_count} -> {actual_comment_count} に更新")
                post.comment_count = actual_comment_count
                updated_count += 1
        
        # 変更を保存
        if updated_count > 0:
            db.session.commit()
            print(f"完了: {updated_count} 件の投稿のコメント数を更新しました。")
        else:
            print("完了: 更新が必要な投稿はありませんでした。")

if __name__ == "__main__":
    sync_comment_counts()
