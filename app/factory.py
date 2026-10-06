"""Application creation, runtime compatibility bindings and registration."""

import logging
import os
import re
import traceback
from datetime import datetime, timedelta, timezone

from flask import jsonify, redirect, request, session, url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from flask import Flask

from app.config import load_settings
from app.extensions import init_extensions
from app.hooks import register_hooks

from app.services import results as results_service
from app.integrations import images as image_storage
from app.integrations import cloud_tasks
from app.extensions import migrate
from app.models import (
    Bookmark,
    Comment,
    Contest,
    ContestResult,
    Notification,
    Post,
    User,
    Vote,
    db,
)


def create_base_app(config_overrides=None):
    settings = load_settings(config_overrides)
    app = Flask(
        "app",
        root_path=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        instance_path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "instance"),
    )
    app.config.update(settings.flask_config)
    logging.basicConfig(level=logging.INFO)
    init_extensions(app, settings.frontend_url)
    register_hooks(app)
    image_storage.initialize_image_settings(app)
    return app, settings


def initialize_application(namespace):
    """Populate an entry namespace, preserving its live compatibility seams."""
    namespace.update({
        "logging": logging,
        "os": os,
        "re": re,
        "traceback": traceback,
        "datetime": datetime,
        "timedelta": timedelta,
        "timezone": timezone,
        "jsonify": jsonify,
        "redirect": redirect,
        "request": request,
        "session": session,
        "url_for": url_for,
        "IntegrityError": IntegrityError,
        "joinedload": joinedload,
        "create_base_app": create_base_app,
        "results_service": results_service,
        "image_storage": image_storage,
        "cloud_tasks": cloud_tasks,
        "migrate": migrate,
        "Bookmark": Bookmark,
        "Comment": Comment,
        "Contest": Contest,
        "ContestResult": ContestResult,
        "Notification": Notification,
        "Post": Post,
        "User": User,
        "Vote": Vote,
        "db": db,
    })

    namespace["app"], namespace["runtime_settings"] = namespace["create_base_app"]()
    namespace["frontend_url"] = namespace["runtime_settings"].frontend_url
    namespace["backend_url"] = namespace["runtime_settings"].backend_url
    namespace["is_local_dev"] = namespace["runtime_settings"].is_local_dev
    namespace["logger"] = namespace["logging"].getLogger(namespace["__name__"])
    namespace["JST"] = namespace["timezone"](namespace["timedelta"](hours=9), "JST")

    from app.routes import BLUEPRINTS
    from app.routes.account import get_current_user, logout, withdraw_user
    from app.routes.core import index
    from app.routes.tasks import handle_contest_task
    from app.cli import process_contests_command, register_cli, update_user_stats

    namespace.update({
        "BLUEPRINTS": BLUEPRINTS,
        "get_current_user": get_current_user,
        "logout": logout,
        "withdraw_user": withdraw_user,
        "index": index,
        "handle_contest_task": handle_contest_task,
        "process_contests_command": process_contests_command,
        "register_cli": register_cli,
        "update_user_stats": update_user_stats,
    })


    def _register_extracted_routes(application):
        for blueprint in namespace["BLUEPRINTS"]:
            application.register_blueprint(blueprint)

    namespace["_register_extracted_routes"] = _register_extracted_routes

    namespace["_register_extracted_routes"](namespace["app"])
    namespace["register_cli"](namespace["app"])


    def create_app(config=None):
        """Create an independently configured app with the same routes and CLI."""
        application, _settings = namespace["create_base_app"](config)
        namespace["_register_extracted_routes"](application)
        namespace["register_cli"](application)
        return application

    namespace["create_app"] = create_app
