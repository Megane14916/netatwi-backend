"""Contest CRUD, timed events and lifecycle batch orchestration.

HTTP conversion and admin exception handlers stay in their original routes.
Scheduling uses the existing application callback, which reaches the Cloud
Tasks integration using the active application configuration.
"""

from datetime import datetime, timedelta, timezone
from functools import wraps

from app.integrations import cloud_tasks

from app.extensions import db
from app.models import Bookmark, Comment, Contest, ContestResult, Notification, Post, User, Vote
from app.services import results as results_service




def get_contest(id):
    return Contest.query.get(id)


def create_contest(data):
    has_qualifier = data.get("hasQualifier", False)

    # 通常/決勝の時刻をパース
    start_time_utc = datetime.fromisoformat(
        data["startTime"].replace("Z", "+00:00")
    )
    end_time_utc = datetime.fromisoformat(data["endTime"].replace("Z", "+00:00"))
    voting_end_time_utc = datetime.fromisoformat(
        data["votingEndTime"].replace("Z", "+00:00")
    )

    has_theme = data.get("hasTheme", True)
    theme_value = data.get("theme") if has_theme else None

    c_type = data.get("type", "grandprix")
    scoring_method = data.get("scoringMethod", "both")
    image_rule = data.get("imageRule", "optional")
    is_voting_visible = data.get("isVotingVisible", True)
    advancement_numerator = (
        int(data.get("advancementNumerator"))
        if data.get("advancementNumerator")
        else None
    )
    advancement_denominator = (
        int(data.get("advancementDenominator"))
        if data.get("advancementDenominator")
        else None
    )
    general_vote_weight = int(data.get("generalVoteWeight", 50))
    judge_max_score = int(data.get("judgeMaxScore", 10))
    judge_password = data.get("judgePassword")

    if has_qualifier:
        q_start_str = data.get("qualifierStartTime")
        q_end_str = data.get("qualifierEndTime")
        q_voting_end_str = data.get("qualifierVotingEndTime")

        q_start_time_utc = (
            datetime.fromisoformat(q_start_str.replace("Z", "+00:00"))
            if q_start_str
            else start_time_utc
        )
        q_end_time_utc = (
            datetime.fromisoformat(q_end_str.replace("Z", "+00:00"))
            if q_end_str
            else end_time_utc
        )
        q_voting_end_time_utc = (
            datetime.fromisoformat(q_voting_end_str.replace("Z", "+00:00"))
            if q_voting_end_str
            else voting_end_time_utc
        )

        qualifier_contest = Contest(
            name=f"{data['name']} 予選",
            theme=data.get("qualifierTheme")
            if data.get("qualifierHasTheme")
            else None,
            has_theme=data.get("qualifierHasTheme", False),
            has_qualifier=False,
            type=c_type,
            scoring_method=data.get("qualifierScoringMethod", "both"),
            image_rule=data.get("qualifierImageRule", "optional"),
            advancement_numerator=advancement_numerator,
            advancement_denominator=advancement_denominator,
            is_voting_visible=data.get("qualifierIsVotingVisible", True),
            start_time=q_start_time_utc,
            end_time=q_end_time_utc,
            voting_end_time=q_voting_end_time_utc,
            judge_award_advancement=data.get(
                "qualifierJudgeAwardAdvancement", False
            ),
            general_vote_weight=int(data.get("qualifierGeneralVoteWeight", 50)),
            judge_max_score=int(data.get("qualifierJudgeMaxScore", 10)),
            judge_password=data.get("qualifierJudgePassword"),
        )
        db.session.add(qualifier_contest)
        db.session.flush()  # ID取得のため

        final_contest = Contest(
            name=f"{data['name']} 決勝",
            theme=theme_value,
            has_theme=has_theme,
            has_qualifier=True,
            type=c_type,
            scoring_method=scoring_method,
            image_rule=image_rule,
            parent_contest_id=qualifier_contest.id,
            is_voting_visible=is_voting_visible,
            start_time=start_time_utc,
            end_time=end_time_utc,
            voting_end_time=voting_end_time_utc,
            judge_award_advancement=data.get("judgeAwardAdvancement", False),
            general_vote_weight=general_vote_weight,
            judge_max_score=judge_max_score,
            judge_password=judge_password,
        )
        db.session.add(final_contest)
        db.session.commit()

        # Cloud Tasksのスケジュール
        cloud_tasks.schedule_contest_task(
            qualifier_contest.id, "post_start", qualifier_contest.start_time
        )
        cloud_tasks.schedule_contest_task(
            qualifier_contest.id, "voting_start", qualifier_contest.end_time
        )
        cloud_tasks.schedule_contest_task(
            qualifier_contest.id,
            "result_announce",
            qualifier_contest.voting_end_time,
        )

        cloud_tasks.schedule_contest_task(
            final_contest.id, "post_start", final_contest.start_time
        )
        cloud_tasks.schedule_contest_task(
            final_contest.id, "voting_start", final_contest.end_time
        )
        cloud_tasks.schedule_contest_task(
            final_contest.id, "result_announce", final_contest.voting_end_time
        )

        return (
            {
                "message": "Contests created successfully",
                "id": final_contest.id,
                "qualifier_id": qualifier_contest.id,
            }
        ), 201

    else:
        new_contest = Contest(
            name=data["name"],
            theme=theme_value,
            has_theme=has_theme,
            has_qualifier=False,
            type=c_type,
            scoring_method=scoring_method,
            image_rule=image_rule,
            is_voting_visible=is_voting_visible,
            start_time=start_time_utc,
            end_time=end_time_utc,
            voting_end_time=voting_end_time_utc,
            judge_award_advancement=data.get("judgeAwardAdvancement", False),
            general_vote_weight=general_vote_weight,
            judge_max_score=judge_max_score,
            judge_password=judge_password,
        )
        db.session.add(new_contest)
        db.session.commit()

        cloud_tasks.schedule_contest_task(new_contest.id, "post_start", new_contest.start_time)
        cloud_tasks.schedule_contest_task(new_contest.id, "voting_start", new_contest.end_time)
        cloud_tasks.schedule_contest_task(
            new_contest.id, "result_announce", new_contest.voting_end_time
        )

        return (
            {"message": "Contest created successfully", "id": new_contest.id}
        ), 201


def update_contest(contest, data):
    if "name" in data:
        contest.name = data["name"]
    if "theme" in data:
        contest.theme = data["theme"] if data.get("hasTheme") else None
    if "hasTheme" in data:
        contest.has_theme = data["hasTheme"]
    if "type" in data:
        contest.type = data["type"]
    if "scoringMethod" in data:
        contest.scoring_method = data["scoringMethod"]
    if "imageRule" in data:
        contest.image_rule = data["imageRule"]
    if "isVotingVisible" in data:
        contest.is_voting_visible = data["isVotingVisible"]
    if "advancementNumerator" in data:
        contest.advancement_numerator = (
            int(data["advancementNumerator"])
            if data["advancementNumerator"]
            else None
        )
    if "advancementDenominator" in data:
        contest.advancement_denominator = (
            int(data["advancementDenominator"])
            if data["advancementDenominator"]
            else None
        )
    if "generalVoteWeight" in data:
        contest.general_vote_weight = int(data["generalVoteWeight"])
    if "judgeMaxScore" in data:
        contest.judge_max_score = int(data["judgeMaxScore"])
    if "judgePassword" in data:
        contest.judge_password = data["judgePassword"]

    # 時刻の更新 (ISOフォーマットを想定)
    if "startTime" in data:
        contest.start_time = datetime.fromisoformat(
            data["startTime"].replace("Z", "+00:00")
        )
    if "endTime" in data:
        contest.end_time = datetime.fromisoformat(
            data["endTime"].replace("Z", "+00:00")
        )
    if "votingEndTime" in data:
        contest.voting_end_time = datetime.fromisoformat(
            data["votingEndTime"].replace("Z", "+00:00")
        )

    # コメントの更新
    if "resultCommentTop" in data:
        contest.result_comment_top = data["resultCommentTop"]
    if "resultCommentBottom" in data:
        contest.result_comment_bottom = data["resultCommentBottom"]

    # 審査員賞での決勝進出設定の更新
    if "judgeAwardAdvancement" in data:
        contest.judge_award_advancement = data["judgeAwardAdvancement"]
    if "qualifierJudgeAwardAdvancement" in data:
        contest.judge_award_advancement = data[
            "qualifierJudgeAwardAdvancement"
        ]  # フロントの名称揺れ対応

    db.session.commit()

    # 時刻が変更された可能性があるのでタスクを再スケジュール
    cloud_tasks.schedule_contest_task(contest.id, "post_start", contest.start_time)
    cloud_tasks.schedule_contest_task(contest.id, "voting_start", contest.end_time)
    cloud_tasks.schedule_contest_task(contest.id, "result_announce", contest.voting_end_time)

    return ({"message": "Contest updated successfully"}), 200


def delete_contest(id):
    contest_to_delete = Contest.query.get(id)
    if not contest_to_delete:
        return ({"error": "削除対象の大会が見つかりません。"}), 404

    # Bulk deletes do not invoke ORM cascades. Remove every dependent row first,
    # including historical votes/results with a mismatched contest reference.
    post_ids = db.session.query(Post.id).filter_by(contest_id=id).subquery()
    Vote.query.filter(db.or_(Vote.contest_id == id, Vote.post_id.in_(db.select(post_ids.c.id)))).delete(synchronize_session=False)
    Comment.query.filter(Comment.post_id.in_(db.select(post_ids.c.id))).delete(synchronize_session=False)
    Notification.query.filter(db.or_(Notification.contest_id == id, Notification.post_id.in_(db.select(post_ids.c.id)))).delete(synchronize_session=False)
    Bookmark.query.filter(Bookmark.post_id.in_(db.select(post_ids.c.id))).delete(synchronize_session=False)
    ContestResult.query.filter(db.or_(ContestResult.contest_id == id, ContestResult.post_id.in_(db.select(post_ids.c.id)))).delete(synchronize_session=False)
    Post.query.filter_by(contest_id=id).delete()
    # Retain child contests, matching the previous ORM parent-detach behavior.
    Contest.query.filter_by(parent_contest_id=id).update({"parent_contest_id": None})
    Contest.query.filter_by(id=id).delete()
    db.session.commit()

    print(f"--- Contest Deleted: ID={id} ---")
    return ({"message": "大会が正常に削除されました。"}), 200


def _rollback_on_failure(operation):
    """Leave the current contest retryable when any persistence step fails."""
    @wraps(operation)
    def run(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except Exception:
            db.session.rollback()
            raise
    return run


@_rollback_on_failure
def handle_contest_task(id, event_type):
    contest = Contest.query.get(id)
    if not contest:
        return ({"error": "Contest not found"}), 404

    now = datetime.now(timezone.utc)
    changed = False

    if event_type == "post_start":
        if (
            contest.start_time
            and now >= contest.start_time.replace(tzinfo=timezone.utc)
            and not contest.notified_post_start
        ):
            print(f"[{contest.id}] Post start notification (Cloud Tasks)")
            user_ids = db.session.query(User.id).all()
            notifications = [
                {
                    "user_id": uid[0],
                    "type": "contest_post_start",
                    "contest_id": contest.id,
                }
                for uid in user_ids
            ]
            db.session.bulk_insert_mappings(Notification, notifications)
            contest.notified_post_start = True
            changed = True

    elif event_type == "voting_start":
        if (
            contest.end_time
            and now >= contest.end_time.replace(tzinfo=timezone.utc)
            and not contest.notified_voting_start
        ):
            print(f"[{contest.id}] Voting start notification (Cloud Tasks)")
            user_ids = db.session.query(User.id).all()
            notifications = [
                {
                    "user_id": uid[0],
                    "type": "contest_voting_start",
                    "contest_id": contest.id,
                }
                for uid in user_ids
            ]
            db.session.bulk_insert_mappings(Notification, notifications)
            contest.notified_voting_start = True
            changed = True

    elif event_type == "result_announce":
        if (
            contest.voting_end_time
            and now >= contest.voting_end_time.replace(tzinfo=timezone.utc)
            and not contest.notified_result_announce
        ):
            print(
                f"[{contest.id}] Result announce notification & calculation (Cloud Tasks)"
            )
            results_service.generate_contest_results(contest.id, commit=False)
            user_ids = db.session.query(User.id).all()
            notifications = [
                {
                    "user_id": uid[0],
                    "type": "contest_result_announce",
                    "contest_id": contest.id,
                }
                for uid in user_ids
            ]
            db.session.bulk_insert_mappings(Notification, notifications)
            contest.notified_result_announce = True
            changed = True

    if changed:
        db.session.commit()
        return ({"message": f"Processed {event_type}"}), 200

    return (
        {"message": "Task skipped (time not reached or already processed)"}
    ), 200


@_rollback_on_failure
def process_contests():
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
            results_service.generate_contest_results(contest.id, commit=False)
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
