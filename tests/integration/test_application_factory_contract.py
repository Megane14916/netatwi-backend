"""Explicit factory registration, WSGI, CLI and direct-entry contracts (#70)."""

import runpy
from pathlib import Path

import pytest
from flask import Flask
from flask.cli import ScriptInfo

from app import create_app
from app import factory
from app import cli
from app.extensions import db, limiter, migrate
from app.integrations import images
from app.routes import BLUEPRINTS


def test_factory_initialization_and_registration_order(monkeypatch):
    events = []
    def watch(owner, name, label):
        original = getattr(owner, name)
        def wrapped(*args, **kwargs):
            events.append(label)
            return original(*args, **kwargs)
        monkeypatch.setattr(owner, name, wrapped)
    for name in ("load_settings", "Flask", "init_extensions", "register_hooks"):
        watch(factory, name, name)
    watch(factory.logging, "basicConfig", "logging")
    watch(images, "initialize_image_settings", "images")
    watch(cli, "register_cli", "cli")
    original = Flask.register_blueprint
    def register(application, blueprint, **options):
        events.append(blueprint.name)
        return original(application, blueprint, **options)
    monkeypatch.setattr(Flask, "register_blueprint", register)
    for name in ("first", "second"):
        events.clear()
        application = create_app({"TESTING": True, "SECRET_KEY": name, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
        assert events == ["load_settings", "Flask", "logging", "init_extensions", "images"] + [b.name for b in BLUEPRINTS] + ["cli", "register_hooks"]
        assert application.config["SECRET_KEY"] == name
        assert application.extensions["sqlalchemy"] is db
        assert application.extensions["migrate"].migrate is migrate
        assert limiter in application.extensions["limiter"]


def test_multiple_apps_preserve_routes_commands_and_hook_counts(app):
    applications = [app] + [create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "SECRET_KEY": name}) for name in ("one", "two")]
    for application in applications:
        assert list(application.blueprints) == [bp.name for bp in BLUEPRINTS]
        assert [(r.rule, r.endpoint, r.methods) for r in application.url_map.iter_rules()] == [(r.rule, r.endpoint, r.methods) for r in app.url_map.iter_rules()]
        assert len(application.view_functions) == 36
        for endpoint, view in app.view_functions.items():
            if endpoint != "static":
                assert application.view_functions[endpoint] is view
        assert application.cli.commands == app.cli.commands
        assert application.before_request_funcs == app.before_request_funcs
        assert list(application.after_request_funcs) == list(app.after_request_funcs)
        for key, hooks in app.after_request_funcs.items():
            current = application.after_request_funcs[key]
            assert len(current) == len(hooks)
            assert [getattr(h, "__name__", getattr(h, "func", None)) for h in current] == [getattr(h, "__name__", getattr(h, "func", None)) for h in hooks]
            assert current[-1] is hooks[-1]
        assert application.error_handler_spec == app.error_handler_spec
    assert applications[1].config["SECRET_KEY"] == "one"
    assert applications[2].config["SECRET_KEY"] == "two"


def test_factory_config_reaches_extensions_without_namespace_callbacks():
    config = {"TESTING": True, "SECRET_KEY": "explicit", "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"}
    application = create_app(config)
    assert application.config["SECRET_KEY"] == "explicit"
    assert application.extensions["sqlalchemy"] is db
    assert "legacy_route_helpers" not in application.extensions
    assert "schedule_contest_task" not in application.extensions


@pytest.mark.parametrize("mode", ["wsgi", "factory"])
def test_flask_entry_resolves_new_wsgi_and_factory(mode):
    path = "wsgi:app" if mode == "wsgi" else "app:create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})"
    application = ScriptInfo(app_import_path=path).load_app()
    assert application.test_client().get("/api/me").get_json() == {"logged_in": False}
    assert {"db", "process-contests", "update-user-stats"} <= set(application.cli.commands)


@pytest.mark.parametrize("port,expected", [(None, 5001), ("8123", 8123)])
def test_direct_entry_creates_tables_then_runs_server(monkeypatch, capsys, port, expected):
    events = []
    if port is None:
        monkeypatch.delenv("PORT", raising=False)
    else:
        monkeypatch.setenv("PORT", port)
    def create_all():
        from flask import current_app
        events.append(("tables", current_app._get_current_object()))
    def run(application, **options):
        events.append(("server", application, options))
    monkeypatch.setattr(db, "create_all", create_all)
    monkeypatch.setattr(Flask, "run", run)
    loaded = runpy.run_path("app.py", run_name="__main__")
    application = events[0][1]
    assert events == [("tables", application), ("server", application, {"host": "0.0.0.0", "port": expected, "debug": False})]
    assert "app" not in loaded
    assert capsys.readouterr().out == "Database tables created (if not existed).\n"


def test_auxiliary_script_imports_are_cold_and_use_shared_db(monkeypatch):
    assert Path("sync_comment_counts.py").is_file()
    monkeypatch.setattr(Flask, "__init__", lambda *_args, **_kwargs: pytest.fail("script import created app"))
    loaded = runpy.run_path("sync_comment_counts.py", run_name="script_import")
    assert loaded["create_app"] is create_app
    assert loaded["db"] is db
    assert "app" not in loaded
