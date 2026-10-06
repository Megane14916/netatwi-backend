"""HTTP and Flask registration guarantees for the standard Blueprint switch."""

import json
from pathlib import Path

from flask import request, url_for, Blueprint


def test_standard_blueprints_keep_all_urls_and_add_only_the_intended_namespace(app):
    mapping = json.loads((Path(__file__).parents[2] / "docs/refactor/issue-68-endpoints.json").read_text(encoding="utf-8"))
    actual = {(r.rule, tuple(sorted(r.methods - {"HEAD", "OPTIONS"})), r.endpoint) for r in app.url_map.iter_rules()}
    assert len(actual) == len(mapping) == 36
    assert all(type(bp) is Blueprint for bp in app.blueprints.values())
    assert actual == {(r["path"], tuple(r["methods"]), r["endpoint"]) for r in mapping}
    assert {r["old"] for r in mapping if r["old"] != "static"}.isdisjoint(app.view_functions)
    for row in mapping:
        if row["old"] == "static":
            assert row["endpoint"] == "static"
            continue
        assert row["endpoint"].split(".", 1)[1] == row["old"]
    with app.test_request_context("/api/me"):
        assert request.endpoint == "account.get_current_user"
        assert request.blueprint == "account"
        assert url_for("account.get_current_user") == "/api/me"


def test_namespaced_requests_keep_hooks_cors_and_options(client):
    response = client.get("/api/me", headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 200
    assert response.get_json() == {"logged_in": False}
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:3000"
    assert response.headers["Access-Control-Allow-Credentials"] == "true"
    assert response.headers["Cache-Control"] == "no-store, no-cache, must-revalidate, private"
    preflight = client.options("/api/me", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
    assert preflight.status_code == 200
    assert "GET" in preflight.headers["Access-Control-Allow-Methods"]


def test_judge_login_explicit_limit_rejects_the_sixth_request(client):
    responses = [client.post("/api/contests/1/judge/login", json={"password": "bad"}, environ_overrides={"REMOTE_ADDR": "192.0.2.68"}) for _ in range(6)]
    assert [r.status_code for r in responses] == [401] * 5 + [429]


def test_default_hourly_limit_still_applies_to_standard_blueprints(client):
    # Exercise the configured 5000/hour limit, including the first rejected call.
    statuses = [client.get("/", environ_overrides={"REMOTE_ADDR": "192.0.2.69"}).status_code for _ in range(5001)]
    assert statuses == [200] * 5000 + [429]
