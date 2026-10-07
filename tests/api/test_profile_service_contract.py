"""Profile behavior captured on the original issue #47 route."""

import builtins
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from unittest.mock import Mock
from sqlalchemy.orm import Query

from app.routes import profile as routes
from app.services import profile as query_module
from app.services import results as results_service
from app.extensions import db
from app.models import Bookmark, ContestResult, Post, Vote


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def clock(monkeypatch, read):
    original = builtins.__import__
    calls = []

    def tick():
        calls.append("time")
        return read()

    fake = SimpleNamespace(time=tick)

    def local_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "time" and globals and globals.get("__name__") == "app.routes.profile":
            return fake
        return original(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", local_import)
    return calls


def observe_reads(monkeypatch, *, allow_rollback=False):
    events = []
    original_all, original_first = Query.all, Query.first

    def read(query):
        events.append(tuple(d["name"] for d in query.column_descriptions))
        return original_all(query)

    def first(query):
        events.append(tuple(d["name"] for d in query.column_descriptions))
        return original_first(query)

    def reject(*_args, **_kwargs):
        raise AssertionError("Profile reads must not write or count rows")

    monkeypatch.setattr(Query, "all", read)
    monkeypatch.setattr(Query, "first", first)
    monkeypatch.setattr(Query, "count", reject)
    monkeypatch.setattr(db.session, "commit", reject)
    monkeypatch.setattr(db.session, "rollback", Mock(wraps=db.session.rollback) if allow_rollback else reject)
    return events


@pytest.fixture
def profile_data(user_factory, contest_factory, fixed_time):
    fixed_time(NOW)
    target = user_factory("target")
    reader = user_factory("reader")
    judge = user_factory("judge")
    other = user_factory("other")
    target.name = "投稿者"
    target.profile_image_url = "https://image.example/target.png"
    judge.name = "審査員"
    other.deleted_at = NOW  # Related authors/voters are still displayed.
    closed = contest_factory(NOW - timedelta(days=3), NOW - timedelta(days=2), NOW,
                             name="大会A", theme="テーマ", has_theme=False, scoring_method="both")
    second = contest_factory(NOW - timedelta(days=5), NOW - timedelta(days=4), NOW - timedelta(days=3),
                             name="大会B", scoring_method="user")
    hidden_contest = contest_factory(NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2))
    old = Post(user_id=target.id, contest_id=closed.id, content="古い投稿", created_at=NOW - timedelta(days=3),
               bookmark_count=12, comment_count=13)
    old.images = ["https://image.example/post.png"]
    new = Post(user_id=target.id, contest_id=closed.id, content="新しい投稿", created_at=NOW - timedelta(days=2))
    other_post = Post(user_id=other.id, contest_id=second.id, content="Other post", created_at=NOW - timedelta(days=4))
    hidden = Post(user_id=target.id, contest_id=hidden_contest.id, content="Hidden", created_at=NOW - timedelta(days=1))
    db.session.add_all([old, new, other_post, hidden])
    db.session.flush()
    db.session.add_all([
        Bookmark(user_id=target.id, post_id=old.id, created_at=NOW),
        Bookmark(user_id=target.id, post_id=new.id, created_at=NOW - timedelta(minutes=1)),
        Bookmark(user_id=target.id, post_id=other_post.id, created_at=NOW + timedelta(minutes=1)),
        Bookmark(user_id=target.id, post_id=hidden.id, created_at=NOW + timedelta(minutes=2)),
        Bookmark(user_id=reader.id, post_id=old.id),
        Vote(user_id=target.id, post_id=old.id, contest_id=closed.id, count=1.5,
             is_judge_award=True, created_at=NOW + timedelta(minutes=1)),
        Vote(user_id=reader.id, post_id=old.id, contest_id=closed.id, count=0),
        Vote(user_id=judge.id, post_id=old.id, contest_id=closed.id, count=9,
             is_judge_vote=True, is_judge_award=True),
        Vote(user_id=other.id, post_id=old.id, contest_id=closed.id, count=-2),
        Vote(user_id=target.id, post_id=new.id, contest_id=closed.id, count=0,
             is_judge_vote=True, created_at=NOW + timedelta(minutes=2)),
        Vote(user_id=target.id, post_id=other_post.id, contest_id=second.id, count=2,
             created_at=NOW + timedelta(minutes=3)),
        Vote(user_id=target.id, post_id=hidden.id, contest_id=hidden_contest.id, count=1,
             created_at=NOW + timedelta(minutes=4)),
        ContestResult(contest_id=closed.id, post_id=old.id, user_id=target.id,
                      rank=7, score=12.34, is_judge_award=False),
        ContestResult(contest_id=second.id, post_id=other_post.id, user_id=other.id, rank=2, score=8.5),
    ])
    db.session.commit()
    return SimpleNamespace(target=target, reader=reader, judge=judge, other=other,
                           closed=closed, second=second, hidden_contest=hidden_contest,
                           old=old, new=new, other_post=other_post, hidden=hidden)


@pytest.mark.parametrize("viewer", ("anonymous", "target", "reader", "judge", "other"))
def test_complete_payload_lists_viewer_information_and_live_awards(client, profile_data, login, monkeypatch, viewer):
    e = profile_data
    if viewer != "anonymous":
        login(getattr(e, viewer), judge_contests=[e.closed.id] if viewer == "judge" else [])
    reads = observe_reads(monkeypatch)
    result_calls = []
    original = results_service.get_cached_contest_results

    def results(cid):
        result_calls.append(cid)
        return original(cid)

    monkeypatch.setattr(results_service, "get_cached_contest_results", results)
    response = client.get("/api/profile/target")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["user"] == {"id": e.target.id, "screen_name": "target", "name": "投稿者",
                               "profile_image_url": "https://image.example/target.png"}
    assert [p["post_id"] for p in payload["posts"]] == [e.new.id, e.old.id]
    assert [p["post_id"] for p in payload["bookmarks"]] == [e.other_post.id, e.old.id, e.new.id]
    assert [p["post_id"] for p in payload["likes"]] == [e.other_post.id, e.old.id]
    expected_old = {
        "post_id": e.old.id, "content": "古い投稿", "images": ["https://image.example/post.png"],
        "created_at": "2025-12-29T21:00:00+09:00",
        "contest": {"id": e.closed.id, "name": "大会A", "theme": "テーマ", "scoringMethod": "both"},
        "user": {"screen_name": "target", "name": "投稿者", "profile_image_url": "https://image.example/target.png"},
        "rank": 7, "score": 12.34, "bookmarkCount": 12, "commentCount": 13,
        "isBookmarked": viewer in ("target", "reader"),
        "voters": [
            {"screen_name": "judge", "name": "審査員", "count": 9.0, "is_judge": True},
            {"screen_name": "target", "name": "投稿者", "count": 1.5, "is_judge": False},
            {"screen_name": "reader", "name": "reader", "count": 0.0, "is_judge": False},
            {"screen_name": "other", "name": "other", "count": -2.0, "is_judge": False},
        ],
        "awards": ["投稿者賞", "審査員賞"],
        "myVotes": {"anonymous": None, "target": 1.5, "reader": 0.0, "judge": 9.0, "other": None}[viewer],
    }
    assert payload["posts"][1] == expected_old
    assert payload["bookmarks"][1] == expected_old and payload["likes"][1] == expected_old
    assert payload["posts"][0]["rank"] is None and payload["posts"][0]["score"] == 0
    assert payload["bookmarks"][0]["rank"] == 2 and payload["bookmarks"][0]["score"] == 8.5
    assert payload["bookmarks"][0]["user"]["screen_name"] == "other"
    assert result_calls == [e.closed.id, e.second.id]  # Shared across all three lists.
    expected_reads = [("User",), ("Post",), ("Post",), ("Post",),
                      ("post_id", "count", "is_judge_vote", "user_id", "screen_name", "name"),
                      ("post_id", "name")]
    if viewer not in ("anonymous", "other"):
        expected_reads.append(("post_id",))
    assert reads == expected_reads + [("ContestResult",), ("ContestResult",)]


@pytest.mark.parametrize("offset, visible", [(-1, False), (0, True), (1, True)])
def test_voting_end_boundary_filters_all_three_lists(client, profile_data, fixed_time, offset, visible):
    fixed_time(NOW + timedelta(microseconds=offset))
    payload = client.get("/api/profile/target").get_json()
    assert [p["post_id"] for p in payload["posts"]] == ([profile_data.new.id, profile_data.old.id] if visible else [])
    assert [p["post_id"] for p in payload["bookmarks"]] == (
        [profile_data.other_post.id, profile_data.old.id, profile_data.new.id] if visible else [profile_data.other_post.id])
    assert [p["post_id"] for p in payload["likes"]] == (
        [profile_data.other_post.id, profile_data.old.id] if visible else [profile_data.other_post.id])


@pytest.mark.parametrize("count, judge", [(0, False), (-1, False), (3, True)])
def test_likes_exclude_nonpositive_and_judge_votes(client, profile_data, count, judge):
    Vote.query.filter_by(user_id=profile_data.target.id, post_id=profile_data.old.id).update(
        {"count": count, "is_judge_vote": judge})
    db.session.commit()
    payload = client.get("/api/profile/target").get_json()
    assert [p["post_id"] for p in payload["likes"]] == [profile_data.other_post.id]
    assert len(payload["posts"]) == 2 and len(payload["bookmarks"]) == 3


@pytest.mark.parametrize("viewer_id", (None, 0, "", 987654))
def test_session_truthiness_and_unknown_viewer(client, profile_data, monkeypatch, viewer_id):
    with client.session_transaction() as session:
        session["user_id"] = viewer_id
    reads = observe_reads(monkeypatch)
    response = client.get("/api/profile/target")
    assert response.status_code == 200
    assert all(p["myVotes"] is None and p["isBookmarked"] is False for p in response.get_json()["posts"])
    assert ("post_id",) not in reads


@pytest.mark.parametrize("case", ("missing", "deleted", "case_sensitive"))
def test_missing_or_deleted_target_stops_before_post_queries(client, profile_data, monkeypatch, case):
    if case == "deleted":
        profile_data.target.deleted_at = NOW
        db.session.commit()
    reads = observe_reads(monkeypatch)
    result_calls = []
    monkeypatch.setattr(results_service, "get_cached_contest_results", result_calls.append)
    path = "target" if case == "deleted" else "TARGET" if case == "case_sensitive" else "missing"
    response = client.get(f"/api/profile/{path}")
    assert response.status_code == 404 and response.get_json() == {"error": "Not found"}
    assert reads == [("User",)] and result_calls == []


@pytest.mark.parametrize("hidden_entries", (False, True))
def test_empty_visible_lists_skip_bulk_queries_and_results(client, profile_data, monkeypatch, hidden_entries):
    if hidden_entries:
        profile_data.closed.voting_end_time = NOW + timedelta(days=1)
        profile_data.second.voting_end_time = NOW + timedelta(days=1)
        db.session.commit()
        name, user = "target", profile_data.target
    else:
        name, user = "judge", profile_data.judge
    reads = observe_reads(monkeypatch)
    result_calls = []
    monkeypatch.setattr(results_service, "get_cached_contest_results", result_calls.append)
    response = client.get(f"/api/profile/{name}")
    assert response.status_code == 200
    assert response.get_json() == {"user": {"id": user.id, "screen_name": name, "name": user.name,
                                          "profile_image_url": user.profile_image_url},
                                   "posts": [], "bookmarks": [], "likes": []}
    assert reads == [("User",), ("Post",), ("Post",), ("Post",)] and result_calls == []


def test_results_cache_is_per_request_and_uses_saved_results(client, profile_data, monkeypatch):
    calls = []
    original = results_service.get_cached_contest_results

    def results(cid):
        calls.append(cid)
        return original(cid)

    monkeypatch.setattr(results_service, "get_cached_contest_results", results)
    assert client.get("/api/profile/target").get_json()["posts"][1]["score"] == 12.34
    ContestResult.query.filter_by(post_id=profile_data.old.id).update({"rank": 4, "score": 99})
    db.session.commit()
    payload = client.get("/api/profile/target").get_json()
    assert payload["posts"][1]["score"] == 99 and payload["posts"][1]["rank"] == 4
    assert calls == [profile_data.closed.id, profile_data.second.id] * 2


def test_clock_logs_and_session_read_before_target_query(client, profile_data, monkeypatch, capsys, caplog):
    caplog.set_level("INFO", logger="app")
    values = iter(range(10, 20))
    calls = clock(monkeypatch, lambda: next(values))
    reads = observe_reads(monkeypatch)

    def session_input(key):
        assert key == "user_id" and len(calls) == 1 and reads == []
        return profile_data.reader.id

    monkeypatch.setattr(routes, "session", SimpleNamespace(get=session_input))
    assert client.get("/api/profile/target").status_code == 200
    steps = ["target_user query", "query user_posts_raw", "query bookmarks_raw", "query liked_posts_raw",
             "filter and collect all post_ids", "bulk fetch votes_data", "bulk fetch awards_data",
             "bulk fetch viewer_bms", "format_posts_fast all lists"]
    assert capsys.readouterr().out == ""
    assert caplog.messages == [
        f"PROFILE_PERF_LOG: [{step}] took 1.0000s (Total: {i}.0000s)" for i, step in enumerate(steps, 1)]
    assert len(calls) == 10


@pytest.mark.parametrize("index", range(10))
def test_each_clock_failure_is_inside_original_exception_handler(client, profile_data, login, monkeypatch, capsys, caplog, index):
    login(profile_data.reader)
    position = 0

    def read():
        nonlocal position
        current = position
        position += 1
        if current == index:
            raise RuntimeError("clock failure")
        return current

    calls = clock(monkeypatch, read)
    observe_reads(monkeypatch, allow_rollback=True)
    response = client.get("/api/profile/target")
    assert response.status_code == 500 and response.get_json() == {"error": "Error"}
    output = capsys.readouterr()
    assert "RuntimeError" in caplog.text
    assert "clock failure" not in caplog.text + output.out + output.err
    assert db.session.rollback.call_count == 1
    assert len(calls) == index + 1


@pytest.mark.parametrize("stage", ("target", "raw_posts", "bookmarks", "likes", "votes", "awards", "viewer_bookmarks",
                                 "results", "datetime", "filter", "format", "session", "json", "not_found_json", "perf_print"))
def test_failures_keep_print_traceback_500_and_no_rollback(client, profile_data, login, monkeypatch, capsys, caplog, stage):
    login(profile_data.reader)
    observe_reads(monkeypatch, allow_rollback=True)

    def fail(*_args, **_kwargs):
        raise RuntimeError("profile failure")

    if stage == "target":
        monkeypatch.setattr(Query, "first", fail)
    elif stage in ("raw_posts", "bookmarks", "likes", "votes", "awards", "viewer_bookmarks"):
        original = Query.all
        fail_index = {"raw_posts": 0, "bookmarks": 1, "likes": 2, "votes": 3, "awards": 4, "viewer_bookmarks": 5}[stage]
        position = 0

        def read(query):
            nonlocal position
            current = position
            position += 1
            if current == fail_index:
                fail()
            return original(query)

        monkeypatch.setattr(Query, "all", read)
    elif stage == "results":
        monkeypatch.setattr(results_service, "get_cached_contest_results", fail)
    elif stage == "datetime":
        monkeypatch.setattr(query_module, "datetime", SimpleNamespace(now=fail))
    elif stage == "filter":
        # Keep the DB NOT NULL constraint intact; simulate a broken relation at the read boundary.
        original = Query.all

        def read(query):
            if query.column_descriptions[0]["name"] == "Post":
                return [SimpleNamespace(contest=SimpleNamespace(voting_end_time=SimpleNamespace(replace=fail)))]
            return original(query)

        monkeypatch.setattr(Query, "all", read)
    elif stage == "format":
        monkeypatch.setattr(Post, "images", property(fail))
    elif stage == "session":
        monkeypatch.setattr(routes, "session", SimpleNamespace(get=fail))
    elif stage in ("json", "not_found_json"):
        original = routes.jsonify

        def encode(payload):
            if payload.get("error") != "Error":
                fail()
            return original(payload)

        monkeypatch.setattr(routes, "jsonify", encode)
    elif stage == "perf_print":
        original = current_app.logger.info

        def print_log(*args, **kwargs):
            if args and str(args[0]).startswith("PROFILE_PERF_LOG:"):
                fail()
            return original(*args, **kwargs)

        monkeypatch.setattr(current_app.logger, "info", print_log)
    response = client.get("/api/profile/missing" if stage == "not_found_json" else "/api/profile/target")
    assert response.status_code == 500 and response.get_json() == {"error": "Error"}
    output = capsys.readouterr()
    assert "profile.get_user_profile" in caplog.text and "RuntimeError" in caplog.text
    assert "profile failure" not in caplog.text + output.out + output.err
    assert db.session.rollback.call_count == 1
