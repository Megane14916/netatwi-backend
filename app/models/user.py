from datetime import datetime, timezone
from .base import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    twitter_id = db.Column(db.String(80), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    screen_name = db.Column(db.String(80), unique=True, index=True, nullable=False)
    profile_image_url = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    deleted_at = db.Column(db.DateTime, nullable=True)
    # Relationships added for clarity, using back_populates for explicit control
    posts = db.relationship('Post', back_populates='user', lazy=True)
    votes = db.relationship('Vote', back_populates='user', lazy=True)
    bookmarks = db.relationship('Bookmark', back_populates='user', lazy=True, cascade="all, delete-orphan")
