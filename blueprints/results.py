"""Contest result presentation routes."""

import traceback
from datetime import datetime, timedelta, timezone

from flask import jsonify, session
from sqlalchemy.orm import joinedload

from models import Bookmark, Comment, Contest, Post, User, Vote, db
from .dependencies import get_cached_contest_results
from .legacy import LegacyEndpointBlueprint


bp = LegacyEndpointBlueprint("results", __name__)
JST = timezone(timedelta(hours=9), "JST")


@bp.route("/api/contests/<int:id>/results")
def get_contest_results(id):
    try:
        user_id = session.get("user_id")
        c = Contest.query.get_or_404(id)
        now = datetime.now(timezone.utc)
        if now < c.voting_end_time.replace(tzinfo=timezone.utc):
            return jsonify({"error": "Voting ongoing"}), 403

        all_posts = (
            Post.query.options(joinedload(Post.user))
            .filter(Post.contest_id == id)
            .all()
        )
        if not all_posts:
            return jsonify(
                {
                    "contest": {"id": c.id, "name": c.name, "theme": c.theme},
                    "results": [],
                    "judgeAwards": [],
                    "totalPosters": 0,
                    "totalVoters": 0,
                }
            )

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

        return jsonify(
            {
                "contest": {"id": c.id, "name": c.name, "theme": c.theme},
                "results": results_list,
                "judgeAwards": judge_awards_data,  # 追加
                "totalPosters": total_posters or 0,
                "totalVoters": total_voters or 0,
                "totalJudges": total_judges or 0,
            }
        )
    except Exception as e:
        print(e)
        traceback.print_exc()
        return jsonify({"error": "Error"}), 500
