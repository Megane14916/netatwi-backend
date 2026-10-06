from datetime import datetime, timezone
from app.extensions import db


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True, nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), index=True, nullable=False)
    content = db.Column(db.Text, nullable=False)
    is_judge = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref=db.backref('comments', lazy=True))
    post = db.relationship('Post', backref=db.backref('comments', lazy=True))

    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='uq_user_post_comment'),)
