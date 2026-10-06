from datetime import datetime, timezone
from app.extensions import db


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True, nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True, nullable=True)
    type = db.Column(db.String(50), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), index=True, nullable=True)
    contest_id = db.Column(db.Integer, db.ForeignKey('contest.id'), index=True, nullable=True)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (db.Index('idx_user_is_read', 'user_id', 'is_read'),)

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('notifications', lazy=True))
    sender = db.relationship('User', foreign_keys=[sender_id])
    post = db.relationship('Post', backref=db.backref('notifications', lazy=True))
    contest = db.relationship('Contest', backref=db.backref('notifications', lazy=True))
