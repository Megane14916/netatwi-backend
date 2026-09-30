"""Contest administration routes."""

import os
import traceback
from datetime import datetime, timedelta, timezone

from flask import current_app, jsonify, request, session

from models import Contest, Post, Vote, db
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
            schedule_contest_task(
                qualifier_contest.id, "post_start", qualifier_contest.start_time
            )
            schedule_contest_task(
                qualifier_contest.id, "voting_start", qualifier_contest.end_time
            )
            schedule_contest_task(
                qualifier_contest.id,
                "result_announce",
                qualifier_contest.voting_end_time,
            )

            schedule_contest_task(
                final_contest.id, "post_start", final_contest.start_time
            )
            schedule_contest_task(
                final_contest.id, "voting_start", final_contest.end_time
            )
            schedule_contest_task(
                final_contest.id, "result_announce", final_contest.voting_end_time
            )

            return jsonify(
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

            schedule_contest_task(new_contest.id, "post_start", new_contest.start_time)
            schedule_contest_task(new_contest.id, "voting_start", new_contest.end_time)
            schedule_contest_task(
                new_contest.id, "result_announce", new_contest.voting_end_time
            )

            return jsonify(
                {"message": "Contest created successfully", "id": new_contest.id}
            ), 201
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

    contest = Contest.query.get(id)
    if not contest:
        return jsonify({"error": "Contest not found"}), 404

    data = request.get_json()
    try:
        # 更新可能なフィールドの更新
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
        schedule_contest_task(contest.id, "post_start", contest.start_time)
        schedule_contest_task(contest.id, "voting_start", contest.end_time)
        schedule_contest_task(contest.id, "result_announce", contest.voting_end_time)

        return jsonify({"message": "Contest updated successfully"}), 200
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
        contest_to_delete = Contest.query.get(id)
        if not contest_to_delete:
            return jsonify({"error": "削除対象の大会が見つかりません。"}), 404

        # --- ▼▼▼ 関連データの削除処理を追加 ▼▼▼ ---
        # 1. 関連する投票(Vote)を削除
        Vote.query.filter_by(contest_id=id).delete()
        # 2. 関連する投稿(Post)を削除
        Post.query.filter_by(contest_id=id).delete()
        # 3. 中間コミット (任意だが、ステップを分ける場合は推奨)
        # db.session.commit() # ここでコミットしても良い
        # --- ▲▲▲ ここまで ▲▲▲ ---

        # 4. 大会(Contest)自体を削除
        db.session.delete(contest_to_delete)
        db.session.commit()  # 最終コミット

        print(f"--- Contest Deleted: ID={id} ---")
        return jsonify({"message": "大会が正常に削除されました。"}), 200
    except Exception as e:
        db.session.rollback()  # エラー時はロールバック
        print(f"!!! ERROR at DELETE /api/admin/contests/{id}: {e}")
        traceback.print_exc()
        return jsonify({"error": "大会の削除中にエラーが発生しました。"}), 500
