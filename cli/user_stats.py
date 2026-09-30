"""User statistics batch command."""

from flask.cli import AppGroup


cli = AppGroup()


@cli.command("update-user-stats")
def update_user_stats():
    """Update UserStats table by aggregating ContestResult data"""
    from models import Contest, ContestResult, User, UserStats, db
    from sqlalchemy import case, func

    print("--- update-user-stats batch started ---")

    gp_1st = func.sum(
        case(((Contest.type == "grandprix") & (ContestResult.rank == 1), 1), else_=0)
    ).label("gp_1st")
    gp_2nd = func.sum(
        case(((Contest.type == "grandprix") & (ContestResult.rank == 2), 1), else_=0)
    ).label("gp_2nd")
    gp_3rd = func.sum(
        case(((Contest.type == "grandprix") & (ContestResult.rank == 3), 1), else_=0)
    ).label("gp_3rd")
    daily_1st = func.sum(
        case(((Contest.type == "daily") & (ContestResult.rank == 1), 1), else_=0)
    ).label("daily_1st")
    daily_2nd = func.sum(
        case(((Contest.type == "daily") & (ContestResult.rank == 2), 1), else_=0)
    ).label("daily_2nd")
    daily_3rd = func.sum(
        case(((Contest.type == "daily") & (ContestResult.rank == 3), 1), else_=0)
    ).label("daily_3rd")
    judge_awards = func.sum(
        case((ContestResult.is_judge_award == True, 1), else_=0)
    ).label("judge_awards")

    results = (
        db.session.query(
            User.id,
            User.name,
            gp_1st,
            gp_2nd,
            gp_3rd,
            daily_1st,
            daily_2nd,
            daily_3rd,
            judge_awards,
        )
        .outerjoin(ContestResult, User.id == ContestResult.user_id)
        .outerjoin(Contest, ContestResult.contest_id == Contest.id)
        .group_by(User.id, User.name)
        .all()
    )

    def sort_key(row):
        return (
            -(row.gp_1st or 0),
            -(row.gp_2nd or 0),
            -(row.gp_3rd or 0),
            -(row.judge_awards or 0),
            -(row.daily_1st or 0),
            -(row.daily_2nd or 0),
            -(row.daily_3rd or 0),
            row.name or "",
        )

    results.sort(key=sort_key)

    existing_stats = {s.user_id: s for s in UserStats.query.all()}

    current_rank = 1
    tie_count = 0
    prev_score = None

    for row in results:
        user_id = row.id

        score = (
            row.gp_1st or 0,
            row.gp_2nd or 0,
            row.gp_3rd or 0,
            row.judge_awards or 0,
            row.daily_1st or 0,
            row.daily_2nd or 0,
            row.daily_3rd or 0,
        )

        if prev_score is None:
            rank = current_rank
        elif score == prev_score:
            rank = current_rank
            tie_count += 1
        else:
            current_rank += tie_count + 1
            rank = current_rank
            tie_count = 0

        prev_score = score

        stats = existing_stats.get(user_id)
        if not stats:
            stats = UserStats(user_id=user_id)
            db.session.add(stats)

        stats.rank = rank
        stats.gp_1st = row.gp_1st or 0
        stats.gp_2nd = row.gp_2nd or 0
        stats.gp_3rd = row.gp_3rd or 0
        stats.daily_1st = row.daily_1st or 0
        stats.daily_2nd = row.daily_2nd or 0
        stats.daily_3rd = row.daily_3rd or 0
        stats.judge_awards = row.judge_awards or 0

    db.session.commit()
    print("--- update-user-stats batch completed ---")
