"""Public and management contest queries with an application-local cache."""

from app.services.serialization import contest_rules, contest_times

from datetime import datetime, timezone

from flask import current_app
from app.services import policies
from app.models import Contest, ContestResult



# Simple cache for get_contests
def contest_cache():
    return current_app.extensions.setdefault("contests_cache", {"payload": None, "time": 0})


def get_cached_contests(time):
    cache = contest_cache()
    if cache["payload"] and time.time() - cache["time"] < 5:
        return True, cache["payload"]
    return False, None


def get_contests(time):
    cache = contest_cache()
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
            **contest_rules(contest),
            "parentContestId": contest.parent_contest_id,
            **contest_times(contest, nullable=True),
            # 追加フィールド
            "totalPosters": total_posters,
            "totalVoters": total_voters,
            "totalJudges": total_judges,
        }

        if st and et and policies.in_period(now, st, et):
            ongoing.append(c_data)
        elif et and vt and policies.in_period(now, et, vt):
            voting.append(c_data)
        elif st and now < st:
            upcoming.append(c_data)
        elif vt and policies.has_reached(now, vt):
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
    cache["payload"] = payload
    cache["time"] = time.time()
    return (payload)


def get_contest_for_details(id, start_time, time):
    contest = Contest.query.get_or_404(id)
    t1 = time.time()
    current_app.logger.info(f"[get_contest_details] get_or_404: {t1 - start_time:.4f}s")
    return contest


def get_contest_details(contest, user_id, start_time, time):
    is_advanced_to_final = None
    if user_id and contest.parent_contest_id:
        qualifier_result = ContestResult.query.filter_by(
            contest_id=contest.parent_contest_id, user_id=user_id
        ).first()
        is_advanced_to_final = (
            qualifier_result.is_advanced if qualifier_result else False
        )

    t2 = time.time()
    current_app.logger.info(f"[get_contest_details] TOTAL TIME: {t2 - start_time:.4f}s")
    return (
        {
            "id": contest.id,
            "name": contest.name,
            "theme": contest.theme,  # お題 (Noneの場合もある)
            **contest_times(contest),
            **contest_rules(contest),
            "hasTheme": contest.has_theme,
            "hasQualifier": contest.has_qualifier,
            "parentContestId": contest.parent_contest_id,
            "isAdvancedToFinal": is_advanced_to_final,
            "resultCommentTop": contest.result_comment_top,
            "resultCommentBottom": contest.result_comment_bottom,
            "postCount": contest.post_count,
            "totalVoters": contest.total_voters,
            "totalJudges": contest.total_judges,
        }
    )


def get_management_contests():
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
                **contest_times(contest),
                "judgePassword": contest.judge_password,  # パスワードも含める
                **contest_rules(contest),
                "resultCommentTop": contest.result_comment_top,
                "resultCommentBottom": contest.result_comment_bottom,
            }
        )
    return (contests_data)
