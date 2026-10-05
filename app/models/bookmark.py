from datetime import datetime, timezone
from .base import db


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
