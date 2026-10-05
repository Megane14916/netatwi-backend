"""Verify the canonical package and its legacy compatibility connections."""

import ast
from importlib import import_module
from pathlib import Path

import app
from tests.integration.test_package_entry_contract import run_isolated


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "app"


def test_package_wins_over_same_named_script_and_handlers_live_in_package():
    assert Path(app.__file__) == PACKAGE / "__init__.py"
    assert list(app.__path__) == [str(PACKAGE)]
    for endpoint, view in app.app.view_functions.items():
        if endpoint != "static":
            assert view.__module__.startswith("app.routes.")
    assert app.create_app.__module__ == "app.factory"
    assert app.db is import_module("app.extensions").db
    assert len(app.db.Model.registry.mappers) == 10
    assert all(m.class_.__module__.startswith("app.models.") for m in app.db.Model.registry.mappers)


def test_legacy_modules_share_canonical_bodies_and_mutable_module_state():
    flat = {"app_factory": "factory", "app_config": "config", "app_extensions": "extensions", "app_hooks": "hooks", "runtime_dependencies": "runtime_dependencies"}
    for old, new in flat.items():
        assert import_module(old) is import_module("app." + new)
    groups = {"models": "models", "blueprints": "routes", "services": "services", "integrations": "integrations", "cli": "cli"}
    for old, new in groups.items():
        legacy_root = import_module(old)
        canonical_root = import_module("app." + new)
        if old not in {"services", "integrations"}:
            assert legacy_root is canonical_root
        for path in (PACKAGE / new).glob("*.py"):
            if path.name == "__init__.py":
                continue
            canonical = import_module(f"app.{new}.{path.stem}")
            assert import_module(f"{old}.{path.stem}") is canonical
            assert Path(canonical.__file__) == path
    assert import_module("models.base").db is app.db


def test_legacy_cloud_tasks_cache_patch_is_seen_by_canonical_module(monkeypatch):
    old = import_module("integrations.cloud_tasks")
    canonical = import_module("app.integrations.cloud_tasks")
    cache = object()
    monkeypatch.setattr(old, "_cloud_tasks_client", cache)
    assert canonical._cloud_tasks_client is cache
    assert app.cloud_tasks is canonical


def test_cold_direct_entry_publishes_the_same_app_without_second_generation():
    run_isolated('''
        import runpy
        from flask import Flask
        from flask_sqlalchemy import SQLAlchemy
        from unittest.mock import patch
        count = []
        original_init = Flask.__init__
        def init(self, *args, **kwargs):
            count.append(self)
            original_init(self, *args, **kwargs)
        with patch.object(Flask, "__init__", init), patch.object(Flask, "run"), patch.object(SQLAlchemy, "create_all"):
            loaded = runpy.run_path("app.py", run_name="__main__")
            from app import app, create_app, db
            assert app is loaded["app"]
            assert create_app is loaded["create_app"]
            assert db is loaded["db"]
        assert count == [app]
    ''')


def test_canonical_imports_do_not_use_legacy_paths_or_service_to_route_dependencies():
    legacy = {"models", "blueprints", "services", "integrations", "cli", "app_factory", "app_config", "app_extensions", "app_hooks", "runtime_dependencies"}
    for path in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                assert node.module.split(".")[0] not in legacy, path
                if path.parent.name == "services":
                    assert not node.module.startswith("app.routes"), path
            elif isinstance(node, ast.Import):
                assert all(a.name.split(".")[0] not in legacy for a in node.names), path


def test_failed_public_resolution_can_retry_without_a_partial_application():
    run_isolated('''
        import os
        import app
        import app.config as config
        config.load_dotenv = lambda: None
        os.environ["FLASK_DEBUG"] = "False"
        for key in ("SQLALCHEMY_DATABASE_URI", "SECRET_KEY", "FRONTEND_URL"):
            os.environ.pop(key, None)
        try:
            app.app
        except ValueError as error:
            assert "SQLALCHEMY_DATABASE_URI" in str(error)
        else:
            raise AssertionError("Missing configuration must fail")
        assert "app" not in vars(app)
        assert "create_app" not in vars(app)
        os.environ.update({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "SECRET_KEY": "retry", "FRONTEND_URL": "https://frontend.example"})
        resolved = app.app
        assert resolved.config["SECRET_KEY"] == "retry"
        assert len(resolved.view_functions) == 36
        assert resolved is app.app
    ''')


def test_concurrent_factory_export_resolution_creates_one_default_app():
    run_isolated('''
        from concurrent.futures import ThreadPoolExecutor
        from flask import Flask
        from unittest.mock import patch
        import app
        created = []
        original_init = Flask.__init__
        def init(self, *args, **kwargs):
            created.append(self)
            original_init(self, *args, **kwargs)
        with patch.object(Flask, "__init__", init), ThreadPoolExecutor(max_workers=8) as pool:
            factories = list(pool.map(lambda _: app.create_app, range(8)))
        assert all(factory is factories[0] for factory in factories)
        assert created == [app.app]
        assert len(app.app.view_functions) == 36
    ''')
