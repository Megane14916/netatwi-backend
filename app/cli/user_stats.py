"""User statistics batch command."""

from flask.cli import AppGroup

from app.services import user_stats as user_stats_service
from app.diagnostics import log_failure


cli = AppGroup()


@cli.command("update-user-stats")
def update_user_stats():
    """Update UserStats table by aggregating ContestResult data"""
    try:
        return user_stats_service.update_user_stats()
    except Exception as error:
        log_failure("cli.update_user_stats", error)
        raise
