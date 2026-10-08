"""Explicit API field sets shared by presentation services.

Visibility, ownership, ordering and management-only fields belong to callers.
No model-wide serialization or private-field discovery is performed here.
"""

from datetime import timedelta, timezone

JST = timezone(timedelta(hours=9), "JST")


def jst_iso(value):
    """Preserve the API's historical interpretation of persisted times as UTC."""
    return value.replace(tzinfo=timezone.utc).astimezone(JST).isoformat()


def public_user(user, *, include_id=False):
    payload = {
        "screen_name": user.screen_name,
        "name": user.name,
        "profile_image_url": user.profile_image_url,
    }
    if include_id:
        payload["id"] = user.id
    return payload


def post_content(post):
    return {
        "content": post.content,
        "images": post.images,
        "created_at": jst_iso(post.created_at),
    }


def post_submission(post):
    return {"id": post.id, **post_content(post), "user_id": post.user_id}


def contest_rules(contest):
    return {
        "type": contest.type,
        "scoringMethod": contest.scoring_method,
        "imageRule": contest.image_rule,
        "isVotingVisible": contest.is_voting_visible,
        "advancementNumerator": contest.advancement_numerator,
        "advancementDenominator": contest.advancement_denominator,
        "judgeAwardAdvancement": contest.judge_award_advancement,
        "generalVoteWeight": contest.general_vote_weight,
        "judgeMaxScore": contest.judge_max_score,
    }


def contest_times(contest, *, nullable=False):
    def format_time(value):
        return None if nullable and value is None else jst_iso(value)

    return {
        "startTime": format_time(contest.start_time),
        "endTime": format_time(contest.end_time),
        "votingEndTime": format_time(contest.voting_end_time),
    }
