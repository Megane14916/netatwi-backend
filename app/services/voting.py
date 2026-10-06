"""Vote validation, replacement, award handling and voter counter updates.

The route supplies session-derived judge flags and the original timing origin,
and retains HTTP responses and the exception/rollback boundary.
"""

import time
from datetime import datetime, timezone

from app.runtime_dependencies import calculate_weighted_length, route_logger as logger
from app.models import Contest, Post, Vote, db


# Post.id uses PostgreSQL INTEGER (signed 32-bit), including in migrations.
_MAX_POST_ID = 2**31 - 1


def _normalize_post_id(value):
    post_id = int(value)
    if not 0 < post_id <= _MAX_POST_ID:
        raise ValueError("Post ID out of range")
    return post_id


def validate_votes(content, votes_to_submit):
    if content:
        content = content.replace("\r\n", "\n").replace("\r", "\n")

    if not isinstance(votes_to_submit, dict):
        return ({"error": "Invalid vote data"}), 400

    # バリデーション: 文字数チェック
    if calculate_weighted_length(content) > 280:
        return ({"error": "Text too long (max 280)"}), 400

    return None


def submit_votes(
    id, user_id, votes_to_submit, judge_award, is_judge, is_judge_voting_now, start_time
):
    t0 = time.time()

    # 期間チェック（DELETEより前に行い、範囲外なら何も変更せず返す）
    c = Contest.query.get_or_404(id)
    t1 = time.time()
    logger.info(f"==> [submit_votes] get_or_404 took: {t1 - t0:.4f}s")
    now = datetime.now(timezone.utc)
    if not (
        c.end_time.replace(tzinfo=timezone.utc)
        <= now
        < c.voting_end_time.replace(tzinfo=timezone.utc)
    ):
        return ({"error": "Outside period"}), 403

    # Validate every target and score before replacing any existing rows.
    max_score = c.judge_max_score if is_judge else 1
    normalized_votes = {}
    try:
        for pid_str, count_val in votes_to_submit.items():
            post_id = _normalize_post_id(pid_str)
            if post_id in normalized_votes:
                raise ValueError
            count = float(count_val)
            if is_judge_voting_now:
                if not 0 <= count <= max_score:
                    raise ValueError
            elif count not in (0, 1):
                raise ValueError
            normalized_votes[post_id] = count
    except (ValueError, TypeError, OverflowError):
        return ({"error": "Invalid vote data"}), 400

    award_pid = None
    if is_judge_voting_now and judge_award is not None:
        if not isinstance(judge_award, dict):
            return ({"error": "Invalid judge award"}), 400
        award_pid = judge_award.get("postId")
        if type(award_pid) is not int:
            return ({"error": "Invalid judge award"}), 400
        try:
            award_pid = _normalize_post_id(award_pid)
        except ValueError:
            return ({"error": "Invalid judge award"}), 400

    target_ids = set(normalized_votes)
    if award_pid is not None:
        target_ids.add(award_pid)
    posts_map = {p.id: p for p in Post.query.filter(
        Post.contest_id == id, Post.id.in_(target_ids)
    ).all()} if target_ids else {}
    if set(posts_map) != target_ids or any(p.user_id == user_id for p in posts_map.values()):
        return ({"error": "Invalid vote target"}), 400

    # --- キャッシュスタンピード対策のカウンタ更新用 ---
    previous_votes = Vote.query.filter_by(user_id=user_id, contest_id=id).all()
    was_voter = len(previous_votes) > 0
    was_judge_voter = any(v.is_judge_vote for v in previous_votes)
    # ----------------------------------------------------

    Vote.query.filter_by(user_id=user_id, contest_id=id).delete()
    t2 = time.time()
    logger.info(f"==> [submit_votes] delete took: {t2 - t1:.4f}s")

    # --- 投票データの保存 ---
    # 1. 点数投票の保存
    # N+1問題を回避するため、事前に対象のPostをバルク取得
    processed_post_ids = set()
    for post_id, count in normalized_votes.items():
        is_award = is_judge_voting_now and award_pid == post_id
        comment = judge_award.get("comment") if is_award else None
        if count > 0 or is_award or (is_judge_voting_now and count == 0):
            db.session.add(
                Vote(
                    user_id=user_id,
                    post_id=post_id,
                    contest_id=id,
                    count=count,
                    is_judge_vote=is_judge_voting_now,
                    is_judge_award=is_award,
                    judge_comment=comment,
                )
            )
            processed_post_ids.add(post_id)

    # 2. 審査員賞が選択されているが、点数が0点(votesに含まれない/0)の場合のフォロー
    if award_pid is not None and award_pid not in processed_post_ids:
        # 0点で賞だけあげるケース
        db.session.add(
            Vote(
                user_id=user_id,
                post_id=award_pid,
                contest_id=id,
                count=0,
                is_judge_vote=True,
                is_judge_award=True,
                judge_comment=judge_award.get("comment"),
            )
        )

    # --- キャッシュスタンピード対策のカウンタ更新用 ---
    is_now_voter = bool(processed_post_ids) or award_pid is not None
    is_now_judge_voter = bool(is_now_voter and is_judge_voting_now)

    if not was_voter and is_now_voter:
        Contest.query.filter_by(id=id).update(
            {"total_voters": Contest.total_voters + 1}
        )
    elif was_voter and not is_now_voter:
        Contest.query.filter(Contest.id == id, Contest.total_voters > 0).update(
            {"total_voters": Contest.total_voters - 1}
        )

    if not was_judge_voter and is_now_judge_voter:
        Contest.query.filter_by(id=id).update(
            {"total_judges": Contest.total_judges + 1}
        )
    elif was_judge_voter and not is_now_judge_voter:
        Contest.query.filter(Contest.id == id, Contest.total_judges > 0).update(
            {"total_judges": Contest.total_judges - 1}
        )
    # ----------------------------------------------------

    t3 = time.time()
    logger.info(f"==> [submit_votes] loop took: {t3 - t2:.4f}s")
    db.session.commit()
    t4 = time.time()
    logger.info(f"==> [submit_votes] commit took: {t4 - t3:.4f}s")
    logger.info(f"==> [submit_votes] FINISHED in {t4 - start_time:.4f}s")
    return ({"message": "Voted"}), 200
