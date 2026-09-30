"""Contract captured before separating app creation from route definitions."""

import json
from datetime import timedelta
from pathlib import Path

from app import app as production_app, create_app
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.exceptions import RequestEntityTooLarge


ROUTES = json.loads(
    (Path(__file__).parent / "fixtures" / "url_map.json").read_text(encoding="utf-8")
)


def route_map(flask_app):
    routes = [
        {
            "endpoint": rule.endpoint,
            "path": rule.rule,
            "methods": sorted(rule.methods - {"HEAD", "OPTIONS"}),
        }
        for rule in flask_app.url_map.iter_rules()
    ]
    return sorted(
        routes, key=lambda route: (route["path"], route["methods"], route["endpoint"])
    )


def test_production_url_map_matches_pre_refactor_snapshot():
    assert route_map(production_app) == ROUTES


def test_factory_creates_isolated_app_with_the_same_routes_and_cli():
    first = create_app({"TESTING": True, "SECRET_KEY": "first"})
    second = create_app({"TESTING": True, "SECRET_KEY": "second"})

    assert first is not second
    assert first.config["SECRET_KEY"] == "first"
    assert second.config["SECRET_KEY"] == "second"
    assert route_map(first) == route_map(second) == ROUTES
    assert {"process-contests", "update-user-stats", "db"} <= set(first.cli.commands)
    assert first.test_client().get("/api/me").get_json() == {"logged_in": False}


def test_production_configuration_and_cli_entry_points():
    config = production_app.config
    assert config["SQLALCHEMY_DATABASE_URI"] == "sqlite:///:memory:"
    assert config["SECRET_KEY"] == "test-only-secret-key"
    assert config["SQLALCHEMY_ENGINE_OPTIONS"] == {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }
    assert config["SESSION_COOKIE_HTTPONLY"] is True
    assert config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert config["SESSION_COOKIE_SECURE"] is False
    assert config["SESSION_COOKIE_DOMAIN"] == "localhost"
    assert config["PERMANENT_SESSION_LIFETIME"] == timedelta(days=31)
    assert config["MAX_CONTENT_LENGTH"] == 17 * 1024 * 1024
    assert isinstance(production_app.wsgi_app, ProxyFix)
    assert {"process-contests", "update-user-stats"} <= set(production_app.cli.commands)


def test_production_hooks_and_payload_error(client):
    response = client.get("/api/me", headers={"Origin": "http://localhost:3000"})
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:3000"
    assert response.headers["Cache-Control"] == "no-store, no-cache, must-revalidate, private"
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["Expires"] == "0"
    assert response.headers["Vary"] == "Cookie"

    with production_app.test_request_context():
        oversized = production_app.make_response(
            production_app.handle_http_exception(RequestEntityTooLarge())
        )
    assert oversized.status_code == 413
    assert oversized.get_json() == {
        "error": "画像の合計サイズが上限を超えています（最大16 MiB）",
        "code": "PAYLOAD_TOO_LARGE",
        "maxBytes": 16 * 1024 * 1024,
    }
