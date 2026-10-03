"""Contest lifecycle batch command."""

from flask.cli import AppGroup

from services import contest_lifecycle


cli = AppGroup()


@cli.command("process-contests")
def process_contests_command():
    """定期実行バッチ: 大会の状態変化を検知して通知送信や結果集計を行う"""
    return contest_lifecycle.process_contests()
