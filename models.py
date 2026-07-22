from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
import json

db = SQLAlchemy()

# ユーザーモデル (変更なし)
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    twitter_id = db.Column(db.String(80), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    screen_name = db.Column(db.String(80), unique=True, index=True, nullable=False)
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
    
    general_vote_weight = db.Column(db.Integer, nullable=False, default=50) # 一般票の重み係数 (デフォルト50)
    judge_max_score = db.Column(db.Integer, nullable=False, default=10)

    judge_password = db.Column(db.String(120), nullable=True)
    has_theme = db.Column(db.Boolean, nullable=False, default=True)
    has_qualifier = db.Column(db.Boolean, nullable=False, default=False)
    allow_images = db.Column(db.Boolean, nullable=False, default=True)

    # --- ▼▼▼ 新規追加カラム (Phase 1) ▼▼▼ ---
    type = db.Column(db.String(20), nullable=False, default='grandprix')
    scoring_method = db.Column(db.String(20), nullable=False, default='both')
    image_rule = db.Column(db.String(20), nullable=False, default='optional')
    advancement_numerator = db.Column(db.Integer, nullable=True) # 予選通過率 (分子)
    advancement_denominator = db.Column(db.Integer, nullable=True) # 予選通過率 (分母)
    judge_award_advancement = db.Column(db.Boolean, nullable=False, default=False)
    parent_contest_id = db.Column(db.Integer, db.ForeignKey('contest.id'), index=True, nullable=True)
    is_voting_visible = db.Column(db.Boolean, nullable=False, default=True)

    result_comment_top = db.Column(db.Text, nullable=True)
    result_comment_bottom = db.Column(db.Text, nullable=True)
    
    # バッチ処理用の通知完了フラグ
    notified_post_start = db.Column(db.Boolean, nullable=False, default=False)
    notified_voting_start = db.Column(db.Boolean, nullable=False, default=False)
    notified_result_announce = db.Column(db.Boolean, nullable=False, default=False)

    # --- キャッシュスタンピード対策用カウンタ ---
    post_count = db.Column(db.Integer, nullable=False, default=0)
    total_voters = db.Column(db.Integer, nullable=False, default=0)
    total_judges = db.Column(db.Integer, nullable=False, default=0)

    children = db.relationship('Contest', backref=db.backref('parent', remote_side=[id]), lazy=True)
    # --- ▲▲▲ ここまで ▲▲▲ ---

    posts = db.relationship('Post', back_populates='contest', lazy=True)
    votes = db.relationship('Vote', back_populates='contest', lazy=True)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)

    image_urls = db.Column(db.Text, nullable=True) 
    comment_count = db.Column(db.Integer, nullable=False, default=0)
    bookmark_count = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    contest_id = db.Column(db.Integer, db.ForeignKey('contest.id'), index=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True, nullable=False)
    # Relationships - use back_populates
    user = db.relationship('User', back_populates='posts', lazy=True)
    contest = db.relationship('Contest', back_populates='posts', lazy=True)
    votes = db.relationship('Vote', back_populates='post', lazy=True)
    bookmarks = db.relationship('Bookmark', back_populates='post', lazy=True, cascade="all, delete-orphan")

    @property
    def images(self):
        if self.image_urls:
            try:
                return json.loads(self.image_urls)
            except:
                return []
        return []

    @images.setter
    def images(self, value):
        if value:
            self.image_urls = json.dumps(value)
        else:
            self.image_urls = None


class Vote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    count = db.Column(db.Float, nullable=False, default=0.0)
    is_judge_vote = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True, nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), index=True, nullable=False)
    contest_id = db.Column(db.Integer, db.ForeignKey('contest.id'), index=True, nullable=False)
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
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True, nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), index=True, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationships
    user = db.relationship('User', back_populates='bookmarks', lazy=True)
    post = db.relationship('Post', back_populates='bookmarks', lazy=True)

    # user_id と post_id の組み合わせでユニーク制約
    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='uq_user_post_bookmark'),)

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True, nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), index=True, nullable=False)
    content = db.Column(db.String(140), nullable=False)
    is_judge = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref=db.backref('comments', lazy=True))
    post = db.relationship('Post', backref=db.backref('comments', lazy=True))

    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='uq_user_post_comment'),)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True, nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True, nullable=True)
    type = db.Column(db.String(50), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), index=True, nullable=True)
    contest_id = db.Column(db.Integer, db.ForeignKey('contest.id'), index=True, nullable=True)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('notifications', lazy=True))
    sender = db.relationship('User', foreign_keys=[sender_id])
    post = db.relationship('Post', backref=db.backref('notifications', lazy=True))
    contest = db.relationship('Contest', backref=db.backref('notifications', lazy=True))

class ContestResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    contest_id = db.Column(db.Integer, db.ForeignKey('contest.id'), index=True, nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), index=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True, nullable=False)
    score = db.Column(db.Float, nullable=False, default=0.0)
    rank = db.Column(db.Integer, nullable=False)
    is_advanced = db.Column(db.Boolean, nullable=False, default=False)
    is_judge_award = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    contest = db.relationship('Contest', backref=db.backref('results', lazy=True, cascade="all, delete-orphan"))
    post = db.relationship('Post', backref=db.backref('results', lazy=True, cascade="all, delete-orphan"))
    user = db.relationship('User', backref=db.backref('results', lazy=True))

class UserStats(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    
    gp_1st = db.Column(db.Integer, nullable=False, default=0)
    gp_2nd = db.Column(db.Integer, nullable=False, default=0)
    gp_3rd = db.Column(db.Integer, nullable=False, default=0)
    
    daily_1st = db.Column(db.Integer, nullable=False, default=0)
    daily_2nd = db.Column(db.Integer, nullable=False, default=0)
    daily_3rd = db.Column(db.Integer, nullable=False, default=0)
    
    judge_awards = db.Column(db.Integer, nullable=False, default=0)
    
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref=db.backref('stats', uselist=False, lazy=True))

class News(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tweet_id = db.Column(db.String(80), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
