"""News behavior captured before the issue #48 service extraction."""

import builtins
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Query

from app.routes import news as routes
from app.models import News, db


NOW = datetime(2026, 1, 1, 12)
MISSING = {"error": "ツイートIDまたはURLは必須です。"}
ADD_ERROR = {"error": "ニュースの追加に失敗しました。"}
DELETE_ERROR = {"error": "ニュースの削除に失敗しました。"}


def transactions(monkeypatch):
    events = []
    for name in ("add", "delete", "commit", "rollback"):
        original = getattr(db.session, name)

        def call(*args, _name=name, _original=original, **kwargs):
            events.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(db.session, name, call)
    return events


def regex_imports(monkeypatch):
    original = builtins.__import__
    calls = []

    def importing(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "re" and globals and globals.get("__name__") in ("app.routes.news", "app.services.news"):
            calls.append("re")
        return original(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", importing)
    return calls


@pytest.fixture
def admin(client, user_factory):
    user = user_factory("test_admin")
    with client.session_transaction() as session:
        session["user_id"] = user.id
        session["screen_name"] = "test_admin"


@pytest.fixture
def saved_news(app):
    row = News(tweet_id="existing", created_at=NOW)
    db.session.add(row)
    db.session.commit()
    return row


def test_complete_public_and_admin_lists_keep_order_limit_and_naive_isoformat(client, admin, monkeypatch):
    rows = [News(tweet_id=f"tweet-{i}", created_at=NOW + timedelta(minutes=i)) for i in range(25)]
    db.session.add_all(rows)
    db.session.commit()
    expected = [{"id": row.id, "tweet_id": f"tweet-{i}", "created_at": f"2026-01-01T12:{i:02d}:00"}
                for i, row in reversed(list(enumerate(rows)))]
    events = transactions(monkeypatch)
    public = client.get("/api/news")
    management = client.get("/api/admin/news")
    assert public.status_code == management.status_code == 200
    assert public.get_json() == expected[:20] and management.get_json() == expected
    assert events == []


@pytest.mark.parametrize("path", ("/api/news", "/api/admin/news"))
def test_empty_lists_have_200_empty_array(client, admin, monkeypatch, path):
    events = transactions(monkeypatch)
    response = client.get(path)
    assert response.status_code == 200 and response.get_json() == []
    assert events == []


@pytest.mark.parametrize("value, stored", [
    ("123456", "123456"), ("https://x.com/example/status/123456", "123456"),
    ("https://twitter.com/user/status/789?ref=share", "789"),
    ("anything status/00123suffix status/999", "00123"),
    ("https://untrusted.example/status/456", "456"),
    ("status/１２３", "１２３"), ("status/no-number", "status/no-number"),
    ("STATUS/123", "STATUS/123"), (" arbitrary text ", " arbitrary text "), ("   ", "   "),
])
def test_add_keeps_id_url_regex_and_unvalidated_strings(client, admin, monkeypatch, value, stored):
    events = transactions(monkeypatch)
    imports = regex_imports(monkeypatch)
    response = client.post("/api/admin/news", json={"tweet_id": value, "ignored": "extra"})
    assert response.status_code == 201
    payload = response.get_json()
    assert payload == {"message": "ニュースを追加しました。", "id": payload["id"]}
    assert type(payload["id"]) is int
    assert db.session.get(News, payload["id"]).tweet_id == stored
    assert events == ["add", "commit"] and imports == ["re"]


@pytest.mark.parametrize("data", ({}, {"tweet_id": None}, {"tweet_id": ""}, {"tweet_id": 0},
                                  {"tweet_id": False}, {"tweet_id": []}, {"tweet_id": {}}))
def test_missing_or_falsy_id_returns_400_without_import_or_transaction(client, admin, monkeypatch, data):
    events = transactions(monkeypatch)
    imports = regex_imports(monkeypatch)
    response = client.post("/api/admin/news", json=data)
    assert response.status_code == 400 and response.get_json() == MISSING
    assert events == [] and imports == [] and News.query.count() == 0


@pytest.mark.parametrize("value", (123, True, [123], {"id": 123}))
def test_truthy_nonstring_id_keeps_regex_failure_and_rollback(client, admin, monkeypatch, capsys, value):
    events = transactions(monkeypatch)
    imports = regex_imports(monkeypatch)
    response = client.post("/api/admin/news", json={"tweet_id": value})
    assert response.status_code == 500 and response.get_json() == ADD_ERROR
    assert events == ["rollback"] and imports == ["re"] and News.query.count() == 0
    assert "!!! ERROR at POST /api/admin/news:" in capsys.readouterr().out


@pytest.mark.parametrize("body, content_type", [('null', "application/json"), ('[]', "application/json"),
                                              ('"text"', "application/json"), ('{', "application/json"),
                                              ("tweet_id=123", "text/plain"), ("", "application/json")])
def test_invalid_http_input_is_caught_and_rolled_back(client, admin, monkeypatch, body, content_type):
    events = transactions(monkeypatch)
    imports = regex_imports(monkeypatch)
    response = client.post("/api/admin/news", data=body, content_type=content_type)
    assert response.status_code == 500 and response.get_json() == ADD_ERROR
    assert events == ["rollback"] and imports == [] and News.query.count() == 0


def test_duplicate_additions_remain_allowed(client, admin, monkeypatch):
    events = transactions(monkeypatch)
    first = client.post("/api/admin/news", json={"tweet_id": "123"})
    second = client.post("/api/admin/news", json={"tweet_id": "123"})
    assert first.status_code == second.status_code == 201
    assert first.get_json()["id"] != second.get_json()["id"]
    assert [row.tweet_id for row in News.query.all()] == ["123", "123"]
    assert events == ["add", "commit", "add", "commit"]


@pytest.mark.parametrize("action", ("list", "add", "delete"))
@pytest.mark.parametrize("state, status", [("anonymous", 401), ("name_only", 401), ("ordinary", 403),
                                         ("id_only", 403), ("authorized", 200), ("falsy_id", 401)])
def test_auth_precedes_json_and_news_queries_and_requires_active_user(client, monkeypatch, user_factory, action, state, status):
    user = user_factory("test_admin")
    with client.session_transaction() as session:
        if state not in ("anonymous", "name_only"):
            session["user_id"] = None if state == "falsy_id" else user.id
        if state not in ("anonymous", "id_only"):
            session["screen_name"] = "ordinary" if state == "ordinary" else "test_admin"
    monkeypatch.setenv("ADMIN_SCREEN_NAMES", " , test_admin , ")
    events = transactions(monkeypatch)
    reads = []
    original_all, original_get = Query.all, Query.get

    def read(query):
        reads.append("all")
        return original_all(query)

    def get(query, ident):
        reads.append("get")
        return original_get(query, ident)

    monkeypatch.setattr(Query, "all", read)
    monkeypatch.setattr(Query, "get", get)
    if action == "list":
        response = client.get("/api/admin/news")
        expected = status
    elif action == "add":
        response = client.post("/api/admin/news", data="{", content_type="application/json")
        expected = 500 if status == 200 else status
    else:
        response = client.delete("/api/admin/news/987654")
        expected = 404 if status == 200 else status
    assert response.status_code == expected
    if status != 200:
        assert response.get_json() == {"error": "Login required" if status == 401 else "Forbidden: Admins only"}
        assert events == [] and reads == []
    else:
        assert events == (["rollback"] if action == "add" else [])
        assert reads == (["all"] if action == "list" else ["get"] if action == "delete" else [])


@pytest.mark.parametrize("setting, screen_name, status", [(None, "dummy_admin1", 200),
                                                        (None, "dummy_admin2", 200),
                                                        ("", "dummy_admin1", 403),
                                                        ("Test_Admin", "test_admin", 403)])
def test_default_empty_and_case_sensitive_admin_settings(client, monkeypatch, user_factory, setting, screen_name, status):
    user = user_factory(screen_name)
    if setting is None:
        monkeypatch.delenv("ADMIN_SCREEN_NAMES", raising=False)
    else:
        monkeypatch.setenv("ADMIN_SCREEN_NAMES", setting)
    with client.session_transaction() as session:
        session["user_id"] = user.id
        session["screen_name"] = screen_name
    assert client.get("/api/admin/news").status_code == status


@pytest.mark.parametrize("path", ("/api/news", "/api/admin/news"))
@pytest.mark.parametrize("stage", ("query", "format", "json"))
def test_list_failures_keep_500_print_without_rollback(client, admin, saved_news, monkeypatch, capsys, path, stage):
    events = transactions(monkeypatch)

    def fail(*_args, **_kwargs):
        raise RuntimeError("list failure")

    if stage == "query":
        monkeypatch.setattr(Query, "all", fail)
    elif stage == "format":
        monkeypatch.setattr(Query, "all", lambda _query: [SimpleNamespace(id=1, tweet_id="123", created_at=SimpleNamespace(isoformat=fail))])
    else:
        original = routes.jsonify

        def encode(payload):
            if isinstance(payload, list):
                fail()
            return original(payload)

        monkeypatch.setattr(routes, "jsonify", encode)
    response = client.get(path)
    assert response.status_code == 500 and response.get_json() == {"error": "ニュースの取得に失敗しました。"}
    output = capsys.readouterr()
    assert f"!!! ERROR at GET {path}: list failure" in output.out and output.err == ""
    assert events == []


def test_delete_then_repeat_preserves_not_found_without_second_transaction(client, admin, saved_news, monkeypatch):
    ident = saved_news.id
    events = transactions(monkeypatch)
    first = client.delete(f"/api/admin/news/{ident}")
    assert first.status_code == 200 and first.get_json() == {"message": "ニュースを削除しました。"}
    assert db.session.get(News, ident) is None
    second = client.delete(f"/api/admin/news/{ident}")
    assert second.status_code == 404 and second.get_json() == {"error": "ニュースが見つかりません。"}
    assert events == ["delete", "commit"]


@pytest.mark.parametrize("action, stage", [("add", "add"), ("add", "commit"), ("delete", "get"),
                                         ("delete", "delete"), ("delete", "commit"),
                                         ("add", "json"), ("delete", "json")])
def test_write_failures_keep_transaction_order_and_partial_commit(client, admin, saved_news, monkeypatch, capsys, action, stage):
    ident = saved_news.id
    events = transactions(monkeypatch)

    def fail(*_args, **_kwargs):
        raise RuntimeError("write failure")

    if stage == "get":
        monkeypatch.setattr(Query, "get", fail)
    elif stage == "json":
        original = routes.jsonify

        def encode(payload):
            events.append("json")
            if "message" in payload:
                fail()
            return original(payload)

        monkeypatch.setattr(routes, "jsonify", encode)
    else:
        def operation(*_args, **_kwargs):
            events.append(stage)
            fail()

        monkeypatch.setattr(db.session, stage, operation)
    path = "/api/admin/news" if action == "add" else f"/api/admin/news/{ident}"
    response = client.post(path, json={"tweet_id": "new"}) if action == "add" else client.delete(path)
    assert response.status_code == 500 and response.get_json() == (ADD_ERROR if action == "add" else DELETE_ERROR)
    expected = (["add"] if action == "add" else ["delete"]) if stage != "get" else []
    if stage in ("commit", "json"):
        expected.append("commit")
    if stage == "json":
        expected.append("json")
    expected.append("rollback")
    if stage == "json":
        expected.append("json")
    assert events == expected
    rows = {row.tweet_id for row in News.query.all()}
    assert rows == ({"existing", "new"} if action == "add" and stage == "json"
                    else set() if action == "delete" and stage == "json" else {"existing"})
    output = capsys.readouterr()
    assert f"!!! ERROR at {'POST' if action == 'add' else 'DELETE'} {path}: write failure" in output.out
    assert output.err == ""


def test_post_commit_id_refresh_failure_cannot_undo_addition(client, admin, monkeypatch):
    events = transactions(monkeypatch)
    original_commit = db.session.commit
    committed = False

    def commit():
        nonlocal committed
        original_commit()
        committed = True

    def fail_refresh(_conn, _cursor, statement, _parameters, _context, _executemany):
        if committed and statement.lstrip().upper().startswith("SELECT"):
            raise RuntimeError("refresh failure")

    monkeypatch.setattr(db.session, "commit", commit)
    event.listen(db.engine, "before_cursor_execute", fail_refresh)
    try:
        response = client.post("/api/admin/news", json={"tweet_id": "123"})
    finally:
        event.remove(db.engine, "before_cursor_execute", fail_refresh)
    assert response.status_code == 500 and response.get_json() == ADD_ERROR
    assert events == ["add", "commit", "rollback"]
    assert [row.tweet_id for row in News.query.all()] == ["123"]


@pytest.mark.parametrize("action", ("add", "delete"))
def test_rollback_failure_propagates_out_of_original_except(client, admin, saved_news, monkeypatch, action):
    ident = saved_news.id
    events = []

    def commit():
        events.append("commit")
        raise RuntimeError("commit failure")

    def rollback():
        events.append("rollback")
        raise RuntimeError("rollback failure")

    monkeypatch.setattr(db.session, "commit", commit)
    monkeypatch.setattr(db.session, "rollback", rollback)
    with pytest.raises(RuntimeError, match="rollback failure"):
        if action == "add":
            client.post("/api/admin/news", json={"tweet_id": "123"})
        else:
            client.delete(f"/api/admin/news/{ident}")
    assert events == ["commit", "rollback"]


@pytest.mark.parametrize("action", ("add", "delete"))
def test_validation_json_failure_is_caught_and_rolled_back(client, admin, monkeypatch, action):
    events = transactions(monkeypatch)
    original = routes.jsonify

    def encode(payload):
        if payload in (MISSING, {"error": "ニュースが見つかりません。"}):
            raise RuntimeError("validation JSON failure")
        return original(payload)

    monkeypatch.setattr(routes, "jsonify", encode)
    response = (client.post("/api/admin/news", json={}) if action == "add"
                else client.delete("/api/admin/news/987654"))
    assert response.status_code == 500 and response.get_json() == (ADD_ERROR if action == "add" else DELETE_ERROR)
    assert events == ["rollback"]
