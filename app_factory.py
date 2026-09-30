"""Create a configured Flask instance before routes are registered."""

import logging

from flask import Flask

from app_config import load_settings
from app_extensions import init_extensions
from app_hooks import register_hooks


def create_base_app(config_overrides=None):
    settings = load_settings(config_overrides)
    app = Flask("app")
    app.config.update(settings.flask_config)
    logging.basicConfig(level=logging.INFO)
    init_extensions(app, settings.frontend_url)
    register_hooks(app)
    return app, settings
