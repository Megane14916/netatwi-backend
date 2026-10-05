from datetime import datetime, timezone
from .base import db


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
