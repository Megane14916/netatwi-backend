"""Register and export the ten canonical database models."""

from .user import User
from .contest import Contest
from .post import Post
from .vote import Vote
from .bookmark import Bookmark
from .comment import Comment
from .notification import Notification
from .contest_result import ContestResult
from .user_stats import UserStats
from .news import News

__all__ = [
    "User",
    "Contest",
    "Post",
    "Vote",
    "Bookmark",
    "Comment",
    "Notification",
    "ContestResult",
    "UserStats",
    "News",
]
