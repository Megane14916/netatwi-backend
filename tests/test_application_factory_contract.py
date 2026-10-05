"""Capture creation, registration and entry contracts before moving #51."""

import importlib.util
import runpy
from pathlib import Path
from unittest.mock import Mock

import pytest
from flask import Flask
from flask.cli import ScriptInfo

import app as app_module
import app_factory
import cli
import runtime_dependencies
from app_extensions import limiter, migrate
from models import db


def load_entry(name):
    spec = importlib.util.spec_from_file_location(name, "app.py")
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    return entry


def test_bootstrap_and_factory_preserve_initialization_order(monkeypatch):
    events = []

    def watch(owner, name, label):
        original = getattr(owner, name)

        def wrapped(*args, **kwargs):
            events.append(label)
            return original(*args, **kwargs)

        monkeypatch.setattr(owner, name, wrapped)

    for name in ("load_settings", "Flask", "init_extensions", "register_hooks"):
        watch(app_factory, name, name)
    watch(app_factory.logging, "basicConfig", "logging")
    watch(app_module.image_storage, "initialize_image_settings", "images")
    watch(runtime_dependencies, "register_helper_bindings", "bindings")
    original_register = Flask.register_blueprint

    def register(application, blueprint, **options):
        events.append(blueprint.name)
        return original_register(application, blueprint, **options)

    monkeypatch.setattr(Flask, "register_blueprint", register)
    watch(cli, "register_cli", "cli")
    entry = load_entry("issue51_entry")
    before_routes = ["load_settings", "Flask", "logging", "init_extensions", "register_hooks"]
    routes = [bp.name for bp in entry.BLUEPRINTS]
    assert events == before_routes + ["images", "bindings"] + routes + ["cli"]
    assert entry.logger.name == "issue51_entry"
    assert entry.db is db
    assert entry.migrate is migrate
    events.clear()
    application = entry.create_app({"TESTING": True, "SECRET_KEY": "other", "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    assert events == before_routes + ["bindings"] + routes + ["cli"]
    assert application is not entry.app
    assert application.config["SECRET_KEY"] == "other"
    assert entry.app.config["SECRET_KEY"] == "test-only-secret-key"
    assert application.extensions["sqlalchemy"] is db
    assert application.extensions["migrate"].migrate is migrate
    assert limiter in application.extensions["limiter"]


def test_multiple_apps_keep_registration_order_function_identity_and_hook_counts():
    applications = [app_module.app] + [app_module.create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "SECRET_KEY": name}) for name in ("one", "two")]
    first = applications[0]
    for application in applications:
        assert list(application.blueprints) == [bp.name for bp in app_module.BLUEPRINTS]
        assert [(r.rule, r.endpoint, r.methods) for r in application.url_map.iter_rules()] == [(r.rule, r.endpoint, r.methods) for r in first.url_map.iter_rules()]
        assert len(application.view_functions) == 36
        for endpoint, view in first.view_functions.items():
            if endpoint != "static":
                assert application.view_functions[endpoint] is view
        assert list(application.cli.commands) == list(first.cli.commands)
        assert all(application.cli.commands[n] is first.cli.commands[n] for n in first.cli.commands)
        assert application.before_request_funcs == first.before_request_funcs
        assert list(application.after_request_funcs) == list(first.after_request_funcs)
        for key, hooks in first.after_request_funcs.items():
            current = application.after_request_funcs[key]
            assert len(current) == len(hooks)
            assert [getattr(h, "__name__", getattr(h, "func", None)) for h in current] == [getattr(h, "__name__", getattr(h, "func", None)) for h in hooks]
            assert current[-1] is hooks[-1]
        assert application.error_handler_spec == first.error_handler_spec
    assert applications[1].config["SECRET_KEY"] == "one"
    assert applications[2].config["SECRET_KEY"] == "two"


def test_factory_keeps_live_entry_callback_and_cli_seams(monkeypatch):
    entry = load_entry("issue51_callbacks")
    register = Mock(wraps=entry._register_extracted_routes)
    command_register = Mock(wraps=entry.register_cli)
    base = Mock(wraps=entry.create_base_app)
    monkeypatch.setattr(entry, "_register_extracted_routes", register)
    monkeypatch.setattr(entry, "register_cli", command_register)
    monkeypatch.setattr(entry, "create_base_app", base)
    config = {"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"}
    application = entry.create_app(config)
    base.assert_called_once_with(config)
    register.assert_called_once_with(application)
    command_register.assert_called_once_with(application)
    save = Mock(return_value="image")
    logger = Mock()
    scheduler = Mock(return_value="task")
    monkeypatch.setattr(entry, "save_file", save)
    monkeypatch.setattr(entry, "logger", logger)
    monkeypatch.setattr(entry, "schedule_contest_task", scheduler)
    for active in (entry.app, application):
        with active.app_context():
            assert runtime_dependencies.save_file("file") == "image"
            runtime_dependencies.route_logger.info("entry")
            assert runtime_dependencies.schedule_contest_task(1, "event", "time") == "task"
    assert save.call_count == logger.info.call_count == scheduler.call_count == 2


@pytest.mark.parametrize("mode", ["default", "factory"])
def test_flask_entry_resolves_app_and_factory(mode):
    path = "app:app" if mode == "default" else "app:create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})"
    application = ScriptInfo(app_import_path=path).load_app()
    if mode == "default":
        assert application is app_module.app
    else:
        assert application is not app_module.app
    assert application.test_client().get("/api/me").get_json() == {"logged_in": False}
    assert {"db", "process-contests", "update-user-stats"} <= set(application.cli.commands)


@pytest.mark.parametrize("port, expected", [(None, 5001), ("8123", 8123)])
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
    assert events == [("tables", loaded["app"]), ("server", loaded["app"], {"host": "0.0.0.0", "port": expected, "debug": False})]
    assert loaded["logger"].name == "__main__"
    assert capsys.readouterr().out == "Database tables created (if not existed).\n"


@pytest.mark.parametrize("path", ["sync_comment_counts.py", "scripts/sync_comment_count.py", "scripts/recalculate_contest_stats.py"])
def test_auxiliary_script_imports_keep_app_and_db(path):
    assert Path(path).is_file()
    loaded = runpy.run_path(path, run_name="issue51_script")
    assert loaded["app"] is app_module.app
    assert loaded["db"] is db
