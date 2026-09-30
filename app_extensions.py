"""Flask extensions and process-wide SQL timing hooks."""

import logging
import time

from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from sqlalchemy import event
from sqlalchemy.engine import Engine
from werkzeug.middleware.proxy_fix import ProxyFix

from models import db


logger = logging.getLogger("app")
limiter = Limiter(
    get_remote_address,
    default_limits=["10000 per day", "5000 per hour"],
    storage_uri="memory://",
)
migrate = Migrate()


@event.listens_for(Engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    conn.info.setdefault("query_start_time", []).append(time.time())


@event.listens_for(Engine, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    total = time.time() - conn.info["query_start_time"].pop(-1)
    if total > 0.05:
        logger.info(f"[SQL_SLOW] {total:.4f}s: {statement[:100]}...")


def init_extensions(app, frontend_url):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0, x_prefix=0)
    CORS(app, supports_credentials=True, origins=[frontend_url])
    db.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)
