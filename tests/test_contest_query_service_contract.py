"""Contest query behavior captured before the issue #45 extraction."""

import builtins
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Query

from app import create_app
from blueprints import admin as admin_routes
from blueprints import contests as public_routes
from services import contests as query_module
from models import Contest, ContestResult, Post, db


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
EMPTY = {"ongoing": [], "voting": [], "upcoming": [], "closed": [], "latestResult": None}


def clock(monkeypatch, read):
    """Replace the handlers' local time imports without changing logging's clock."""
    original_import = builtins.__import__
    calls = []

    def get_time():
        calls.append("time")
        return read()

    fake = SimpleNamespace(time=get_time)

    def import_clock(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "time" and globals and globals.get("__name__") in ("blueprints.contests", "services.contests"):
            return fake
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_clock)
    return calls


def observe_reads(monkeypatch):
    events = []
    original_all = Query.all

    def read(query):
        events.append(query.column_descriptions[0]["entity"].__name__)
        return original_all(query)

    monkeypatch.setattr(Query, "all", read)

    def reject_write(*_args, **_kwargs):
        raise AssertionError("Contest reads must not commit or roll back")

    monkeypatch.setattr(db.session, "commit", reject_write)
    monkeypatch.setattr(db.session, "rollback", reject_write)
    monkeypatch.setattr(Query, "count", reject_write)
    return events


@pytest.fixture
def rich_contest(contest_factory):
    return contest_factory(NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2),
                           name="大会", theme="Hidden theme", has_theme=False, has_qualifier=True,
                           type="daily", scoring_method="judge", image_rule="required",
                           is_voting_visible=False, advancement_numerator=2, advancement_denominator=5,
                           judge_award_advancement=True, general_vote_weight=37, judge_max_score=17,
                           judge_password="secret", result_comment_top="Top", result_comment_bottom="Bottom",
                           post_count=11, total_voters=12, total_judges=13)


@pytest.mark.parametrize("endpoint", ("list", "details", "management"))
def test_complete_payloads_preserve_field_names_types_and_theme_visibility(
    client, rich_contest, fixed_time, user_factory, login, monkeypatch, endpoint
):
    c = rich_contest
    fixed_time(NOW)
    if endpoint == "management":
        login(user_factory("test_admin"))
    common = {"id": c.id, "name": "大会", "theme": "Hidden theme", "hasQualifier": True,
              "type": "daily", "scoringMethod": "judge", "imageRule": "required",
              "isVotingVisible": False, "advancementNumerator": 2, "advancementDenominator": 5,
              "judgeAwardAdvancement": True, "generalVoteWeight": 37, "judgeMaxScore": 17,
              "startTime": "2026-01-01T21:00:00+09:00", "endTime": "2026-01-01T22:00:00+09:00",
              "votingEndTime": "2026-01-01T23:00:00+09:00"}
    reads = observe_reads(monkeypatch)
    if endpoint == "list":
        expected = dict(EMPTY, ongoing=[dict(common, hasTheme=False, parentContestId=None,
                                             totalPosters=11, totalVoters=12, totalJudges=13)])
        response = client.get("/api/contests")
    elif endpoint == "details":
        expected = dict(common, hasTheme=False, parentContestId=None, isAdvancedToFinal=None,
                        resultCommentTop="Top", resultCommentBottom="Bottom", postCount=11,
                        totalVoters=12, totalJudges=13)
        response = client.get(f"/api/contests/{c.id}")
    else:
        expected = [dict(common, theme=None, judgePassword="secret", resultCommentTop="Top",
                         resultCommentBottom="Bottom")]
        response = client.get("/api/admin/contests/management")
    assert response.status_code == 200
    assert response.get_json() == expected
    assert reads == ([] if endpoint == "details" else ["Contest"])


@pytest.mark.parametrize("offset, category, managed", [
    (timedelta(microseconds=-1), "upcoming", True), (timedelta(), "ongoing", True),
    (timedelta(hours=1, microseconds=-1), "ongoing", True),
    (timedelta(hours=1), "voting", True),
    (timedelta(hours=2, microseconds=-1), "voting", True),
    (timedelta(hours=2), "closed", True), (timedelta(hours=2, microseconds=1), "closed", False),
])
def test_public_period_boundaries_and_management_inclusive_voting_end(
    client, rich_contest, user_factory, login, fixed_time, offset, category, managed
):
    fixed_time(NOW + offset)
    login(user_factory("test_admin"))
    payload = client.get("/api/contests").get_json()
    for key in ("ongoing", "voting", "upcoming", "closed"):
        assert [c["id"] for c in payload[key]] == ([rich_contest.id] if key == category else [])
    assert (payload["latestResult"] is not None) == (category == "closed")
    assert [c["id"] for c in client.get("/api/admin/contests/management").get_json()] == (
        [rich_contest.id] if managed else []
    )


def test_ordering_and_latest_result_use_start_time_instead_of_voting_end(
    client, contest_factory, fixed_time, user_factory, login
):
    fixed_time(NOW)
    def make(start, end, voting_end, **fields):
        return contest_factory(NOW + timedelta(hours=start), NOW + timedelta(hours=end),
                               NOW + timedelta(hours=voting_end), **fields)
    upcoming_late = make(4, 5, 6)
    upcoming_early = make(2, 3, 4)
    ongoing_old = make(-2, 2, 3)
    ongoing_new = make(-1, 2, 3)
    voting_old = make(-5, -2, 1)
    voting_new = make(-4, -1, 1)
    closed_old = make(-9, -8, -0.5)
    closed_new = make(-7, -6, -3, theme="latest", post_count=8, total_voters=9, total_judges=10)
    payload = client.get("/api/contests").get_json()
    assert [c["id"] for c in payload["upcoming"]] == [upcoming_early.id, upcoming_late.id]
    assert [c["id"] for c in payload["ongoing"]] == [ongoing_new.id, ongoing_old.id]
    assert [c["id"] for c in payload["voting"]] == [voting_new.id, voting_old.id]
    assert [c["id"] for c in payload["closed"]] == [closed_new.id, closed_old.id]
    assert payload["latestResult"] == {"contest_id": closed_new.id, "contest_name": closed_new.name,
                                       "theme": "latest", "totalPosters": 8, "totalVoters": 9, "totalJudges": 10}
    login(user_factory("test_admin"))
    assert [c["id"] for c in client.get("/api/admin/contests/management").get_json()] == [
        upcoming_late.id, upcoming_early.id, ongoing_new.id, ongoing_old.id, voting_new.id, voting_old.id,
    ]


@pytest.mark.parametrize("missing, category", [("start_time", "voting"), ("end_time", "closed"),
                                             ("voting_end_time", "ongoing")])
def test_listing_keeps_existing_nullable_time_guards(client, rich_contest, fixed_time, monkeypatch, missing, category):
    values = {col.name: getattr(rich_contest, col.name) for col in Contest.__table__.columns}
    values.update(start_time=NOW - timedelta(hours=2), end_time=NOW - timedelta(hours=1),
                  voting_end_time=NOW + timedelta(hours=1))
    if missing == "end_time":
        values["voting_end_time"] = NOW - timedelta(hours=1)
    elif missing == "voting_end_time":
        values["end_time"] = NOW + timedelta(hours=1)
    values[missing] = None
    monkeypatch.setattr(Query, "all", lambda _query: [SimpleNamespace(**values)])
    fixed_time(NOW)
    payload = client.get("/api/contests").get_json()
    item = payload[category][0]
    assert item[{"start_time": "startTime", "end_time": "endTime", "voting_end_time": "votingEndTime"}[missing]] is None


@pytest.mark.parametrize("case, expected", [("anonymous", None), ("no_parent", None), ("missing", False),
                                          ("not_advanced", False), ("advanced", True)])
def test_detail_qualifier_information_is_scoped_to_session_user_and_parent(
    client, user_factory, contest_factory, login, fixed_time, case, expected
):
    fixed_time(NOW)
    user = user_factory("reader")
    other = user_factory("other")
    qualifier = contest_factory(NOW - timedelta(days=2), NOW - timedelta(days=1), NOW)
    final = contest_factory(NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2),
                            parent_contest_id=None if case == "no_parent" else qualifier.id, has_qualifier=False)
    post = Post(user_id=user.id, contest_id=qualifier.id, content="Entry")
    db.session.add(post)
    db.session.flush()
    db.session.add(ContestResult(user_id=other.id, contest_id=qualifier.id, post_id=post.id, rank=1, is_advanced=True))
    if case in ("advanced", "not_advanced"):
        db.session.add(ContestResult(user_id=user.id, contest_id=qualifier.id, post_id=post.id,
                                    rank=2, is_advanced=case == "advanced"))
    db.session.commit()
    if case != "anonymous":
        login(user)
    response = client.get(f"/api/contests/{final.id}")
    assert response.status_code == 200
    assert response.get_json()["isAdvancedToFinal"] is expected


@pytest.mark.parametrize("elapsed, hit", [(-1, True), (4.999, True), (5, False), (6, False)])
def test_cache_ttl_boundary_and_clock_read_count(client, fixed_time, monkeypatch, elapsed, hit):
    fixed_time(NOW)
    cached = dict(EMPTY, latestResult={"cached": True})
    query_module._contests_cache = cached
    query_module._contests_cache_time = 100
    times = clock(monkeypatch, lambda: 100 + elapsed)
    reads = observe_reads(monkeypatch)
    response = client.get("/api/contests")
    assert response.get_json() == (cached if hit else EMPTY)
    assert reads == ([] if hit else ["Contest"])
    assert len(times) == (1 if hit else 2)
    assert query_module._contests_cache_time == (100 if hit else 100 + elapsed)


def test_empty_database_payload_is_cached_and_shared_across_factory_apps(client, monkeypatch):
    assert query_module._contests_cache is None
    assert query_module._contests_cache_time == 0
    times = clock(monkeypatch, lambda: 100)
    reads = observe_reads(monkeypatch)
    assert client.get("/api/contests").get_json() == EMPTY
    assert query_module._contests_cache == EMPTY
    first_cache = query_module._contests_cache
    second = create_app({"TESTING": True, "SECRET_KEY": "another-app", "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    assert second.test_client().get("/api/contests").get_json() == EMPTY
    assert query_module._contests_cache is first_cache
    assert reads == ["Contest"]
    assert len(times) == 2


@pytest.mark.parametrize("cached", ({}, None))
def test_falsy_cache_does_not_read_ttl_clock(client, monkeypatch, cached):
    query_module._contests_cache = cached
    query_module._contests_cache_time = 100
    times = clock(monkeypatch, lambda: 101)
    reads = observe_reads(monkeypatch)
    assert client.get("/api/contests").get_json() == EMPTY
    assert reads == ["Contest"] and len(times) == 1


def test_cache_hit_clock_failure_is_outside_exception_handler(client, monkeypatch):
    query_module._contests_cache = dict(EMPTY)

    def fail():
        raise RuntimeError("clock failure")

    clock(monkeypatch, fail)
    with pytest.raises(RuntimeError, match="clock failure"):
        client.get("/api/contests")


def test_cache_store_clock_failure_keeps_new_payload_and_old_timestamp(client, monkeypatch):
    query_module._contests_cache_time = 123

    def fail():
        raise RuntimeError("store clock failure")

    clock(monkeypatch, fail)
    response = client.get("/api/contests")
    assert response.status_code == 500 and response.get_json() == {"error": "Failed"}
    assert query_module._contests_cache == EMPTY
    assert query_module._contests_cache_time == 123


def test_list_json_failure_is_caught_on_miss_and_propagates_on_hit(client, monkeypatch):
    clock(monkeypatch, lambda: 100)
    original_jsonify = public_routes.jsonify

    def fail_success(payload):
        if "error" not in payload:
            raise RuntimeError("JSON failure")
        return original_jsonify(payload)

    monkeypatch.setattr(public_routes, "jsonify", fail_success)
    response = client.get("/api/contests")
    assert response.status_code == 500 and response.get_json() == {"error": "Failed"}
    assert query_module._contests_cache == EMPTY
    assert query_module._contests_cache_time == 100
    with pytest.raises(RuntimeError, match="JSON failure"):
        client.get("/api/contests")


def test_stale_cache_survives_query_failure(client, monkeypatch):
    stale = dict(EMPTY, latestResult={"old": True})
    query_module._contests_cache, query_module._contests_cache_time = stale, 100
    clock(monkeypatch, lambda: 106)

    def fail(_query):
        raise RuntimeError("query failure")

    monkeypatch.setattr(Query, "all", fail)
    response = client.get("/api/contests")
    assert response.status_code == 500 and response.get_json() == {"error": "Failed"}
    assert query_module._contests_cache is stale and query_module._contests_cache_time == 100


def test_detail_clock_reads_and_log_messages_keep_original_order(client, rich_contest, monkeypatch):
    values = iter((10, 10.25, 11))
    times = clock(monkeypatch, lambda: next(values))
    logs = []
    monkeypatch.setattr(query_module, "logger", SimpleNamespace(info=logs.append))
    assert client.get(f"/api/contests/{rich_contest.id}").status_code == 200
    assert times == ["time"] * 3
    assert logs == ["[get_contest_details] get_or_404: 0.2500s", "[get_contest_details] TOTAL TIME: 1.0000s"]


@pytest.mark.parametrize("endpoint", ("details", "management"))
def test_query_failure_keeps_error_response_logs_and_no_rollback(
    client, rich_contest, user_factory, login, monkeypatch, capsys, endpoint
):
    login(user_factory("test_admin"))
    observe_reads(monkeypatch)

    def fail(*_args):
        raise RuntimeError("query failure")

    if endpoint == "details":
        monkeypatch.setattr(Query, "get", fail)
        path, status, error = f"/api/contests/{rich_contest.id}", 404, "Contest not found"
    else:
        monkeypatch.setattr(Query, "all", fail)
        path, status, error = "/api/admin/contests/management", 500, "Failed to fetch contests for management"
    response = client.get(path)
    assert response.status_code == status and response.get_json() == {"error": error}
    output = capsys.readouterr()
    assert "query failure" in output.out
    assert ("RuntimeError: query failure" in output.err) == (endpoint == "management")


@pytest.mark.parametrize("endpoint", ("details", "management"))
def test_json_failure_keeps_original_exception_boundary(
    client, rich_contest, user_factory, login, monkeypatch, endpoint
):
    login(user_factory("test_admin"))
    module = public_routes if endpoint == "details" else admin_routes
    original_jsonify = module.jsonify

    def fail_success(payload):
        if not isinstance(payload, dict) or "error" not in payload:
            raise RuntimeError("JSON failure")
        return original_jsonify(payload)

    monkeypatch.setattr(module, "jsonify", fail_success)
    path = f"/api/contests/{rich_contest.id}" if endpoint == "details" else "/api/admin/contests/management"
    response = client.get(path)
    assert response.status_code == (404 if endpoint == "details" else 500)


@pytest.mark.parametrize("authorized", (False, True))
def test_management_auth_and_trimmed_admin_names_precede_query(client, user_factory, login, monkeypatch, authorized):
    login(user_factory("test_admin" if authorized else "reader"))
    monkeypatch.setenv("ADMIN_SCREEN_NAMES", " , test_admin , ")
    reads = observe_reads(monkeypatch)
    response = client.get("/api/admin/contests/management")
    assert response.status_code == (200 if authorized else 403)
    assert reads == (["Contest"] if authorized else [])


def test_details_and_management_remain_fresh_while_public_list_keeps_cache(
    client, rich_contest, user_factory, login, fixed_time, monkeypatch
):
    login(user_factory("test_admin"))
    fixed_time(NOW)
    clock(monkeypatch, lambda: 100)
    original = client.get("/api/contests").get_json()
    rich_contest.name = "Changed"
    db.session.commit()
    assert client.get("/api/contests").get_json() == original
    assert client.get(f"/api/contests/{rich_contest.id}").get_json()["name"] == "Changed"
    assert client.get("/api/admin/contests/management").get_json()[0]["name"] == "Changed"
