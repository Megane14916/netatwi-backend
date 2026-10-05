"""Register the extracted commands on each Flask application."""

from .process_contests import process_contests_command
from .user_stats import update_user_stats


COMMANDS = (process_contests_command, update_user_stats)


def register_cli(application):
    for command in COMMANDS:
        application.cli.add_command(command)
