"""Route groups extracted from app.py."""

from .admin import bp as admin_bp
from .auth import bp as auth_bp
from .news import bp as news_bp


BLUEPRINTS = (auth_bp, admin_bp, news_bp)
