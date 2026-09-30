"""Route groups extracted from app.py."""

from .admin import bp as admin_bp
from .auth import bp as auth_bp
from .comments import bp as comments_bp
from .contests import bp as contests_bp
from .interactions import bp as interactions_bp
from .news import bp as news_bp
from .notifications import bp as notifications_bp
from .posts import bp as posts_bp
from .profile import bp as profile_bp
from .results import bp as results_bp
from .tasks import bp as tasks_bp
from .users import bp as users_bp
from .voting import bp as voting_bp


BLUEPRINTS = (
    auth_bp,
    admin_bp,
    news_bp,
    contests_bp,
    posts_bp,
    profile_bp,
    voting_bp,
    results_bp,
    interactions_bp,
    comments_bp,
    notifications_bp,
    users_bp,
    tasks_bp,
)
