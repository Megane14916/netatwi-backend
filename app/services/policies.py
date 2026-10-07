"""Shared permission and UTC period predicates; callers own HTTP responses."""

import os
from datetime import timezone


def is_authenticated(session):
    # The request hook invalidates missing/deleted accounts before routes run.
    return "user_id" in session


def is_admin(session):
    admins = {
        name.strip()
        for name in os.environ.get("ADMIN_SCREEN_NAMES", "dummy_admin1,dummy_admin2").split(",")
        if name.strip()
    }
    return is_authenticated(session) and session.get("screen_name") in admins


def is_judge(contest_id, judge_contests):
    return contest_id in judge_contests


def is_owner(resource, user_id):
    return resource.user_id == user_id


def in_period(now, start, end):
    return start.replace(tzinfo=timezone.utc) <= now < end.replace(tzinfo=timezone.utc)


def has_reached(now, boundary):
    return now >= boundary.replace(tzinfo=timezone.utc)
