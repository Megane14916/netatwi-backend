"""User statistics batch command."""

from flask.cli import AppGroup

from services import user_stats as user_stats_service


cli = AppGroup()


@cli.command("update-user-stats")
def update_user_stats():
    """Update UserStats table by aggregating ContestResult data"""
    return user_stats_service.update_user_stats()
