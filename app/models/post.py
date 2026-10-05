from datetime import datetime, timezone
import json
from .base import db


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
