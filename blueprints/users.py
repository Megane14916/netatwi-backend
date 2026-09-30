"""Public user directory routes."""

from flask import jsonify, request
from sqlalchemy.orm import joinedload

from models import db
from .legacy import LegacyEndpointBlueprint


bp = LegacyEndpointBlueprint("users", __name__)


@bp.route("/api/users", methods=["GET"])
def get_users_list():
    from models import User, UserStats
    from sqlalchemy import asc, desc, func

    search_query = request.args.get("q", "")
    page = request.args.get("page", 1, type=int)
    per_page = 100

    query = User.query.join(UserStats, User.id == UserStats.user_id).options(
        joinedload(User.stats)
    )
    query = query.filter(User.deleted_at.is_(None))
    if search_query:
        search_term = f"%{search_query}%"
        query = query.filter(
            db.or_(
                User.name.ilike(search_term),
                User.screen_name.ilike(search_term),
                User.twitter_id.ilike(search_term),
            )
        )

    query = query.order_by(asc(UserStats.rank), asc(User.name))
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    users_data = []
    for user in pagination.items:
        stats = user.stats
        users_data.append(
            {
                "id": user.id,
                "twitter_id": user.twitter_id,
                "name": user.name,
                "screen_name": user.screen_name,
                "profile_image_url": user.profile_image_url,
                "stats": {
                    "gp_1st": stats.gp_1st if stats else 0,
                    "gp_2nd": stats.gp_2nd if stats else 0,
                    "gp_3rd": stats.gp_3rd if stats else 0,
                    "daily_1st": stats.daily_1st if stats else 0,
                    "daily_2nd": stats.daily_2nd if stats else 0,
                    "daily_3rd": stats.daily_3rd if stats else 0,
                    "judge_awards": stats.judge_awards if stats else 0,
                },
            }
        )

    return jsonify(
        {
            "users": users_data,
            "page": pagination.page,
            "total_pages": pagination.pages,
            "total_items": pagination.total,
            "has_next": pagination.has_next,
            "has_prev": pagination.has_prev,
        }
    ), 200
