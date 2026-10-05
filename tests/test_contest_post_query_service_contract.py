"""Contest post listing behavior captured before issue #46 extraction."""

import builtins
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Query

from app.routes import posts as routes
from app.services import contest_posts as query_module
from app.models import Comment, Post, Vote, db


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def clock(monkeypatch, read):
    original = builtins.__import__
    calls = []

    def tick():
        calls.append("time")
        return read()

    fake = SimpleNamespace(time=tick)

    def local_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "time" and globals and globals.get("__name__") == "app.routes.posts":
            return fake
        return original(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", local_import)
    return calls


def observe_reads(monkeypatch):
    events = []
    original = Query.all

    def read(query):
        events.append(query.column_descriptions[0]["entity"].__name__)
        return original(query)

    def reject(*_args, **_kwargs):
        raise AssertionError("Listing must not write or count rows")

    monkeypatch.setattr(Query, "all", read)
    monkeypatch.setattr(Query, "count", reject)
    monkeypatch.setattr(db.session, "commit", reject)
    monkeypatch.setattr(db.session, "rollback", reject)
    return events


@pytest.fixture
def entries(user_factory, contest_factory):
    author = user_factory("author")
    reader = user_factory("reader")
    other = user_factory("other")
    c = contest_factory(NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2),
                        post_count=27, is_voting_visible=False)
    foreign = contest_factory(NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2))
    old = Post(contest_id=c.id, user_id=author.id, content="古い投稿", created_at=NOW,
               comment_count=9)
    new = Post(contest_id=c.id, user_id=author.id, content="新しい投稿", created_at=NOW + timedelta(seconds=1))
    excluded = Post(contest_id=foreign.id, user_id=other.id, content="Other contest", created_at=NOW + timedelta(days=1))
    old.images = ["https://images.example/1.png", "https://images.example/2.png"]
    db.session.add_all([old, new, excluded])
    db.session.flush()
    db.session.add_all([
        Vote(user_id=reader.id, contest_id=c.id, post_id=old.id, count=0,
             is_judge_award=True, is_judge_vote=True, judge_comment="審査員コメント"),
        Vote(user_id=other.id, contest_id=c.id, post_id=new.id, count=7,
             is_judge_award=True, judge_comment="Other reader"),
        Vote(user_id=reader.id, contest_id=foreign.id, post_id=excluded.id, count=2),
        Comment(user_id=reader.id, post_id=old.id, content="My comment"),
        Comment(user_id=other.id, post_id=new.id, content="Other comment"),
        Comment(user_id=reader.id, post_id=excluded.id, content="Foreign comment"),
    ])
    db.session.commit()
    return SimpleNamespace(c=c, foreign=foreign, old=old, new=new, excluded=excluded,
                           reader=reader, other=other, author=author)


@pytest.mark.parametrize("viewer", ("anonymous", "reader", "judge", "author"))
def test_complete_payload_and_viewer_scope(client, entries, login, monkeypatch, viewer):
    e = entries
    if viewer != "anonymous":
        login(e.reader if viewer in ("reader", "judge") else e.author,
              judge_contests=[e.c.id] if viewer == "judge" else [])
    reads = observe_reads(monkeypatch)
    response = client.get(f"/api/contests/{e.c.id}/posts")
    assert response.status_code == 200
    mine = viewer in ("reader", "judge")
    assert response.get_json() == {
        "posts": [
            {"id": e.new.id, "content": "新しい投稿", "created_at": "2026-01-01T21:00:01+09:00",
             "user_id": e.author.id, "myVotes": None, "images": [], "myJudgeAward": False,
             "myJudgeComment": None, "hasCommented": False, "comment_count": 0},
            {"id": e.old.id, "content": "古い投稿", "created_at": "2026-01-01T21:00:00+09:00",
             "user_id": e.author.id, "myVotes": 0.0 if mine else None,
             "images": ["https://images.example/1.png", "https://images.example/2.png"],
             "myJudgeAward": mine, "myJudgeComment": "審査員コメント" if mine else None,
             "hasCommented": mine, "comment_count": 9}],
        "totalPosters": 27, "userHasVotedInContest": mine,
    }
    assert reads == (["Post"] if viewer == "anonymous" else ["Post", "Vote", "Comment"])


@pytest.mark.parametrize("period", ("upcoming", "ongoing", "voting", "closed"))
def test_listing_keeps_no_period_or_visibility_restriction(client, entries, period):
    c = entries.c
    shift = {"upcoming": 24, "ongoing": -0.5, "voting": -1.5, "closed": -24}[period]
    c.start_time = NOW + timedelta(hours=shift)
    c.end_time = c.start_time + timedelta(hours=1)
    c.voting_end_time = c.start_time + timedelta(hours=2)
    db.session.commit()
    response = client.get(f"/api/contests/{c.id}/posts")
    assert response.status_code == 200
    assert [p["id"] for p in response.get_json()["posts"]] == [entries.new.id, entries.old.id]


@pytest.mark.parametrize("user_id", (None, 0, "", 987654))
def test_session_truthiness_and_unknown_user_keep_query_behavior(client, entries, monkeypatch, user_id):
    with client.session_transaction() as session:
        session["user_id"] = user_id
    reads = observe_reads(monkeypatch)
    payload = client.get(f"/api/contests/{entries.c.id}/posts").get_json()
    assert payload["userHasVotedInContest"] is False
    assert reads == (["Post", "Vote", "Comment"] if user_id else ["Post"])


@pytest.mark.parametrize("signed_in", (False, True))
def test_empty_contest_still_uses_stored_counter_and_queries(client, entries, login, monkeypatch, signed_in):
    if signed_in:
        login(entries.reader)
    # The foreign contest has an entry; remove it and keep the counter distinct.
    Vote.query.filter_by(post_id=entries.excluded.id).delete()
    Comment.query.filter_by(post_id=entries.excluded.id).delete()
    db.session.delete(entries.excluded)
    entries.foreign.post_count = 14
    db.session.commit()
    reads = observe_reads(monkeypatch)
    response = client.get(f"/api/contests/{entries.foreign.id}/posts")
    assert response.status_code == 200
    assert response.get_json() == {"posts": [], "totalPosters": 14, "userHasVotedInContest": False}
    assert reads == (["Post", "Vote", "Comment"] if signed_in else ["Post"])


def test_missing_contest_keeps_500_and_skips_post_query(client, monkeypatch, capsys):
    reads = observe_reads(monkeypatch)
    response = client.get("/api/contests/987654/posts")
    assert response.status_code == 500 and response.get_json() == {"error": "Failed to fetch posts"}
    assert reads == []
    assert "!!! ERROR at GET /api/contests/987654/posts: 404 Not Found" in capsys.readouterr().out


def test_fractional_vote_and_nullable_comment_are_returned_without_judge_session(client, entries, login):
    login(entries.reader)
    Vote.query.filter_by(user_id=entries.reader.id, post_id=entries.old.id).update(
        {"count": 1.5, "is_judge_vote": False, "is_judge_award": False, "judge_comment": None}
    )
    db.session.commit()
    payload = client.get(f"/api/contests/{entries.c.id}/posts").get_json()
    assert payload["userHasVotedInContest"] is True
    assert payload["posts"][1]["myVotes"] == 1.5
    assert payload["posts"][1]["myJudgeAward"] is False
    assert payload["posts"][1]["myJudgeComment"] is None


def test_vote_for_post_outside_listing_still_sets_has_voted(client, entries, login):
    login(entries.reader)
    Vote.query.filter_by(user_id=entries.reader.id, contest_id=entries.c.id).delete()
    Vote.query.filter_by(user_id=entries.reader.id, post_id=entries.excluded.id).update({"contest_id": entries.c.id})
    db.session.commit()
    payload = client.get(f"/api/contests/{entries.c.id}/posts").get_json()
    assert payload["userHasVotedInContest"] is True
    assert all(p["myVotes"] is None and p["myJudgeAward"] is False for p in payload["posts"])


@pytest.mark.parametrize("raw, expected", [(None, []), ("invalid", []), ('{"raw": true}', {"raw": True})])
def test_images_keep_existing_model_decoding(client, entries, raw, expected):
    entries.old.image_urls = raw
    db.session.commit()
    assert client.get(f"/api/contests/{entries.c.id}/posts").get_json()["posts"][1]["images"] == expected


@pytest.mark.parametrize("signed_in", (False, True))
def test_clock_logs_and_session_read_order(client, entries, login, monkeypatch, signed_in):
    if signed_in:
        login(entries.reader)
    values = iter(range(10, 17))
    calls = clock(monkeypatch, lambda: next(values))
    logs = []
    monkeypatch.setattr(query_module, "logger", SimpleNamespace(info=logs.append))

    def read_session(key):
        assert key == "user_id"
        assert len(logs) == 2 and len(calls) == 3
        return entries.reader.id if signed_in else None

    monkeypatch.setattr(routes, "session", SimpleNamespace(get=read_session))
    observe_reads(monkeypatch)
    assert client.get(f"/api/contests/{entries.c.id}/posts").status_code == 200
    expected = ["[get_posts] get_or_404: 1.0000s", "[get_posts] posts query: 1.0000s"]
    if signed_in:
        expected += ["[get_posts] votes query: 1.0000s", "[get_posts] comments query: 1.0000s"]
    expected += ["[get_posts] total_posters query: 1.0000s", "[get_posts] loop formatting: 1.0000s",
                 f"[get_posts] TOTAL TIME: {6 if signed_in else 5}.0000s"]
    assert logs == expected and len(calls) == (7 if signed_in else 6)


@pytest.mark.parametrize("stage", ("contest", "Post", "Vote", "Comment", "log", "format", "session", "json"))
def test_failures_keep_500_print_and_no_rollback(client, entries, login, monkeypatch, capsys, stage):
    login(entries.reader)
    observe_reads(monkeypatch)

    def fail(*_args, **_kwargs):
        raise RuntimeError("listing failure")

    if stage == "contest":
        monkeypatch.setattr(Query, "get", fail)
    elif stage in ("Post", "Vote", "Comment"):
        original = Query.all

        def query_failure(query):
            if query.column_descriptions[0]["entity"].__name__ == stage:
                fail()
            return original(query)

        monkeypatch.setattr(Query, "all", query_failure)
    elif stage == "log":
        monkeypatch.setattr(query_module, "logger", SimpleNamespace(info=fail))
    elif stage == "format":
        monkeypatch.setattr(Post, "images", property(fail))
    elif stage == "session":
        monkeypatch.setattr(routes, "session", SimpleNamespace(get=fail))
    else:
        original = routes.jsonify

        def encode(payload):
            if "error" not in payload:
                fail()
            return original(payload)

        monkeypatch.setattr(routes, "jsonify", encode)
    response = client.get(f"/api/contests/{entries.c.id}/posts")
    assert response.status_code == 500 and response.get_json() == {"error": "Failed to fetch posts"}
    assert f"!!! ERROR at GET /api/contests/{entries.c.id}/posts: listing failure" in capsys.readouterr().out


@pytest.mark.parametrize("index", range(7))
def test_clock_failure_exception_boundary(client, entries, login, monkeypatch, index):
    login(entries.reader)
    position = 0

    def read():
        nonlocal position
        current = position
        position += 1
        if current == index:
            raise RuntimeError("clock failure")
        return current

    calls = clock(monkeypatch, read)
    observe_reads(monkeypatch)
    if index == 0:
        with pytest.raises(RuntimeError, match="clock failure"):
            client.get(f"/api/contests/{entries.c.id}/posts")
    else:
        response = client.get(f"/api/contests/{entries.c.id}/posts")
        assert response.status_code == 500 and response.get_json() == {"error": "Failed to fetch posts"}
    assert len(calls) == index + 1


def test_listing_is_fresh_without_cache(client, entries):
    assert client.get(f"/api/contests/{entries.c.id}/posts").get_json()["totalPosters"] == 27
    entries.c.post_count = 31
    entries.old.content = "Changed"
    db.session.commit()
    payload = client.get(f"/api/contests/{entries.c.id}/posts").get_json()
    assert payload["totalPosters"] == 31 and payload["posts"][1]["content"] == "Changed"
