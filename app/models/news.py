from datetime import datetime, timezone
from app.extensions import db


class News(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tweet_id = db.Column(db.String(80), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
