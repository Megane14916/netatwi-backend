from datetime import datetime, timezone
from .base import db


class UserStats(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    rank = db.Column(db.Integer, nullable=False, default=99999)

    gp_1st = db.Column(db.Integer, nullable=False, default=0)
    gp_2nd = db.Column(db.Integer, nullable=False, default=0)
    gp_3rd = db.Column(db.Integer, nullable=False, default=0)

    daily_1st = db.Column(db.Integer, nullable=False, default=0)
    daily_2nd = db.Column(db.Integer, nullable=False, default=0)
    daily_3rd = db.Column(db.Integer, nullable=False, default=0)

    judge_awards = db.Column(db.Integer, nullable=False, default=0)

    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref=db.backref('stats', uselist=False, lazy=True))
