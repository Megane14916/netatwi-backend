"""Cloud Tasks HTTP handler."""

from datetime import datetime, timezone

from flask import jsonify

from models import Contest, Notification, User, db
from services import results as results_service
from .legacy import LegacyEndpointBlueprint


bp = LegacyEndpointBlueprint("tasks", __name__)


@bp.route("/api/tasks/contest/<int:id>/<event_type>", methods=["POST"])
def handle_contest_task(id, event_type):
    # Security note: In a real app, verify the request comes from Cloud Tasks (e.g. OIDC token)
    contest = Contest.query.get(id)
    if not contest:
        return jsonify({"error": "Contest not found"}), 404

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
            results_service.generate_contest_results(contest.id)
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
        return jsonify({"message": f"Processed {event_type}"}), 200

    return jsonify(
        {"message": "Task skipped (time not reached or already processed)"}
    ), 200
