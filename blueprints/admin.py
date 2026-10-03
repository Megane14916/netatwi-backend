"""Contest administration routes."""

import os
import traceback
from datetime import datetime, timedelta, timezone

from flask import current_app, jsonify, request, session

from models import Contest, db
from services import contest_lifecycle
from .legacy import LegacyEndpointBlueprint


bp = LegacyEndpointBlueprint("admin", __name__)
JST = timezone(timedelta(hours=9), "JST")


def schedule_contest_task(*args):
    return current_app.extensions["schedule_contest_task"](*args)


@bp.route("/api/admin/contests", methods=["POST"])
def create_contest():
    if "user_id" not in session:
        return jsonify({"error": "Login required"}), 401
    allowed_admins = [
        s.strip()
        for s in os.environ.get(
            "ADMIN_SCREEN_NAMES", "dummy_admin1,dummy_admin2"
        ).split(",")
        if s.strip()
    ]
    if session.get("screen_name") not in allowed_admins:
        return jsonify({"error": "Forbidden: Admins only"}), 403

    data = request.get_json()
    try:
        result, status = contest_lifecycle.create_contest(data)
        return jsonify(result), status
    except Exception as e:
        db.session.rollback()
        print(f"!!! ERROR at /api/admin/contests: {e}")
        traceback.print_exc()
        return jsonify({"error": "Failed to create contest"}), 500


@bp.route("/api/admin/contests/management")
def get_management_contests():
    if "user_id" not in session:
        return jsonify({"error": "Login required"}), 401
    allowed_admins = [
        s.strip()
        for s in os.environ.get(
            "ADMIN_SCREEN_NAMES", "dummy_admin1,dummy_admin2"
        ).split(",")
        if s.strip()
    ]
    if session.get("screen_name") not in allowed_admins:
        return jsonify({"error": "Forbidden: Admins only"}), 403

    try:
        now = datetime.now(timezone.utc)
        # 投票終了時間が現在時刻より未来の大会を取得 (upcoming, ongoing, voting)
        # 開始時間が新しい順 (最近作成されたものが上に来る)
        active_contests = (
            Contest.query.filter(Contest.voting_end_time >= now)
            .order_by(Contest.start_time.desc())
            .all()
        )

        contests_data = []
        for contest in active_contests:
            contests_data.append(
                {
                    "id": contest.id,
                    "name": contest.name,
                    "theme": contest.theme if contest.has_theme else None,
                    "hasQualifier": contest.has_qualifier,
                    "startTime": contest.start_time.replace(tzinfo=timezone.utc)
                    .astimezone(JST)
                    .isoformat(),
                    "endTime": contest.end_time.replace(tzinfo=timezone.utc)
                    .astimezone(JST)
                    .isoformat(),
                    "votingEndTime": contest.voting_end_time.replace(
                        tzinfo=timezone.utc
                    )
                    .astimezone(JST)
                    .isoformat(),
                    "judgePassword": contest.judge_password,  # パスワードも含める
                    "type": contest.type,
                    "scoringMethod": contest.scoring_method,
                    "imageRule": contest.image_rule,
                    "generalVoteWeight": contest.general_vote_weight,
                    "judgeMaxScore": contest.judge_max_score,
                    "isVotingVisible": contest.is_voting_visible,
                    "advancementNumerator": contest.advancement_numerator,
                    "advancementDenominator": contest.advancement_denominator,
                    "judgeAwardAdvancement": contest.judge_award_advancement,
                    "resultCommentTop": contest.result_comment_top,
                    "resultCommentBottom": contest.result_comment_bottom,
                }
            )
        return jsonify(contests_data)
    except Exception as e:
        print(f"!!! ERROR at GET /api/admin/contests/management: {e}")
        traceback.print_exc()
        return jsonify({"error": "Failed to fetch contests for management"}), 500


@bp.route("/api/admin/contests/<int:id>", methods=["PUT"])
def update_contest(id):
    if "user_id" not in session:
        return jsonify({"error": "Login required"}), 401
    allowed_admins = [
        s.strip()
        for s in os.environ.get(
            "ADMIN_SCREEN_NAMES", "dummy_admin1,dummy_admin2"
        ).split(",")
        if s.strip()
    ]
    if session.get("screen_name") not in allowed_admins:
        return jsonify({"error": "Forbidden: Admins only"}), 403

    contest = contest_lifecycle.get_contest(id)
    if not contest:
        return jsonify({"error": "Contest not found"}), 404

    data = request.get_json()
    try:
        # 更新可能なフィールドの更新
        result, status = contest_lifecycle.update_contest(contest, data)
        return jsonify(result), status
    except Exception as e:
        db.session.rollback()
        print(f"!!! ERROR at PUT /api/admin/contests/{id}: {e}")
        traceback.print_exc()
        return jsonify({"error": "Failed to update contest"}), 500


@bp.route("/api/admin/contests/<int:id>", methods=["DELETE"])
def delete_contest(id):
    if "user_id" not in session:
        return jsonify({"error": "Login required"}), 401
    allowed_admins = [
        s.strip()
        for s in os.environ.get(
            "ADMIN_SCREEN_NAMES", "dummy_admin1,dummy_admin2"
        ).split(",")
        if s.strip()
    ]
    if session.get("screen_name") not in allowed_admins:
        return jsonify({"error": "Forbidden: Admins only"}), 403

    try:
        result, status = contest_lifecycle.delete_contest(id)
        return jsonify(result), status
    except Exception as e:
        db.session.rollback()  # エラー時はロールバック
        print(f"!!! ERROR at DELETE /api/admin/contests/{id}: {e}")
        traceback.print_exc()
        return jsonify({"error": "大会の削除中にエラーが発生しました。"}), 500
