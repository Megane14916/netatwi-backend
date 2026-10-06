from datetime import datetime, timezone
import json
from app.extensions import db


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
                data = json.loads(self.image_urls)
                if isinstance(data, dict) and data.get("netatwi_image_manifest") == 1:
                    return data["urls"]
                return data
            except:
                return []
        return []

    @images.setter
    def images(self, value):
        owned = self.owned_images
        if value:
            self.image_urls = json.dumps(
                {"netatwi_image_manifest": 1, "urls": value,
                 "owned": [url for url in owned if url in value]}
                if owned else value
            )
        else:
            self.image_urls = None

    @property
    def owned_images(self):
        """Legacy URL lists are readable, but do not prove upload ownership."""
        try:
            data = json.loads(self.image_urls or "null")
            if isinstance(data, dict) and data.get("netatwi_image_manifest") == 1:
                return [url for url in data.get("owned", []) if url in data["urls"]]
        except (ValueError, TypeError, KeyError):
            pass
        return []

    def record_image_uploads(self, urls):
        """Called only for URLs returned by server-side uploads for this post."""
        images = self.images
        owned = list(dict.fromkeys(self.owned_images + [url for url in urls if url in images]))
        if owned:
            self.image_urls = json.dumps({"netatwi_image_manifest": 1, "urls": images, "owned": owned})
