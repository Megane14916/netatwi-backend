"""Environment-backed Flask configuration."""

import os
from dataclasses import dataclass
from datetime import timedelta

from dotenv import load_dotenv


@dataclass(frozen=True)
class RuntimeSettings:
    flask_config: dict
    frontend_url: str
    backend_url: str | None
    is_local_dev: bool


def load_settings(overrides=None):
    load_dotenv()
    overrides = dict(overrides or {})

    is_local_dev = os.environ.get("FLASK_DEBUG") == "True"
    db_uri = overrides.get("SQLALCHEMY_DATABASE_URI") or os.environ.get(
        "SQLALCHEMY_DATABASE_URI"
    )
    secret_key = overrides.get("SECRET_KEY") or os.environ.get("SECRET_KEY")
    frontend_url = (
        overrides.get("FRONTEND_URL") or os.environ.get("FRONTEND_URL", "")
    ).rstrip("/")
    backend_url = "http://127.0.0.1:5001" if is_local_dev else os.environ.get("GCR_URL")

    if is_local_dev:
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
        db_uri = db_uri or "sqlite:///project.db"
        secret_key = secret_key or "a-very-secret-key-for-local-dev"
        frontend_url = frontend_url or "http://localhost:3000"

    if not db_uri:
        raise ValueError(
            "FATAL_ERROR: SQLALCHEMY_DATABASE_URI environment variable is not set."
        )
    if not secret_key:
        raise ValueError("FATAL_ERROR: SECRET_KEY environment variable is not set.")
    if not frontend_url:
        raise ValueError("FATAL_ERROR: FRONTEND_URL environment variable is not set.")

    session_cookie_config = (
        {
            "SESSION_COOKIE_SAMESITE": "Lax",
            "SESSION_COOKIE_SECURE": False,
            "SESSION_COOKIE_DOMAIN": "localhost",
        }
        if is_local_dev
        else {"SESSION_COOKIE_SAMESITE": "None", "SESSION_COOKIE_SECURE": True}
    )
    config = {
        "SECRET_KEY": secret_key,
        "SQLALCHEMY_DATABASE_URI": db_uri,
        "SQLALCHEMY_ENGINE_OPTIONS": {"pool_pre_ping": True, "pool_recycle": 300},
        "SESSION_COOKIE_HTTPONLY": True,
        "PERMANENT_SESSION_LIFETIME": timedelta(days=31),
        "MAX_CONTENT_LENGTH": 17 * 1024 * 1024,
        "UPLOAD_FOLDER": "static/uploads",
        "ALLOWED_EXTENSIONS": {"png", "jpg", "jpeg", "gif", "webp"},
        "USE_R2": os.environ.get("USE_R2", "False").lower() == "true",
        "R2_BUCKET_NAME": os.environ.get("R2_BUCKET_NAME"),
        "R2_PUBLIC_URL": os.environ.get("R2_PUBLIC_URL", "").rstrip("/"),
        "R2_ENDPOINT_URL": os.environ.get("R2_ENDPOINT_URL"),
        "R2_ACCESS_KEY_ID": os.environ.get("R2_ACCESS_KEY_ID"),
        "R2_SECRET_ACCESS_KEY": os.environ.get("R2_SECRET_ACCESS_KEY"),
        "X_CONSUMER_KEY": os.environ.get("X_CONSUMER_KEY"),
        "X_CONSUMER_SECRET": os.environ.get("X_CONSUMER_SECRET"),
        "GCP_PROJECT_ID": os.environ.get("GCP_PROJECT_ID"),
        "GCP_LOCATION": os.environ.get("GCP_LOCATION"),
        "GCP_QUEUE_NAME": os.environ.get("GCP_QUEUE_NAME"),
        "TASK_HANDLER_URL": os.environ.get("TASK_HANDLER_URL"),
        "GCR_URL": os.environ.get("GCR_URL"),
        "TASKS_OIDC_AUDIENCE": os.environ.get("TASKS_OIDC_AUDIENCE", ""),
        "TASKS_SERVICE_ACCOUNT_EMAIL": os.environ.get("TASKS_SERVICE_ACCOUNT_EMAIL", ""),
        **session_cookie_config,
        **overrides,
    }
    config["FRONTEND_URL"] = frontend_url
    config["R2_PUBLIC_URL"] = (config["R2_PUBLIC_URL"] or "").rstrip("/")
    return RuntimeSettings(config, frontend_url, backend_url, is_local_dev)
