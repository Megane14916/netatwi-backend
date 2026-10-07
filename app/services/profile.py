"""Profile queries, visibility and presentation with original result reuse."""

from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import joinedload
from app.services import policies
from app.extensions import db
from app.models import Bookmark, Post, User, Vote
from app.services import results as results_service


JST = timezone(timedelta(hours=9), "JST")


def prepare_profile_timing(time):
    perf_start_time = time.time()
    perf_prev_time = perf_start_time

    def log_step(step_name):
        nonlocal perf_prev_time
        curr = time.time()
        print(
            f"PROFILE_PERF_LOG: [{step_name}] took {curr - perf_prev_time:.4f}s (Total: {curr - perf_start_time:.4f}s)"
        )
        perf_prev_time = curr
    return log_step


def get_user_profile(screen_name, viewer_id, log_step):
    target_user = User.query.filter_by(screen_name=screen_name).first()
    log_step("target_user query")
    if not target_user or target_user.deleted_at:
        return ({"error": "Not found"}), 404
    user_id = target_user.id
    now = datetime.now(timezone.utc)
    results_cache = {}

    # 1. すべての生の投稿リストを取得
    user_posts_raw = (
        Post.query.filter_by(user_id=user_id)
        .options(joinedload(Post.contest), joinedload(Post.user))
        .order_by(Post.created_at.desc())
        .all()
    )
    log_step("query user_posts_raw")

    bookmarks_raw = (
        db.session.query(Post)
        .join(Bookmark, Post.id == Bookmark.post_id)
        .filter(Bookmark.user_id == user_id)
        .options(joinedload(Post.user), joinedload(Post.contest))
        .order_by(Bookmark.created_at.desc())
        .all()
    )
    log_step("query bookmarks_raw")

    liked_posts_raw = (
        db.session.query(Post)
        .join(Vote, Post.id == Vote.post_id)
        .filter(
            Vote.user_id == user_id, Vote.is_judge_vote == False, Vote.count > 0
        )
        .options(joinedload(Post.contest), joinedload(Post.user))
        .order_by(Vote.created_at.desc())
        .all()
    )
    log_step("query liked_posts_raw")

    # 2. 有効な(表示可能な)投稿のフィルタリングとID収集
    def filter_posts(raw_posts):
        valid = []
        for p in raw_posts:
            if policies.has_reached(now, p.contest.voting_end_time):
                valid.append(p)
        return valid

    valid_user_posts = filter_posts(user_posts_raw)
    valid_bookmarks = filter_posts(bookmarks_raw)
    valid_likes = filter_posts(liked_posts_raw)

    all_valid_post_ids = list(
        set(
            [p.id for p in valid_user_posts]
            + [p.id for p in valid_bookmarks]
            + [p.id for p in valid_likes]
        )
    )
    log_step("filter and collect all post_ids")

    # 3. 必要な情報を一括でDBから取得
    voters_map = {}
    my_votes_map = {}
    awards_map = {}
    viewer_bms = set()

    if all_valid_post_ids:
        # (a) 投票データ
        votes_data = (
            db.session.query(
                Vote.post_id,
                Vote.count,
                Vote.is_judge_vote,
                Vote.user_id,
                User.screen_name,
                User.name,
            )
            .join(User, Vote.user_id == User.id)
            .filter(Vote.post_id.in_(all_valid_post_ids))
            .all()
        )
        for (
            v_post_id,
            v_count,
            v_is_judge_vote,
            v_user_id,
            u_screen_name,
            u_name,
        ) in votes_data:
            if v_post_id not in voters_map:
                voters_map[v_post_id] = []
            voters_map[v_post_id].append(
                {
                    "screen_name": u_screen_name,
                    "name": u_name,
                    "count": v_count,
                    "is_judge": v_is_judge_vote,
                }
            )
            if viewer_id and v_user_id == viewer_id:
                my_votes_map[v_post_id] = v_count
        log_step("bulk fetch votes_data")

        # (b) 審査員賞データ
        awards_data = (
            db.session.query(Vote.post_id, User.name)
            .join(User, Vote.user_id == User.id)
            .filter(
                Vote.post_id.in_(all_valid_post_ids), Vote.is_judge_award == True
            )
            .all()
        )
        for a_post_id, u_name in awards_data:
            if a_post_id not in awards_map:
                awards_map[a_post_id] = []
            awards_map[a_post_id].append(f"{u_name}賞")
        log_step("bulk fetch awards_data")

        # (c) 閲覧者のブックマーク状況
        if viewer_id:
            viewer_bms = {
                p
                for (p,) in db.session.query(Bookmark.post_id)
                .filter(
                    Bookmark.user_id == viewer_id,
                    Bookmark.post_id.in_(all_valid_post_ids),
                )
                .all()
            }
        log_step("bulk fetch viewer_bms")

    # 4. フォーマット関数
    def format_posts_fast(posts_list):
        formatted = []
        for post in posts_list:
            cid = post.contest_id
            if cid not in results_cache:
                results_cache[cid] = results_service.get_cached_contest_results(cid)
            res = results_cache[cid].get(post.id)

            post_voters = voters_map.get(post.id, [])
            post_voters.sort(key=lambda v: v["is_judge"], reverse=True)

            formatted.append(
                {
                    "post_id": post.id,
                    "content": post.content,
                    "images": post.images,
                    "created_at": post.created_at.replace(tzinfo=timezone.utc)
                    .astimezone(JST)
                    .isoformat(),
                    "contest": {
                        "id": post.contest.id,
                        "name": post.contest.name,
                        "theme": post.contest.theme,
                        "scoringMethod": post.contest.scoring_method,
                    },
                    "user": {
                        "screen_name": post.user.screen_name,
                        "name": post.user.name,
                        "profile_image_url": post.user.profile_image_url,
                    },
                    "rank": res["rank"] if res else None,
                    "score": res["score"] if res else 0,
                    "bookmarkCount": post.bookmark_count,
                    "commentCount": post.comment_count,
                    "isBookmarked": post.id in viewer_bms,
                    "voters": post_voters,
                    "awards": awards_map.get(post.id, []),
                    "myVotes": my_votes_map.get(post.id, None),
                }
            )
        return formatted

    res_json = {
        "user": {
            "id": target_user.id,
            "screen_name": target_user.screen_name,
            "name": target_user.name,
            "profile_image_url": target_user.profile_image_url,
        },
        "posts": format_posts_fast(valid_user_posts),
        "bookmarks": format_posts_fast(valid_bookmarks),
        "likes": format_posts_fast(valid_likes),
    }
    log_step("format_posts_fast all lists")

    return res_json, 200
