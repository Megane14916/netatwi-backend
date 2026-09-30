"""Contest listing and details routes."""

import logging
from datetime import datetime, timedelta, timezone

from flask import jsonify, session

from models import Contest, ContestResult
from .legacy import LegacyEndpointBlueprint


bp = LegacyEndpointBlueprint("contests", __name__)
logger = logging.getLogger("app")
JST = timezone(timedelta(hours=9), "JST")

# Simple cache for get_contests
_contests_cache = None
_contests_cache_time = 0


@bp.route("/api/contests")
def get_contests():
    global _contests_cache, _contests_cache_time
    import time

    if _contests_cache and time.time() - _contests_cache_time < 5:
        return jsonify(_contests_cache)

    try:
        contests = Contest.query.order_by(Contest.start_time.desc()).all()
        now = datetime.now(timezone.utc)
        ongoing, voting, upcoming, closed_list, closed_data = [], [], [], [], []
        latest_result = None

        # キャッシュスタンピード対策により重い集計クエリを削除

        for contest in contests:
            st = (
                contest.start_time.replace(tzinfo=timezone.utc)
                if contest.start_time
                else None
            )
            et = (
                contest.end_time.replace(tzinfo=timezone.utc)
                if contest.end_time
                else None
            )
            vt = (
                contest.voting_end_time.replace(tzinfo=timezone.utc)
                if contest.voting_end_time
                else None
            )

            # キャッシュスタンピード対策: モデルのカウンタから取得
            total_posters = contest.post_count
            total_voters = contest.total_voters
            total_judges = contest.total_judges

            c_data = {
                "id": contest.id,
                "name": contest.name,
                "hasTheme": contest.has_theme,
                "theme": contest.theme,
                "hasQualifier": contest.has_qualifier,
                "type": contest.type,
                "scoringMethod": contest.scoring_method,
                "imageRule": contest.image_rule,
                "isVotingVisible": contest.is_voting_visible,
                "advancementNumerator": contest.advancement_numerator,
                "advancementDenominator": contest.advancement_denominator,
                "parentContestId": contest.parent_contest_id,
                "judgeAwardAdvancement": contest.judge_award_advancement,
                "startTime": st.astimezone(JST).isoformat() if st else None,
                "endTime": et.astimezone(JST).isoformat() if et else None,
                "votingEndTime": vt.astimezone(JST).isoformat() if vt else None,
                "generalVoteWeight": contest.general_vote_weight,
                "judgeMaxScore": contest.judge_max_score,
                # 追加フィールド
                "totalPosters": total_posters,
                "totalVoters": total_voters,
                "totalJudges": total_judges,
            }

            if st and et and st <= now < et:
                ongoing.append(c_data)
            elif et and vt and et <= now < vt:
                voting.append(c_data)
            elif st and now < st:
                upcoming.append(c_data)
            elif vt and now >= vt:
                closed_list.append(contest)
                closed_data.append(c_data)

        if closed_data:
            # closed_dataはすでにソートされている(contestsループ順)ので、先頭が最新
            latest = closed_data[0]
            latest_result = {
                "contest_id": latest["id"],
                "contest_name": latest["name"],
                "theme": latest["theme"],
                "totalPosters": latest["totalPosters"],
                "totalVoters": latest["totalVoters"],
                "totalJudges": latest["totalJudges"],
            }

        upcoming.reverse()
        payload = {
            "ongoing": ongoing,
            "voting": voting,
            "upcoming": upcoming,
            "closed": closed_data,
            "latestResult": latest_result,
        }
        # Response オブジェカトではなく dict で保持する（ミリセッンスレベルでの共有による不具合を回避）
        _contests_cache = payload
        _contests_cache_time = time.time()
        return jsonify(payload)
    except Exception as e:
        return jsonify({"error": "Failed"}), 500


@bp.route("/api/contests/<int:id>")
def get_contest_details(id):
    import time

    start_time = time.time()
    try:
        contest = Contest.query.get_or_404(id)
        t1 = time.time()
        logger.info(f"[get_contest_details] get_or_404: {t1 - start_time:.4f}s")
        user_id = session.get("user_id")
        is_advanced_to_final = None
        if user_id and contest.parent_contest_id:
            qualifier_result = ContestResult.query.filter_by(
                contest_id=contest.parent_contest_id, user_id=user_id
            ).first()
            is_advanced_to_final = (
                qualifier_result.is_advanced if qualifier_result else False
            )

        t2 = time.time()
        logger.info(f"[get_contest_details] TOTAL TIME: {t2 - start_time:.4f}s")
        return jsonify(
            {
                "id": contest.id,
                "name": contest.name,
                "theme": contest.theme,  # お題 (Noneの場合もある)
                "startTime": contest.start_time.replace(tzinfo=timezone.utc)
                .astimezone(JST)
                .isoformat(),
                "endTime": contest.end_time.replace(tzinfo=timezone.utc)
                .astimezone(JST)
                .isoformat(),
                "votingEndTime": contest.voting_end_time.replace(tzinfo=timezone.utc)
                .astimezone(JST)
                .isoformat(),
                "generalVoteWeight": contest.general_vote_weight,
                "judgeMaxScore": contest.judge_max_score,
                "hasTheme": contest.has_theme,
                "hasQualifier": contest.has_qualifier,
                "type": contest.type,
                "scoringMethod": contest.scoring_method,
                "imageRule": contest.image_rule,
                "isVotingVisible": contest.is_voting_visible,
                "advancementNumerator": contest.advancement_numerator,
                "advancementDenominator": contest.advancement_denominator,
                "judgeAwardAdvancement": contest.judge_award_advancement,
                "parentContestId": contest.parent_contest_id,
                "isAdvancedToFinal": is_advanced_to_final,
                "resultCommentTop": contest.result_comment_top,
                "resultCommentBottom": contest.result_comment_bottom,
                "postCount": contest.post_count,
                "totalVoters": contest.total_voters,
                "totalJudges": contest.total_judges,
            }
        )
    except Exception as e:
        print(f"!!! ERROR at /api/contests/{id}: {e}")
        return jsonify({"error": "Contest not found"}), 404
