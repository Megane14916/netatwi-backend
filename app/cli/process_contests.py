"""Contest lifecycle batch command."""

from flask.cli import AppGroup

from app.services import contest_lifecycle
from app.diagnostics import log_failure


cli = AppGroup()


@cli.command("process-contests")
def process_contests_command():
    """定期実行バッチ: 大会の状態変化を検知して通知送信や結果集計を行う"""
    try:
        return contest_lifecycle.process_contests()
    except Exception as error:
        log_failure("cli.process_contests", error)
        raise
