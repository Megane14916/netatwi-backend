"""Explicit application creation and component registration."""

import logging
from pathlib import Path

from flask import Flask

from app.config import load_settings
from app.extensions import init_extensions
from app.hooks import register_hooks
from app.integrations import images


ROOT = Path(__file__).resolve().parents[1]


def create_app(config=None):
    """Create a configured application without a package-level default instance."""
    settings = load_settings(config)
    application = Flask("app", root_path=str(ROOT), instance_path=str(ROOT / "instance"))
    application.config.update(settings.flask_config)
    logging.basicConfig(level=logging.INFO)
    init_extensions(application, settings.frontend_url)

    # Register all models with the single extensions.db; never create tables here.
    from app import models
    from app.routes import BLUEPRINTS
    from app.cli import register_cli

    images.initialize_image_settings(application)
    for blueprint in BLUEPRINTS:
        application.register_blueprint(blueprint)
    register_cli(application)
    register_hooks(application)
    return application
