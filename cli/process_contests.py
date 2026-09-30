"""Contest lifecycle batch command."""

from datetime import datetime, timedelta, timezone

from flask.cli import AppGroup

from blueprints.dependencies import generate_contest_results
from models import Contest, Notification, User, db


cli = AppGroup()


@cli.command("process-contests")
def process_contests_command():
    """定期実行バッチ: 大会の状態変化を検知して通知送信や結果集計を行う"""
    print("--- process-contests batch started ---")
    now = datetime.now(timezone.utc)
    contests = Contest.query.all()
    all_users = None

    for contest in contests:
        changed = False

        # 投稿開始
        if (
            contest.start_time
            and contest.start_time.replace(tzinfo=timezone.utc) <= now
            and not contest.notified_post_start
        ):
            print(f"[{contest.id}] Post start notification")
            if all_users is None:
                all_users = User.query.all()
            for u in all_users:
                db.session.add(
                    Notification(
                        user_id=u.id, type="contest_post_start", contest_id=contest.id
                    )
                )
            contest.notified_post_start = True
            changed = True

        # 投票開始
        if (
            contest.end_time
            and contest.end_time.replace(tzinfo=timezone.utc) <= now
            and not contest.notified_voting_start
        ):
            print(f"[{contest.id}] Voting start notification")
            if all_users is None:
                all_users = User.query.all()
            for u in all_users:
                db.session.add(
                    Notification(
                        user_id=u.id, type="contest_voting_start", contest_id=contest.id
                    )
                )
            contest.notified_voting_start = True
            changed = True

        # 結果発表
        if (
            contest.voting_end_time
            and contest.voting_end_time.replace(tzinfo=timezone.utc) <= now
            and not contest.notified_result_announce
        ):
            print(f"[{contest.id}] Result announce notification & calculation")
            generate_contest_results(contest.id)
            if all_users is None:
                all_users = User.query.all()
            for u in all_users:
                db.session.add(
                    Notification(
                        user_id=u.id,
                        type="contest_result_announce",
                        contest_id=contest.id,
                    )
                )
            contest.notified_result_announce = True
            changed = True

        if changed:
            db.session.commit()
            print(f"[{contest.id}] Committed changes")

    # --- 古い通知の自動削除 (30日経過) ---
    cutoff_date = now - timedelta(days=30)
    try:
        deleted_count = Notification.query.filter(
            Notification.created_at < cutoff_date
        ).delete(synchronize_session=False)
        if deleted_count > 0:
            db.session.commit()
            print(f"Deleted {deleted_count} old notifications (older than 30 days)")
    except Exception as e:
        db.session.rollback()
        print(f"Failed to delete old notifications: {e}")

    print("--- process-contests batch completed ---")
