from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# ユーザーモデル (変更なし)
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    twitter_id = db.Column(db.String(80), unique=True, nullable=False)
    screen_name = db.Column(db.String(80), nullable=False)
    profile_image_url = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    # Relationships added for clarity, using back_populates for explicit control
    posts = db.relationship('Post', back_populates='user', lazy=True)
    votes = db.relationship('Vote', back_populates='user', lazy=True)
    bookmarks = db.relationship('Bookmark', back_populates='user', lazy=True, cascade="all, delete-orphan")

# 大会モデル (更新)
class Contest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    theme = db.Column(db.Text, nullable=True) # お題なしを許可
    status = db.Column(db.String(20), nullable=False, default='upcoming')
    
    # 既存の時間は「決勝」または「通常」の時間とする
    start_time = db.Column(db.DateTime, nullable=False) # 通常:投稿開始 / 予選あり: 決勝投稿開始
    end_time = db.Column(db.DateTime, nullable=False) # 通常:投稿終了 / 予選あり: 決勝投稿終了
    voting_end_time = db.Column(db.DateTime, nullable=False) # 通常:投票終了 / 予選あり: 決勝投票終了
    
    judge_vote_ratio = db.Column(db.Integer, nullable=False, default=2)
    judge_password = db.Column(db.String(120), nullable=True)
    has_theme = db.Column(db.Boolean, nullable=False, default=True)
    has_qualifier = db.Column(db.Boolean, nullable=False, default=False)
    allow_images = db.Column(db.Boolean, nullable=False, default=True)

    # --- ▼▼▼ 予選用の時刻カラムを追加 ▼▼▼ ---
    qualifier_start_time = db.Column(db.DateTime, nullable=True) # 予選投稿開始
    qualifier_end_time = db.Column(db.DateTime, nullable=True)   # 予選投稿終了
    qualifier_voting_end_time = db.Column(db.DateTime, nullable=True) # 予選投票終了
    # --- ▲▲▲ ここまで ▲▲▲ ---

    posts = db.relationship('Post', back_populates='contest', lazy=True)
    votes = db.relationship('Vote', back_populates='contest', lazy=True)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    contest_id = db.Column(db.Integer, db.ForeignKey('contest.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # Relationships - use back_populates
    user = db.relationship('User', back_populates='posts', lazy=True)
    contest = db.relationship('Contest', back_populates='posts', lazy=True)
    votes = db.relationship('Vote', back_populates='post', lazy=True)
    bookmarks = db.relationship('Bookmark', back_populates='post', lazy=True, cascade="all, delete-orphan")



class Vote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    count = db.Column(db.Integer, nullable=False, default=0)
    is_judge_vote = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    contest_id = db.Column(db.Integer, db.ForeignKey('contest.id'), nullable=False)
    # Relationships - use back_populates
    user = db.relationship('User', back_populates='votes', lazy=True)
    post = db.relationship('Post', back_populates='votes', lazy=True)
    contest = db.relationship('Contest', back_populates='votes', lazy=True)

    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='uq_user_post_vote'),)

    is_judge_award = db.Column(db.Boolean, nullable=False, default=False) # 審査員賞かどうか
    judge_comment = db.Column(db.Text, nullable=True) # 審査員コメント
# --- ▲▲▲ ここまで ▲▲▲ ---

class Bookmark(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationships
    user = db.relationship('User', back_populates='bookmarks', lazy=True)
    post = db.relationship('Post', back_populates='bookmarks', lazy=True)

    # user_id と post_id の組み合わせでユニーク制約
    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='uq_user_post_bookmark'),)