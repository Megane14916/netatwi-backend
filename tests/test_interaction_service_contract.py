"""Interaction behavior captured before the issue #44 service extraction."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Query

from app.routes import interactions as routes
from app.models import Bookmark, Notification, Post, Vote, db
from app.services import notifications


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
BOOKMARK_ERROR = {"error": "ブックマーク処理中にエラーが発生しました。"}
LIKE_ERROR = {"error": "いいね処理中にエラーが発生しました。"}


@pytest.fixture
def interaction_case(user_factory, contest_factory, login, fixed_time):
    author = user_factory("author")
    reader = user_factory("reader")
    contest = contest_factory(NOW - timedelta(hours=2), NOW - timedelta(hours=1), NOW,
                              scoring_method="judge")
    post = Post(user_id=author.id, contest_id=contest.id, content="Entry", bookmark_count=99)
    db.session.add(post)
    db.session.commit()
    login(reader)
    fixed_time(NOW)
    return post, reader, contest


def observe(monkeypatch):
    events = []
    for name in ("add", "delete", "commit", "rollback", "refresh"):
        original = getattr(db.session, name)

        def record(*args, _name=name, _original=original, **kwargs):
            events.append(f"{_name} {type(args[0]).__name__}" if _name in ("add", "delete", "refresh") else _name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(db.session, name, record)
    count = Query.count

    def record_count(query):
        entity = query.column_descriptions[0]["entity"]
        if entity in (Bookmark, Vote):
            events.append(f"count {entity.__name__}")
        return count(query)

    monkeypatch.setattr(Query, "count", record_count)
    return events


@pytest.mark.parametrize("kind", ("bookmark", "like"))
@pytest.mark.parametrize("method", ("PUT", "DELETE"))
def test_exact_anonymous_and_missing_post_responses(client, user_factory, login, monkeypatch, kind, method):
    events = observe(monkeypatch)
    response = client.open(f"/api/posts/999/{kind}", method=method)
    assert response.status_code == 401
    assert response.get_json() == {"error": "ログインが必要です。" if kind == "bookmark" else "Login required"}
    assert events == []
    login(user_factory("reader"))
    events.clear()
    response = client.open(f"/api/posts/999/{kind}", method=method)
    assert response.status_code == (404 if kind == "bookmark" else 500)
    assert response.get_json() == ({"error": "投稿が見つかりません。"} if kind == "bookmark" else LIKE_ERROR)
    assert events == ([] if kind == "bookmark" else ["rollback"])


def test_bookmark_recounts_source_rows_and_commits_twice_on_every_request(
    client, interaction_case, user_factory, monkeypatch
):
    post, reader, _ = interaction_case
    other = user_factory("other")
    db.session.add(Bookmark(user_id=other.id, post_id=post.id))
    db.session.commit()
    events = observe(monkeypatch)
    path = f"/api/posts/{post.id}/bookmark"
    for method, active, count, mutation in [
        ("PUT", True, 2, ["add Bookmark"]), ("PUT", True, 2, []),
        ("DELETE", False, 1, ["delete Bookmark"]), ("DELETE", False, 1, []),
        ("PUT", True, 2, ["add Bookmark"]),
    ]:
        events.clear()
        response = client.open(path, method=method, data="{", content_type="application/json")
        assert response.status_code == 200
        assert response.get_json() == {"message": "ブックマークを更新しました。", "isBookmarked": active,
                                       "bookmarkCount": count}
        assert events == mutation + ["commit", "count Bookmark", "commit", "refresh Post"]
        assert post.bookmark_count == count
    assert Notification.query.count() == 0


def test_bookmark_allows_own_post_before_start_without_scoring_checks(
    client, interaction_case, login, fixed_time
):
    post, _, contest = interaction_case
    contest.scoring_method = "user"
    db.session.commit()
    login(post.user)
    fixed_time(NOW - timedelta(days=1))
    assert client.put(f"/api/posts/{post.id}/bookmark").status_code == 200
    assert post.bookmark_count == 1


@pytest.mark.parametrize("method", ("PUT", "DELETE"))
@pytest.mark.parametrize("offset, scoring, expected", [
    (timedelta(microseconds=-1), "judge", "Voting is ongoing, use the bulk vote API."),
    (timedelta(), "judge", None), (timedelta(days=1), "judge", None),
    (timedelta(microseconds=-1), "user", "Voting is ongoing, use the bulk vote API."),
    (timedelta(), "user", "Cannot like during results when user voting is enabled."),
    (timedelta(), "hybrid", "Cannot like during results when user voting is enabled."),
])
def test_like_period_and_scoring_boundary(
    client, interaction_case, fixed_time, monkeypatch, method, offset, scoring, expected
):
    post, _, contest = interaction_case
    contest.scoring_method = scoring
    db.session.commit()
    fixed_time(NOW + offset)
    events = observe(monkeypatch)
    response = client.open(f"/api/posts/{post.id}/like", method=method)
    assert response.status_code == (403 if expected else 200)
    if expected:
        assert response.get_json() == {"error": expected}
        assert events == []
    else:
        assert response.get_json() == {"isLiked": method == "PUT", "likeCount": int(method == "PUT")}
        assert events == (["add Vote", "add Notification", "commit", "count Vote"] if method == "PUT"
                          else ["commit", "count Vote"])
    assert (contest.total_voters, contest.total_judges) == (0, 0)


@pytest.mark.parametrize("method", ("PUT", "DELETE"))
def test_own_post_check_precedes_period_and_scoring(
    client, interaction_case, login, fixed_time, monkeypatch, method
):
    post, _, contest = interaction_case
    contest.scoring_method = "user"
    db.session.commit()
    login(post.user)
    fixed_time(NOW - timedelta(days=1))
    events = observe(monkeypatch)
    response = client.open(f"/api/posts/{post.id}/like", method=method)
    assert response.status_code == 403
    assert response.get_json() == {"error": "Cannot like your own post."}
    assert events == []


def test_like_create_repeat_delete_recreate_notification_and_count_order(
    client, interaction_case, monkeypatch
):
    post, reader, contest = interaction_case
    events = observe(monkeypatch)
    original_notify = notifications.create_like_notification

    def notify(*args):
        assert args == (post, post.id, reader.id, contest)
        events.append("notify")
        return original_notify(*args)

    monkeypatch.setattr(notifications, "create_like_notification", notify)
    for method, active, count, expected in [
        ("PUT", True, 1, ["add Vote", "notify", "add Notification", "commit", "count Vote"]),
        ("PUT", True, 1, ["commit", "count Vote"]),
        ("DELETE", False, 0, ["delete Vote", "commit", "count Vote"]),
        ("DELETE", False, 0, ["commit", "count Vote"]),
        ("PUT", True, 1, ["add Vote", "notify", "add Notification", "commit", "count Vote"]),
    ]:
        events.clear()
        response = client.open(f"/api/posts/{post.id}/like", method=method)
        assert response.status_code == 200
        assert response.get_json() == {"isLiked": active, "likeCount": count}
        assert events == expected
    vote = Vote.query.one()
    assert (vote.user_id, vote.post_id, vote.contest_id, vote.count, vote.is_judge_vote,
            vote.is_judge_award) == (reader.id, post.id, contest.id, 1, False, False)
    assert Notification.query.count() == 2
    assert post.bookmark_count == 99
    assert (contest.total_voters, contest.total_judges) == (0, 0)


@pytest.mark.parametrize("method", ("PUT", "DELETE"))
@pytest.mark.parametrize("count, judge", [(0, False), (2, False), (0, True)])
def test_existing_votes_and_count_filters(client, interaction_case, user_factory, monkeypatch, method, count, judge):
    post, reader, contest = interaction_case
    other = user_factory("other")
    judge_user = user_factory("judge")
    vote = Vote(user_id=reader.id, post_id=post.id, contest_id=contest.id, count=count,
                is_judge_vote=judge, is_judge_award=True, judge_comment="Keep")
    db.session.add_all([vote, Vote(user_id=other.id, post_id=post.id, contest_id=contest.id, count=1),
                       Vote(user_id=judge_user.id, post_id=post.id, contest_id=contest.id,
                            count=1, is_judge_vote=True)])
    db.session.commit()
    vote_id = vote.id
    events = observe(monkeypatch)
    response = client.open(f"/api/posts/{post.id}/like", method=method)
    assert response.status_code == (400 if judge else 200)
    if judge:
        assert response.get_json() == {"error": "審査員として採点済みのため、いいねは追加できません。"}
        assert events == []
    else:
        assert response.get_json() == {"isLiked": method == "PUT", "likeCount": 1}
        assert events == (["delete Vote"] if method == "DELETE" else []) + ["commit", "count Vote"]
    if method == "PUT" or judge:
        assert (vote.count, vote.is_judge_award, vote.judge_comment) == (count, True, "Keep")
    else:
        assert db.session.get(Vote, vote_id) is None
    assert Notification.query.count() == 0


@pytest.mark.parametrize("method", ("PUT", "DELETE"))
@pytest.mark.parametrize("kind, failure_number", [("bookmark", 1), ("bookmark", 2), ("like", 1)])
def test_commit_failure_keeps_original_partial_commit_boundary(
    client, interaction_case, monkeypatch, capsys, method, kind, failure_number
):
    post, reader, contest = interaction_case
    model = Bookmark if kind == "bookmark" else Vote
    fields = {} if kind == "bookmark" else {"contest_id": contest.id, "count": 1}
    if method == "DELETE":
        db.session.add(model(user_id=reader.id, post_id=post.id, **fields))
        db.session.commit()
    events = observe(monkeypatch)
    original_commit = db.session.commit
    calls = 0

    def fail_commit():
        nonlocal calls
        calls += 1
        if calls == failure_number:
            events.append("commit failure")
            raise RuntimeError("commit failure")
        return original_commit()

    monkeypatch.setattr(db.session, "commit", fail_commit)
    response = client.open(f"/api/posts/{post.id}/{kind}", method=method)
    assert response.status_code == 500
    assert response.get_json() == (BOOKMARK_ERROR if kind == "bookmark" else LIKE_ERROR)
    mutation = [f"{'add' if method == 'PUT' else 'delete'} {model.__name__}"]
    if kind == "like" and method == "PUT":
        mutation += ["add Notification"]
    assert events == mutation + (["commit", "count Bookmark"] if failure_number == 2 else []) + [
        "commit failure", "rollback"
    ]
    assert model.query.count() == (int(method == "PUT") if failure_number == 2 else int(method == "DELETE"))
    assert post.bookmark_count == 99
    assert Notification.query.count() == 0
    output = capsys.readouterr()
    expected = (f"!!! ERROR at POST /api/posts/{post.id}/bookmark: commit failure"
                if kind == "bookmark" else "Error toggling like: commit failure")
    assert expected in output.out
    assert ("RuntimeError: commit failure" in output.err) == (kind == "bookmark")


@pytest.mark.parametrize("kind", ("bookmark", "like"))
@pytest.mark.parametrize("method", ("PUT", "DELETE"))
def test_json_conversion_failure_is_still_inside_original_try(
    client, interaction_case, monkeypatch, kind, method
):
    post, reader, contest = interaction_case
    model = Bookmark if kind == "bookmark" else Vote
    if method == "DELETE":
        fields = {} if kind == "bookmark" else {"contest_id": contest.id, "count": 1}
        db.session.add(model(user_id=reader.id, post_id=post.id, **fields))
        db.session.commit()
    events = observe(monkeypatch)
    original_jsonify = routes.jsonify

    def fail_success_json(payload):
        if "error" not in payload:
            events.append("json failure")
            raise RuntimeError("json failure")
        return original_jsonify(payload)

    monkeypatch.setattr(routes, "jsonify", fail_success_json)
    response = client.open(f"/api/posts/{post.id}/{kind}", method=method)
    assert response.status_code == 500
    assert response.get_json() == (BOOKMARK_ERROR if kind == "bookmark" else LIKE_ERROR)
    assert events[-2:] == ["json failure", "rollback"]
    assert events.count("commit") == (2 if kind == "bookmark" else 1)
    assert model.query.count() == int(method == "PUT")
    assert Notification.query.count() == int(kind == "like" and method == "PUT")


@pytest.mark.parametrize("method", ("PUT", "DELETE"))
@pytest.mark.parametrize("kind", ("bookmark", "like"))
def test_integrity_error_without_concurrent_row_keeps_original_response(
    client, interaction_case, monkeypatch, kind, method
):
    post, _, _ = interaction_case
    events = observe(monkeypatch)

    def fail_commit():
        events.append("integrity failure")
        raise IntegrityError("test", {}, RuntimeError("conflict"))

    monkeypatch.setattr(db.session, "commit", fail_commit)
    response = client.open(f"/api/posts/{post.id}/{kind}", method=method)
    expected_status = 500 if kind == "bookmark" and method == "DELETE" else 200
    assert response.status_code == expected_status
    assert response.get_json() == (BOOKMARK_ERROR if expected_status == 500 else
                                   {"message": "ブックマークを更新しました。", "isBookmarked": True,
                                    "bookmarkCount": 0} if kind == "bookmark" else
                                   {"isLiked": False, "likeCount": 0})
    assert events.count("rollback") == 1
    assert "commit" not in events and "refresh Post" not in events
    assert post.bookmark_count == 99
    assert Notification.query.count() == 0


@pytest.mark.parametrize("kind, count, judge", [("bookmark", 0, False), ("like", 1, False),
                                             ("like", 0, False), ("like", 0, True)])
def test_real_unique_constraint_race_recovers_existing_row(
    client, interaction_case, monkeypatch, kind, count, judge
):
    post, reader, contest = interaction_case
    model = Bookmark if kind == "bookmark" else Vote
    fields = {} if kind == "bookmark" else {"contest_id": contest.id, "count": count, "is_judge_vote": judge}
    existing = model(user_id=reader.id, post_id=post.id, **fields)
    db.session.add(existing)
    db.session.commit()
    original_first = Query.first
    hidden = False

    def stale_first(query):
        nonlocal hidden
        if query.column_descriptions[0]["entity"] is model and not hidden:
            hidden = True
            return None
        return original_first(query)

    monkeypatch.setattr(Query, "first", stale_first)
    events = observe(monkeypatch)
    response = client.put(f"/api/posts/{post.id}/{kind}")
    assert response.status_code == 200
    assert response.get_json() == ({"message": "ブックマークを更新しました。", "isBookmarked": True,
                                    "bookmarkCount": 1} if kind == "bookmark" else
                                   {"isLiked": not judge, "likeCount": int(count == 1 and not judge)})
    assert events == (["add Bookmark", "commit", "rollback", "count Bookmark"] if kind == "bookmark"
                      else ["add Vote", "add Notification", "commit", "rollback", "count Vote"])
    assert model.query.count() == 1
    assert post.bookmark_count == 99
    assert Notification.query.count() == 0


@pytest.mark.parametrize("kind", ("bookmark", "like"))
def test_recovery_query_failure_propagates_outside_generic_handler(
    client, interaction_case, monkeypatch, kind
):
    post, _, _ = interaction_case
    events = observe(monkeypatch)

    def fail_commit():
        raise IntegrityError("test", {}, RuntimeError("conflict"))

    def fail_count(_query):
        events.append("recovery failure")
        raise RuntimeError("recovery failure")

    monkeypatch.setattr(db.session, "commit", fail_commit)
    monkeypatch.setattr(Query, "count", fail_count)
    with pytest.raises(RuntimeError, match="recovery failure"):
        client.put(f"/api/posts/{post.id}/{kind}")
    assert events[-2:] == ["rollback", "recovery failure"]
    assert events.count("rollback") == 1


@pytest.mark.parametrize("method", ("PUT", "DELETE"))
@pytest.mark.parametrize("kind, stage", [("bookmark", "count"), ("bookmark", "refresh"), ("like", "count")])
def test_count_or_refresh_failure_preserves_already_committed_state(
    client, interaction_case, monkeypatch, kind, stage, method
):
    post, reader, contest = interaction_case
    model = Bookmark if kind == "bookmark" else Vote
    if method == "DELETE":
        fields = {} if kind == "bookmark" else {"contest_id": contest.id, "count": 1}
        db.session.add(model(user_id=reader.id, post_id=post.id, **fields))
        db.session.commit()
    events = observe(monkeypatch)

    def fail(*_args):
        events.append(f"{stage} failure")
        raise RuntimeError(f"{stage} failure")

    if stage == "count":
        monkeypatch.setattr(Query, "count", fail)
    else:
        monkeypatch.setattr(db.session, "refresh", fail)
    response = client.open(f"/api/posts/{post.id}/{kind}", method=method)
    assert response.status_code == 500
    assert response.get_json() == (BOOKMARK_ERROR if kind == "bookmark" else LIKE_ERROR)
    assert events[-2:] == [f"{stage} failure", "rollback"]
    assert events.count("commit") == (2 if stage == "refresh" else 1)
    assert len(model.query.all()) == int(method == "PUT")
    assert len(Notification.query.all()) == int(kind == "like" and method == "PUT")
    assert post.bookmark_count == (int(method == "PUT") if stage == "refresh" else 99)


def test_bookmark_integrity_recovery_missing_post_returns_original_500(
    client, interaction_case, monkeypatch
):
    post, _, _ = interaction_case
    post_id = post.id
    events = observe(monkeypatch)
    original_get = Query.get
    failed = False

    def fail_commit():
        nonlocal failed
        failed = True
        raise IntegrityError("test", {}, RuntimeError("conflict"))

    def missing_after_failure(query, key):
        if failed and query.column_descriptions[0]["entity"] is Post:
            return None
        return original_get(query, key)

    monkeypatch.setattr(db.session, "commit", fail_commit)
    monkeypatch.setattr(Query, "get", missing_after_failure)
    response = client.put(f"/api/posts/{post_id}/bookmark")
    assert response.status_code == 500
    assert response.get_json() == BOOKMARK_ERROR
    assert events == ["add Bookmark", "rollback"]
