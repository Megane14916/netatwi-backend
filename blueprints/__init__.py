"""Route groups extracted from app.py."""

from .admin import bp as admin_bp
from .auth import bp as auth_bp
from .contests import bp as contests_bp
from .news import bp as news_bp
from .posts import bp as posts_bp
from .profile import bp as profile_bp


BLUEPRINTS = (
    auth_bp,
    admin_bp,
    news_bp,
    contests_bp,
    posts_bp,
    profile_bp,
)
