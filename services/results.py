"""Persisted result generation, retrieval and API presentation data."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import case, distinct, func
from sqlalchemy.orm import joinedload

from models import Bookmark, Comment, Contest, ContestResult, Post, User, Vote, db


JST = timezone(timedelta(hours=9), "JST")


def generate_contest_results(contest_id):
    """
    定期バッチ専用：結果を集計し、ContestResult に保存する。
    """
    contest = Contest.query.get(contest_id)
    if not contest:
        return None

    # すでに集計済みの場合はスキップ
    existing_results = ContestResult.query.filter_by(contest_id=contest_id).first()
    if existing_results:
        return

    # 一般投票者の総数（ユニーク）を取得
    total_general_voters = (
        db.session.query(func.count(distinct(Vote.user_id)))
        .filter(Vote.contest_id == contest_id, Vote.is_judge_vote == False)
        .scalar()
    )

    if total_general_voters is None or total_general_voters == 0:
        total_general_voters = 1

    judge_score_col = func.sum(case((Vote.is_judge_vote == True, Vote.count), else_=0))
    general_votes_col = func.sum(
        case((Vote.is_judge_vote == False, Vote.count), else_=0)
    )

    results_query = (
        db.session.query(
            Vote.post_id,
            judge_score_col.label("judge_score"),
            general_votes_col.label("general_votes"),
        )
        .filter(Vote.contest_id == contest_id)
        .group_by(Vote.post_id)
        .subquery()
    )

    judge_score_val = func.coalesce(results_query.c.judge_score, 0)
    general_votes_val = func.coalesce(results_query.c.general_votes, 0)

    # 採点方法に基づく計算式
    if contest.scoring_method == "user":
        final_score_expr = general_votes_val
    elif contest.scoring_method == "judge":
        final_score_expr = judge_score_val
    else:  # 'both' or None
        final_score_expr = (
            judge_score_val
            + (general_votes_val / total_general_voters) * contest.general_vote_weight
        )

    ranked_posts_query = (
        db.session.query(Post, final_score_expr.label("total_score"))
        .outerjoin(results_query, Post.id == results_query.c.post_id)
        .filter(Post.contest_id == contest_id)
        .order_by(
            final_score_expr.desc(),
            Post.created_at.asc(),  # 同点時の順序用
        )
    )

    ranked_results = []
    current_rank = 1
    last_score = -1
    skip = 0
    ranked_posts = ranked_posts_query.all()
    total_participants = len(ranked_posts)
    advancement_cutoff = 0
    if contest.advancement_numerator is not None and contest.advancement_denominator:
        advancement_cutoff = (
            total_participants * contest.advancement_numerator
        ) // contest.advancement_denominator

    # 審査員賞の取得
    judge_awards_query = (
        db.session.query(Vote.post_id)
        .filter(Vote.contest_id == contest_id, Vote.is_judge_award == True)
        .all()
    )
    judge_awarded_post_ids = {row[0] for row in judge_awards_query}

    results_to_insert = []
    for idx, (post, total_score) in enumerate(ranked_posts):
        current_score_val = round(total_score, 2) if total_score is not None else 0
        if idx == 0:
            last_score = current_score_val

        if current_score_val != last_score:
            current_rank += 1 + skip
            skip = 0
            last_score = current_score_val
        elif idx > 0:
            skip += 1

        is_advanced = (
            current_rank <= advancement_cutoff if advancement_cutoff > 0 else False
        )
        is_judge_award = post.id in judge_awarded_post_ids
        if contest.judge_award_advancement and is_judge_award:
            is_advanced = True

        cr = ContestResult(
            contest_id=contest_id,
            post_id=post.id,
            user_id=post.user_id,
            score=current_score_val,
            rank=current_rank,
            is_advanced=is_advanced,
            is_judge_award=is_judge_award,
        )
        results_to_insert.append(cr)

    db.session.bulk_save_objects(results_to_insert)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Failed to save ContestResult: {e}")


def get_cached_contest_results(contest_id):
    """
    API呼び出し用：DBに保存済みの ContestResult から結果を取得して返す。
    バッチが未実行でデータがない場合は空の辞書を返す。
    """
    existing_results = ContestResult.query.filter_by(contest_id=contest_id).all()
    results_dict = {}
    for r in existing_results:
        results_dict[r.post_id] = {
            "post_id": r.post_id,
            "rank": r.rank,
            "score": r.score,
            "is_advanced": r.is_advanced,
            "is_judge_award": r.is_judge_award,
        }
    return results_dict


def get_contest_results(id, user_id):
    c = Contest.query.get_or_404(id)
    now = datetime.now(timezone.utc)
    if now < c.voting_end_time.replace(tzinfo=timezone.utc):
        return ({"error": "Voting ongoing"}), 403

    all_posts = (
        Post.query.options(joinedload(Post.user))
        .filter(Post.contest_id == id)
        .all()
    )
    if not all_posts:
        return (
            {
                "contest": {"id": c.id, "name": c.name, "theme": c.theme},
                "results": [],
                "judgeAwards": [],
                "totalPosters": 0,
                "totalVoters": 0,
            }
        ), 200

    contest_results = get_cached_contest_results(id)

    # --- 審査員賞の取得 ---
    judge_awards_query = (
        db.session.query(Vote, User, Post)
        .join(User, Vote.user_id == User.id)
        .join(Post, Vote.post_id == Post.id)
        .filter(Vote.contest_id == id, Vote.is_judge_award == True)
        .all()
    )
    judge_awards_data = []
    award_badges = {}  # post_id -> ["審査員名賞", ...]

    for vote, judge_user, post in judge_awards_query:
        award_name = f"{judge_user.name}賞"
        # 結果リスト表示用バッジ
        if post.id not in award_badges:
            award_badges[post.id] = []
        award_badges[post.id].append(award_name)

        # 審査員賞タブ表示用データ
        judge_awards_data.append(
            {
                "judge": {
                    "screen_name": judge_user.screen_name,
                    "name": judge_user.name,
                    "profile_image_url": judge_user.profile_image_url,
                },
                "comment": vote.judge_comment,
                "post": {
                    "post_id": post.id,
                    "content": post.content,
                    "images": post.images,
                    "user": {
                        "screen_name": post.user.screen_name,
                        "name": post.user.name,
                        "profile_image_url": post.user.profile_image_url,
                    },
                    "created_at": post.created_at.replace(tzinfo=timezone.utc)
                    .astimezone(JST)
                    .isoformat(),
                },
            }
        )

    # ... (以下、既存の結果整形ロジック) ...
    all_votes_query = (
        db.session.query(Vote, User)
        .join(User, Vote.user_id == User.id)
        .filter(Vote.contest_id == id)
        .all()
    )
    voters_by_post = {}
    for vote, user in all_votes_query:
        if vote.post_id not in voters_by_post:
            voters_by_post[vote.post_id] = []
        # 投票者リスト表示: 審査員の場合は点数も表示したいのでcountを含める
        voters_by_post[vote.post_id].append(
            {
                "screen_name": user.screen_name,
                "name": user.name,
                "count": vote.count,
                "is_judge": vote.is_judge_vote,
            }
        )

    post_ids = [p.id for p in all_posts]
    user_bookmarks = set()
    if user_id:
        user_bookmarks = {
            p
            for (p,) in db.session.query(Bookmark.post_id)
            .filter(Bookmark.user_id == user_id, Bookmark.post_id.in_(post_ids))
            .all()
        }
    user_commented_post_ids = set()
    if user_id:
        user_commented_post_ids = {
            c.post_id
            for c in Comment.query.filter_by(user_id=user_id)
            .filter(Comment.post_id.in_(post_ids))
            .all()
        }

    results_list = []
    for post in all_posts:
        post_result = contest_results.get(post.id, {"rank": None, "score": 0})
        post_voters = voters_by_post.get(post.id, [])
        post_voters.sort(key=lambda v: v["is_judge"], reverse=True)
        results_list.append(
            {
                "rank": post_result["rank"],
                "post_id": post.id,
                "content": post.content,
                "images": post.images,
                "created_at": post.created_at.replace(tzinfo=timezone.utc)
                .astimezone(JST)
                .isoformat(),
                "score": post_result["score"],
                "user": {
                    "screen_name": post.user.screen_name,
                    "name": post.user.name,
                    "profile_image_url": post.user.profile_image_url,
                },
                "voters": post_voters,
                "bookmarkCount": post.bookmark_count,
                "commentCount": post.comment_count,
                "hasCommented": post.id in user_commented_post_ids,
                "isBookmarked": post.id in user_bookmarks,
                "awards": award_badges.get(post.id, []),  # バッジ情報を追加
                "is_advanced": post_result.get("is_advanced", False),
            }
        )

    results_list.sort(key=lambda x: (x["rank"] is None, x["rank"]))
    total_posters = c.post_count
    total_voters = c.total_voters
    total_judges = c.total_judges

    return (
        {
            "contest": {"id": c.id, "name": c.name, "theme": c.theme},
            "results": results_list,
            "judgeAwards": judge_awards_data,  # 追加
            "totalPosters": total_posters or 0,
            "totalVoters": total_voters or 0,
            "totalJudges": total_judges or 0,
        }
    ), 200
