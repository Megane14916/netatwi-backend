"""Characterize helper behavior and the live compatibility bindings before #50."""

import importlib.util
from unittest.mock import Mock

import pytest

import app as app_module
import app.factory as app_factory
from app.routes import dependencies
from app.services import contest_lifecycle, posts, voting






@pytest.mark.parametrize(
    "name, argument",
    [
        ("allowed_file", "image.JPG"),
        ("calculate_weighted_length", "text"),
        ("save_file", object()),
        ("delete_file", "https://image.example/a.png"),
        ("get_cached_contest_results", 42),
        ("generate_contest_results", 42),
    ],
)
def test_helpers_use_current_app_globals_after_registration(app, monkeypatch, name, argument):
    replacement = Mock(return_value=object())
    monkeypatch.setattr(app_module, name, replacement)
    assert getattr(dependencies, name)(argument) is replacement.return_value
    replacement.assert_called_once_with(argument)


def test_services_observe_late_text_and_image_replacements(app, monkeypatch):
    length = Mock(return_value=77)
    save = Mock(return_value="replacement-image")
    monkeypatch.setattr(app_module, "calculate_weighted_length", length)
    monkeypatch.setattr(app_module, "save_file", save)
    assert posts.calculate_weighted_length("post") == 77
    assert voting.calculate_weighted_length("vote") == 77
    assert posts.save_file("file") == "replacement-image"
    assert length.call_args_list == [(("post",),), (("vote",),)]
    save.assert_called_once_with("file")


def test_logger_resolves_replacement_on_each_access(app, monkeypatch):
    first, second = Mock(), Mock()
    monkeypatch.setattr(app_module, "logger", first)
    voting.logger.info("first")
    monkeypatch.setattr(app_module, "logger", second)
    voting.logger.error("second")
    first.info.assert_called_once_with("first")
    second.error.assert_called_once_with("second")


def test_dependency_resolution_follows_active_application(app):
    other = app_module.create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    callbacks = [Mock(return_value="first"), Mock(return_value="second")]
    loggers = [Mock(), Mock()]
    for application, callback, logger in zip([app, other], callbacks, loggers):
        application.extensions["legacy_route_helpers"] = {
            "allowed_file": callback,
            "get_route_logger": lambda logger=logger: logger,
        }
        application.extensions["schedule_contest_task"] = callback
        with application.app_context():
            assert dependencies.allowed_file("name") == callback.return_value
            assert contest_lifecycle.schedule_contest_task(1, "event", "time") == callback.return_value
            dependencies.route_logger.info("entry")
        logger.info.assert_called_once_with("entry")
        assert callback.call_args_list == [(("name",),), ((1, "event", "time"),)]


def test_scheduler_observes_late_app_replacement(app, monkeypatch):
    callback = Mock(return_value="task")
    monkeypatch.setattr(app_module, "schedule_contest_task", callback)
    assert contest_lifecycle.schedule_contest_task(1, "start", "now") == "task"
    callback.assert_called_once_with(1, "start", "now")


def test_resolution_requires_application_context():
    with pytest.raises(RuntimeError):
        dependencies.allowed_file("image.png")
    with pytest.raises(RuntimeError):
        contest_lifecycle.schedule_contest_task(1, "start", "now")


def test_image_wrappers_pass_current_settings_callbacks_and_logger(monkeypatch):
    storage = app_module.image_storage
    save, delete = Mock(), Mock()
    client, logger = Mock(), Mock()
    monkeypatch.setattr(storage, "save_file", save)
    monkeypatch.setattr(storage, "delete_file", delete)
    values = dict(UPLOAD_FOLDER="temporary-upload", USE_R2=True, R2_BUCKET_NAME="bucket", R2_PUBLIC_URL="public")
    for name, value in values.items():
        monkeypatch.setattr(app_module, name, value)
    monkeypatch.setattr(app_module, "get_r2_client", client)
    monkeypatch.setattr(app_module, "logger", logger)
    app_module.save_file("file")
    app_module.delete_file("url")
    save.assert_called_once_with("file", **values, get_r2_client=client, logger=logger)
    values.pop("R2_PUBLIC_URL")
    delete.assert_called_once_with("url", **values, get_r2_client=client, logger=logger)
    client.assert_not_called()


@pytest.mark.parametrize("use_r2, expected", [("TrUe", True), (" true ", False), ("False", False)])
def test_image_settings_initialize_once_in_original_order(monkeypatch, use_r2, expected):
    events = []
    create_base = app_factory.create_base_app
    environ_get = app_module.os.environ.get

    def base(config=None):
        events.append("base")
        return create_base(config)

    def get(key, default=None):
        if key in {"USE_R2", "R2_BUCKET_NAME", "R2_PUBLIC_URL"}:
            events.append(key)
        return environ_get(key, default)

    monkeypatch.setenv("USE_R2", use_r2)
    monkeypatch.setenv("R2_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("R2_PUBLIC_URL", "https://images.example///")
    monkeypatch.setattr(app_factory, "create_base_app", base)
    monkeypatch.setattr(app_module.os.environ, "get", get)
    monkeypatch.setattr(app_module.os, "makedirs", lambda path, exist_ok: events.append((path, exist_ok)))
    spec = importlib.util.spec_from_file_location("issue50_entry", "app.py")
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    loaded = entry.__dict__
    assert events == ["base", ("static/uploads", True), "USE_R2", "R2_BUCKET_NAME", "R2_PUBLIC_URL"]
    assert loaded["UPLOAD_FOLDER"] == "static/uploads"
    assert loaded["ALLOWED_EXTENSIONS"] == {"png", "jpg", "jpeg", "gif", "webp"}
    assert loaded["USE_R2"] is expected
    assert loaded["R2_BUCKET_NAME"] == "test-bucket"
    assert loaded["R2_PUBLIC_URL"] == "https://images.example"
    monkeypatch.setenv("USE_R2", "different")
    events.clear()
    application = loaded["create_app"]({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    assert events == ["base"]
    namespace = entry.__dict__
    replacement = Mock(return_value="late")
    namespace["save_file"] = replacement
    with application.app_context():
        assert dependencies.save_file("file") == "late"
        assert dependencies.route_logger.name == "issue50_entry"
    replacement.assert_called_once_with("file")
    assert namespace["USE_R2"] is expected
