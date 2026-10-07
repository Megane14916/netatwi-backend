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
