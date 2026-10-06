from datetime import datetime, timezone
from app.extensions import db


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
