"""Rollback ownership for service mutations that may also run outside HTTP."""

from functools import wraps

from app.extensions import db


def rollback_on_failure(operation):
    @wraps(operation)
    def run(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except Exception:
            db.session.rollback()
            raise
    return run


def lock_contest(contest_id):
    """Serialize lifecycle writers and refresh flags after any lock wait.

    The caller owns commit/rollback. Autoflush preserves changes made earlier
    in the same transaction before refreshing the ORM identity-map entry.
    """
    from app.models import Contest

    return (Contest.query.filter_by(id=contest_id).populate_existing()
            .with_for_update().first())
