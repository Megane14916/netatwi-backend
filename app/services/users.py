"""User directory queries and withdrawal with original dependency timing."""

from app.services.serialization import public_user

from datetime import datetime, timezone
from sqlalchemy.orm import joinedload
from app.services.transactions import rollback_on_failure
from app.extensions import db
from app.models import User


def get_directory_dependencies():
    from app.models import User, UserStats
    from sqlalchemy import asc, desc, func
    return User, UserStats, asc


def get_users_list(search_query, page, User, UserStats, asc):
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
                **public_user(user, include_id=True),
                "twitter_id": user.twitter_id,
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

    return (
        {
            "users": users_data,
            "page": pagination.page,
            "total_pages": pagination.pages,
            "total_items": pagination.total,
            "has_next": pagination.has_next,
            "has_prev": pagination.has_prev,
        }
    ), 200


@rollback_on_failure
def withdraw_user(user_id):
    user = User.query.get(user_id)
    if not user:
        return ({"error": "User not found"}), 404

    user.deleted_at = datetime.now(timezone.utc)
    db.session.commit()

    return None
