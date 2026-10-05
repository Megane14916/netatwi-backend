"""Capture cold imports, entry creation counts and resource paths before #52."""

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

import app as app_module


ROOT = Path(__file__).resolve().parents[1]


def run_isolated(source, *, environment=None):
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("module", [
    "models", "models.user", "services.posts", "services.contests",
    "integrations.cloud_tasks", "integrations.images", "cli.user_stats",
    "app_factory", "app_config", "app_extensions", "app_hooks", "runtime_dependencies",
])
def test_component_import_does_not_create_an_application_or_call_clients(module):
    environment = dict(os.environ)
    for key in ("SQLALCHEMY_DATABASE_URI", "SECRET_KEY", "FRONTEND_URL"):
        environment.pop(key, None)
    environment["FLASK_DEBUG"] = "False"
    run_isolated(f'''
        import importlib, socket, sys
        from flask import Flask
        import boto3
        from google.cloud import tasks_v2
        def reject(*args, **kwargs):
            raise AssertionError("Component imports must not initialize apps or clients")
        Flask.__init__ = reject
        socket.socket.connect = reject
        socket.socket.connect_ex = reject
        boto3.client = reject
        tasks_v2.CloudTasksClient = reject
        importlib.import_module({module!r})
        package = sys.modules.get("app")
        assert package is None or "app" not in vars(package)
    ''', environment=environment)


def test_cold_direct_entry_creates_only_one_app_and_upload_directory():
    run_isolated('''
        import os, runpy, socket
        from flask import Flask, current_app
        from unittest.mock import patch
        counts = {"apps": 0, "uploads": 0, "tables": 0, "server": 0}
        original_init = Flask.__init__
        original_makedirs = os.makedirs
        def init(self, *args, **kwargs):
            counts["apps"] += 1
            original_init(self, *args, **kwargs)
        def mkdir(path, *args, **kwargs):
            if path == "static/uploads":
                counts["uploads"] += 1
            return original_makedirs(path, *args, **kwargs)
        def create_all(self, *args, **kwargs):
            assert current_app.name == "app"
            counts["tables"] += 1
        def server(self, **options):
            assert options == {"host": "0.0.0.0", "port": 5001, "debug": False}
            counts["server"] += 1
        def reject(*args, **kwargs):
            raise AssertionError("External connections are forbidden")
        from flask_sqlalchemy import SQLAlchemy
        os.environ.pop("PORT", None)
        with patch.object(Flask, "__init__", init), patch.object(Flask, "run", server), patch.object(SQLAlchemy, "create_all", create_all), patch.object(os, "makedirs", mkdir), patch.object(socket.socket, "connect", reject):
            loaded = runpy.run_path("app.py", run_name="__main__")
        assert counts == {"apps": 1, "uploads": 1, "tables": 1, "server": 1}
        assert loaded["logger"].name == "__main__"
    ''')


def test_public_entry_repeated_imports_do_not_repeat_initialization():
    run_isolated('''
        import importlib, os
        from flask import Flask
        from unittest.mock import patch
        counts = {"apps": 0, "uploads": 0}
        original_init, original_makedirs = Flask.__init__, os.makedirs
        def init(self, *args, **kwargs):
            counts["apps"] += 1
            original_init(self, *args, **kwargs)
        def mkdir(path, *args, **kwargs):
            if path == "static/uploads": counts["uploads"] += 1
            return original_makedirs(path, *args, **kwargs)
        with patch.object(Flask, "__init__", init), patch.object(os, "makedirs", mkdir):
            import app
            first = app.app
            from app import app as again, create_app, db
            assert first is again is importlib.import_module("app").app
            assert first.extensions["sqlalchemy"] is db
            other = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
            assert other is not first
        assert counts == {"apps": 2, "uploads": 1}
    ''')


def test_resource_and_instance_paths_stay_at_repository_root():
    for application in (app_module.app, app_module.create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})):
        assert Path(application.root_path) == ROOT
        assert Path(application.static_folder) == ROOT / "static"
        assert Path(application.instance_path) == ROOT / "instance"
        assert app_module.UPLOAD_FOLDER == "static/uploads"
        with application.open_resource("Dockerfile") as resource:
            assert resource.read() == (ROOT / "Dockerfile").read_bytes()
