"""Directory and account contracts captured before issue #49 extraction."""

import builtins
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from flask import url_for
from flask_sqlalchemy.query import Query as FlaskQuery
from sqlalchemy.orm import Query

import app as account_routes
import app as withdrawal_module
from blueprints import users as directory_routes
from models import Bookmark, Comment, ContestResult, Notification, Post, User, UserStats, Vote, db


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


@pytest.fixture
def directory(app):
    rows = []
    for i in reversed(range(205)):
        user = User(twitter_id=f"private-id-{i:03d}", screen_name=f"screen-{i:03d}", name=f"Name-{i:03d}",
                    profile_image_url="https://image.example/0.png" if i == 0 else None)
        db.session.add(user)
        db.session.add(UserStats(user=user, rank=1 if i < 105 else 2,
                                gp_1st=1, gp_2nd=2, gp_3rd=3, daily_1st=4, daily_2nd=5, daily_3rd=6, judge_awards=7))
        rows.append(user)
    deleted = User(twitter_id="deleted-id", screen_name="deleted", name="Deleted", deleted_at=NOW)
    db.session.add_all([deleted, User(twitter_id="no-stats", screen_name="no_stats", name="No stats")])
    db.session.add(UserStats(user=deleted, rank=0))
    db.session.commit()
    return list(reversed(rows))


def reject_writes(monkeypatch):
    def reject(*_args, **_kwargs):
        raise AssertionError("Unexpected commit or rollback")

    monkeypatch.setattr(db.session, "commit", reject)
    monkeypatch.setattr(db.session, "rollback", reject)


@pytest.mark.parametrize("query, page, ids", [("", 1, range(100)), ("?page=2", 2, range(100, 200)),
                                            ("?page=3", 3, range(200, 205)), ("?page=4", 4, ()),
                                            ("?page=0", 1, range(100)), ("?page=-2", 1, range(100)),
                                            ("?page=invalid", 1, range(100)), ("?page=", 1, range(100)),
                                            ("?page=2&page=1", 2, range(100, 200))])
def test_directory_join_soft_delete_rank_name_order_and_paging(client, directory, monkeypatch, query, page, ids):
    expected_ids = [directory[i].id for i in ids]
    reject_writes(monkeypatch)
    response = client.get("/api/users" + query)
    assert response.status_code == 200
    payload = response.get_json()
    assert [u["id"] for u in payload["users"]] == expected_ids
    assert {k: v for k, v in payload.items() if k != "users"} == {
        "page": page, "total_pages": 3, "total_items": 205, "has_next": page < 3, "has_prev": page > 1}
    if page == 1:
        assert payload["users"][0] == {"id": directory[0].id, "twitter_id": "private-id-000", "name": "Name-000",
                                       "screen_name": "screen-000", "profile_image_url": "https://image.example/0.png",
                                       "stats": {"gp_1st": 1, "gp_2nd": 2, "gp_3rd": 3, "daily_1st": 4,
                                                 "daily_2nd": 5, "daily_3rd": 6, "judge_awards": 7}}


@pytest.mark.parametrize("q, positions", [("Name-017", [17]), ("SCREEN-018", [18]), ("private-id-019", [19]),
                                         ("%", range(100)), ("_", range(100)), (" ", []), ("deleted", []), ("no_stats", [])])
def test_search_keeps_all_three_fields_case_insensitivity_wildcards_and_no_trim(client, directory, q, positions):
    response = client.get("/api/users", query_string={"q": q})
    assert response.status_code == 200
    assert [u["id"] for u in response.get_json()["users"]] == [directory[i].id for i in positions]


def test_empty_directory_and_search_past_last_page(client, directory):
    payload = client.get("/api/users?q=screen-00&page=2").get_json()
    assert payload == {"users": [], "page": 2, "total_pages": 1, "total_items": 10, "has_next": False, "has_prev": True}
    payload = client.get("/api/users?q=missing").get_json()
    assert payload == {"users": [], "page": 1, "total_pages": 0, "total_items": 0, "has_next": False, "has_prev": False}


def test_missing_stats_formatting_guards_are_kept_without_changing_inner_join(client, monkeypatch):
    user = SimpleNamespace(id=1, twitter_id="id", name="name", screen_name="screen", profile_image_url=None, stats=None)
    monkeypatch.setattr(FlaskQuery, "paginate", lambda *_args, **_kwargs: SimpleNamespace(
        items=[user], page=1, pages=1, total=1, has_next=False, has_prev=False))
    assert client.get("/api/users").get_json()["users"][0]["stats"] == {
        "gp_1st": 0, "gp_2nd": 0, "gp_3rd": 0, "daily_1st": 0, "daily_2nd": 0, "daily_3rd": 0, "judge_awards": 0}


def test_lazy_imports_precede_input_and_pagination(client, monkeypatch):
    events = []
    original_import = builtins.__import__
    original_paginate = FlaskQuery.paginate

    def importing(name, globals=None, locals=None, fromlist=(), level=0):
        if globals and globals.get("__name__") in ("blueprints.users", "services.users") and name in ("models", "sqlalchemy"):
            events.append(name)
        return original_import(name, globals, locals, fromlist, level)

    def get(key, default=None, **kwargs):
        events.append(key)
        assert events[:2] == ["models", "sqlalchemy"]
        assert (default, kwargs) == (("", {}) if key == "q" else (1, {"type": int}))
        return default

    def paginate(query, **kwargs):
        events.append("paginate")
        assert kwargs == {"page": 1, "per_page": 100, "error_out": False}
        return original_paginate(query, **kwargs)

    monkeypatch.setattr(builtins, "__import__", importing)
    monkeypatch.setattr(directory_routes, "request", SimpleNamespace(args=SimpleNamespace(get=get)))
    monkeypatch.setattr(FlaskQuery, "paginate", paginate)
    assert client.get("/api/users").status_code == 200
    assert events == ["models", "sqlalchemy", "q", "page", "paginate"]


@pytest.mark.parametrize("stage", ("query", "json"))
def test_directory_failures_propagate_without_rollback(client, monkeypatch, stage):
    reject_writes(monkeypatch)

    def fail(*_args, **_kwargs):
        raise RuntimeError("directory failure")

    monkeypatch.setattr(FlaskQuery, "paginate", fail) if stage == "query" else monkeypatch.setattr(directory_routes, "jsonify", fail)
    with pytest.raises(RuntimeError, match="directory failure"):
        client.get("/api/users")


@pytest.mark.parametrize("setting, name, admin", [(None, "dummy_admin1", True), (None, "dummy_admin2", True),
                                               ("", "dummy_admin1", False), (" , test_admin , ", "test_admin", True),
                                               ("Test_Admin", "test_admin", False)])
def test_me_uses_session_only_and_original_admin_settings(client, monkeypatch, setting, name, admin):
    if setting is None:
        monkeypatch.delenv("ADMIN_SCREEN_NAMES", raising=False)
    else:
        monkeypatch.setenv("ADMIN_SCREEN_NAMES", setting)
    with client.session_transaction() as session:
        session.update(user_id=987654, screen_name=name, name="Session name", profile_image_url="Session image", extra="keep")
    monkeypatch.setattr(Query, "get", lambda *_args: pytest.fail("me must not query the DB"))
    response = client.get("/api/me")
    assert response.status_code == 200 and response.get_json() == {
        "logged_in": True, "user": {"id": 987654, "screen_name": name, "name": "Session name", "profile_image_url": "Session image",
                                     "isAdmin": admin}, "judge_contests": []}
    with client.session_transaction() as session:
        assert session["extra"] == "keep"


@pytest.mark.parametrize("user_id", (None, 0, ""))
@pytest.mark.parametrize("judges", (None, [12, 3], "raw", {"raw": 1}))
def test_me_checks_key_presence_and_preserves_judge_value(client, user_id, judges):
    with client.session_transaction() as session:
        session.update(user_id=user_id, screen_name="member", judge_for_contest_ids=judges)
    assert client.get("/api/me").get_json() == {
        "logged_in": True, "user": {"id": user_id, "screen_name": "member", "name": None, "profile_image_url": None,
                                     "isAdmin": False}, "judge_contests": judges}


def test_me_missing_screen_name_still_raises(client):
    with client.session_transaction() as session:
        session["user_id"] = 123
    with pytest.raises(KeyError, match="screen_name"):
        client.get("/api/me")


@pytest.mark.parametrize("logged_in", (False, True))
def test_logout_clears_every_session_value_without_db_writes(client, monkeypatch, logged_in):
    with client.session_transaction() as session:
        session["oauth_state"] = "state"
        session["judge_for_contest_ids"] = [1]
        if logged_in:
            session.update(user_id=123, screen_name="member")
    reject_writes(monkeypatch)
    assert client.get("/api/logout").get_json() == {"message": "Logged out successfully"}
    with client.session_transaction() as session:
        assert dict(session) == {}


@pytest.mark.parametrize("ident, status", [("missing_key", 401), (None, 404), (0, 404), (987654, 404)])
def test_withdrawal_missing_user_preserves_session_and_skips_commit(client, monkeypatch, ident, status):
    with client.session_transaction() as session:
        session.update(screen_name="member", extra="keep")
        if ident != "missing_key":
            session["user_id"] = ident
    reject_writes(monkeypatch)
    response = client.delete("/api/users/me")
    assert response.status_code == status and response.get_json() == {"error": "Login required" if status == 401 else "User not found"}
    with client.session_transaction() as session:
        assert session["extra"] == "keep"


@pytest.mark.parametrize("already_deleted", (False, True))
def test_withdrawal_updates_timestamp_once_retains_related_data_then_clears_session(
    client, user_factory, contest_factory, login, fixed_time, monkeypatch, already_deleted
):
    fixed_time(NOW)
    user = user_factory("member")
    other = user_factory("other")
    contest = contest_factory(NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2), post_count=9)
    post = Post(user_id=user.id, contest_id=contest.id, content="retain", comment_count=4, bookmark_count=5)
    db.session.add(post)
    db.session.flush()
    db.session.add_all([Bookmark(user_id=user.id, post_id=post.id), Comment(user_id=user.id, post_id=post.id, content="retain"),
                       Vote(user_id=user.id, post_id=post.id, contest_id=contest.id, count=3), UserStats(user_id=user.id, rank=1),
                       ContestResult(user_id=user.id, post_id=post.id, contest_id=contest.id, rank=1, score=3),
                       Notification(user_id=user.id, sender_id=other.id, post_id=post.id, type="like")])
    if already_deleted:
        user.deleted_at = NOW - timedelta(days=1)
    db.session.commit()
    ident = user.id
    login(user, judge_contests=[contest.id])
    events = []
    original_commit = db.session.commit

    def commit():
        from flask import session
        assert session["user_id"] == ident
        assert user.deleted_at == NOW
        events.append("commit")
        return original_commit()

    monkeypatch.setattr(db.session, "commit", commit)
    monkeypatch.setattr(db.session, "rollback", lambda: pytest.fail("No withdrawal rollback"))
    response = client.delete("/api/users/me")
    assert response.status_code == 200 and response.get_json() == {"message": "退会処理が完了しました"}
    assert db.session.get(User, ident).deleted_at.replace(tzinfo=timezone.utc) == NOW
    assert events == ["commit"]
    assert all(model.query.count() == 1 for model in (Post, Bookmark, Comment, Vote, UserStats, ContestResult, Notification))
    assert contest.post_count == 9 and post.comment_count == 4 and post.bookmark_count == 5
    with client.session_transaction() as session:
        assert dict(session) == {}


@pytest.mark.parametrize("stage", ("query", "datetime", "commit", "clear", "json"))
def test_withdrawal_failures_keep_uncaught_exception_and_session_order(client, user_factory, monkeypatch, stage):
    user = user_factory("member")
    ident = user.id
    events = []

    def fail(*_args, **_kwargs):
        raise RuntimeError("withdrawal failure")

    class Snapshot(dict):
        def clear(self):
            events.append("clear")
            if stage == "clear":
                fail()
            super().clear()

    snapshot = Snapshot(user_id=ident, screen_name="member", extra="keep")
    monkeypatch.setattr(account_routes, "session", snapshot)
    original_commit = db.session.commit

    def commit():
        events.append("commit")
        assert snapshot["user_id"] == ident
        if stage == "commit":
            fail()
        return original_commit()

    monkeypatch.setattr(db.session, "commit", commit)
    monkeypatch.setattr(db.session, "rollback", lambda: pytest.fail("No automatic rollback"))
    if stage == "query":
        monkeypatch.setattr(Query, "get", fail)
    elif stage == "datetime":
        monkeypatch.setattr(withdrawal_module, "datetime", SimpleNamespace(now=fail))
    elif stage == "json":
        monkeypatch.setattr(account_routes, "jsonify", fail)
    with pytest.raises(RuntimeError, match="withdrawal failure"):
        client.delete("/api/users/me")
    assert events == ([] if stage in ("query", "datetime") else ["commit"] if stage == "commit" else ["commit", "clear"])
    assert snapshot == ({} if stage == "json" else {"user_id": ident, "screen_name": "member", "extra": "keep"})
    if stage in ("clear", "json"):
        assert user.deleted_at is not None  # Commit survives later response/session failure.


def test_top_and_legacy_handler_names_remain_registered(app):
    import app as entry
    for application in (entry.app, app):
        for endpoint, path in (("get_current_user", "/api/me"), ("logout", "/api/logout"), ("withdraw_user", "/api/users/me"), ("index", "/")):
            assert getattr(entry, endpoint) is application.view_functions[endpoint]
            with application.test_request_context():
                assert url_for(endpoint) == path
        response = application.test_client().get("/")
        assert response.status_code == 200 and response.get_data(as_text=True) == "ネタツイ大会バックエンド"
        assert response.content_type == "text/html; charset=utf-8"
