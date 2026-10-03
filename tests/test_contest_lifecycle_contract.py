"""Characterize admin writes, task scheduling and deletion before extraction."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from sqlalchemy import event
from google.cloud import tasks_v2

import app as app_module
from models import Bookmark, Comment, Contest, ContestResult, Notification, Post, Vote, db


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
scheduler_module = app_module
PAYLOAD = {"name": "Contest", "startTime": "2026-01-01T12:00:00Z",
           "endTime": "2026-01-01T13:00:00Z", "votingEndTime": "2026-01-01T14:00:00Z"}


@pytest.fixture
def admin(user_factory, login, fixed_time):
    user = user_factory("test_admin")
    login(user)
    fixed_time(NOW)
    return user


def observe_admin_effects(monkeypatch, *, fail_commit=False, fail_schedule=False):
    effects = []
    original_commit, original_rollback = db.session.commit, db.session.rollback

    def commit():
        effects.append("commit")
        if fail_commit:
            raise RuntimeError("commit failed")
        original_commit()

    def rollback():
        effects.append("rollback")
        original_rollback()

    def schedule(contest_id, event_type, moment):
        # A committed row is visible when scheduling starts.
        assert db.session.get(Contest, contest_id) is not None
        effects.append((contest_id, event_type, moment.replace(tzinfo=timezone.utc)))
        if fail_schedule:
            raise RuntimeError("schedule failed")

    monkeypatch.setattr(db.session, "commit", commit)
    monkeypatch.setattr(db.session, "rollback", rollback)
    monkeypatch.setattr(app_module, "schedule_contest_task", schedule)
    return effects


@pytest.mark.parametrize("qualifier", [False, True])
def test_create_fields_parent_link_and_schedule_order(client, admin, monkeypatch, qualifier):
    payload = dict(PAYLOAD, hasQualifier=qualifier, hasTheme=False, theme="Ignored", type="daily",
                   scoringMethod="judge", imageRule="required", generalVoteWeight="70",
                   judgeMaxScore="20", judgePassword="secret", isVotingVisible=False,
                   advancementNumerator="1", advancementDenominator="3", judgeAwardAdvancement=True,
                   qualifierHasTheme=True, qualifierTheme="Qualifier theme",
                   qualifierScoringMethod="user", qualifierImageRule="forbidden",
                   qualifierGeneralVoteWeight="60", qualifierJudgeMaxScore="15",
                   qualifierJudgePassword="q-secret", qualifierIsVotingVisible=False,
                   qualifierJudgeAwardAdvancement=True)
    effects = observe_admin_effects(monkeypatch)
    response = client.post("/api/admin/contests", json=payload)
    assert response.status_code == 201
    data = response.get_json()
    contest = db.session.get(Contest, data["id"])
    assert (contest.name, contest.theme, contest.has_theme, contest.type, contest.scoring_method,
            contest.image_rule, contest.general_vote_weight, contest.judge_max_score,
            contest.judge_password, contest.is_voting_visible, contest.judge_award_advancement,
            contest.status) == (
                "Contest 決勝" if qualifier else "Contest", None, False, "daily", "judge",
                "required", 70, 20, "secret", False, True, "upcoming")
    expected_ids = [contest.id]
    if qualifier:
        q = db.session.get(Contest, data["qualifier_id"])
        assert data == {"message": "Contests created successfully", "id": contest.id, "qualifier_id": q.id}
        assert contest.parent_contest_id == q.id
        assert (q.name, q.theme, q.has_theme, q.has_qualifier, q.scoring_method, q.image_rule,
                q.general_vote_weight, q.judge_max_score, q.judge_password, q.is_voting_visible,
                q.advancement_numerator, q.advancement_denominator, q.judge_award_advancement) == (
                    "Contest 予選", "Qualifier theme", True, False, "user", "forbidden",
                    60, 15, "q-secret", False, 1, 3, True)
        assert contest.advancement_numerator is contest.advancement_denominator is None
        expected_ids = [q.id, contest.id]
    else:
        assert data == {"message": "Contest created successfully", "id": contest.id}
        assert contest.parent_contest_id is None
        assert contest.advancement_numerator is contest.advancement_denominator is None
    assert effects == ["commit"] + [
        (cid, kind, NOW + timedelta(hours=hours)) for cid in expected_ids
        for kind, hours in [("post_start", 0), ("voting_start", 1), ("result_announce", 2)]
    ]


def test_qualifier_explicit_times_and_default_fields(client, admin, monkeypatch):
    payload = dict(PAYLOAD, hasQualifier=True, qualifierStartTime="2025-12-30T12:00:00Z",
                   qualifierEndTime="2025-12-30T13:00:00Z", qualifierVotingEndTime="2025-12-30T14:00:00Z")
    effects = observe_admin_effects(monkeypatch)
    response = client.post("/api/admin/contests", json=payload)
    assert response.status_code == 201
    q = db.session.get(Contest, response.get_json()["qualifier_id"])
    assert (q.theme, q.has_theme, q.scoring_method, q.image_rule, q.general_vote_weight,
            q.judge_max_score, q.is_voting_visible) == (None, False, "both", "optional", 50, 10, True)
    assert [entry[2] for entry in effects[1:4]] == [NOW - timedelta(days=2) + timedelta(hours=i) for i in range(3)]


@pytest.mark.parametrize("payload", [{}, dict(PAYLOAD, startTime="bad"),
    dict(PAYLOAD, generalVoteWeight="bad"), dict(PAYLOAD, hasQualifier=True, qualifierJudgeMaxScore="bad")])
def test_create_invalid_input_rolls_back_without_scheduling(client, admin, monkeypatch, payload):
    effects = observe_admin_effects(monkeypatch)
    response = client.post("/api/admin/contests", json=payload)
    assert response.status_code == 500
    assert response.get_json() == {"error": "Failed to create contest"}
    assert effects == ["rollback"]
    assert Contest.query.count() == 0


@pytest.mark.parametrize("failure", ["commit", "schedule"])
def test_create_failure_preserves_commit_before_schedule_boundary(client, admin, monkeypatch, failure):
    effects = observe_admin_effects(monkeypatch, fail_commit=failure == "commit", fail_schedule=failure == "schedule")
    response = client.post("/api/admin/contests", json=PAYLOAD)
    assert response.status_code == 500
    assert response.get_json() == {"error": "Failed to create contest"}
    if failure == "commit":
        assert effects == ["commit", "rollback"]
        assert Contest.query.count() == 0
    else:
        assert effects[0] == "commit" and effects[-1] == "rollback"
        assert len(effects) == 3
        assert Contest.query.one().name == "Contest"


def test_update_all_fields_flags_alias_precedence_and_reschedule(client, admin, contest_factory, monkeypatch):
    contest = contest_factory(NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2),
                              theme="Old theme", notified_post_start=True, notified_voting_start=True,
                              notified_result_announce=True)
    effects = observe_admin_effects(monkeypatch)
    data = dict(PAYLOAD, name="Updated", theme="Dropped without hasTheme", type="daily", scoringMethod="user",
                imageRule="forbidden", isVotingVisible=False, advancementNumerator=0, advancementDenominator="0",
                generalVoteWeight="80", judgeMaxScore="12", judgePassword="new", resultCommentTop="Top",
                resultCommentBottom="Bottom", judgeAwardAdvancement=True, qualifierJudgeAwardAdvancement=False,
                startTime="2026-01-02T12:00:00Z", endTime="2026-01-02T13:00:00Z", votingEndTime="2026-01-02T14:00:00Z")
    response = client.put(f"/api/admin/contests/{contest.id}", json=data)
    assert response.status_code == 200
    assert response.get_json() == {"message": "Contest updated successfully"}
    db.session.refresh(contest)
    assert (contest.name, contest.theme, contest.has_theme, contest.type, contest.scoring_method, contest.image_rule,
            contest.is_voting_visible, contest.advancement_numerator, contest.advancement_denominator,
            contest.general_vote_weight, contest.judge_max_score, contest.judge_password, contest.result_comment_top,
            contest.result_comment_bottom, contest.judge_award_advancement) == (
                "Updated", None, True, "daily", "user", "forbidden", False, None, 0, 80, 12, "new", "Top", "Bottom", False)
    assert contest.notified_post_start and contest.notified_voting_start and contest.notified_result_announce
    assert effects == ["commit"] + [(contest.id, kind, NOW + timedelta(days=1, hours=hours))
                                   for kind, hours in [("post_start", 0), ("voting_start", 1), ("result_announce", 2)]]


def test_empty_update_still_commits_and_schedules_and_missing_lookup_precedes_json(client, admin, contest_factory, monkeypatch):
    contest = contest_factory(NOW, NOW, NOW)
    effects = observe_admin_effects(monkeypatch)
    missing = client.put("/api/admin/contests/999", data="bad JSON", content_type="application/json")
    assert missing.status_code == 404
    assert missing.get_json() == {"error": "Contest not found"}
    assert effects == []
    response = client.put(f"/api/admin/contests/{contest.id}", json={})
    assert response.status_code == 200
    assert effects == ["commit"] + [(contest.id, kind, NOW) for kind in ["post_start", "voting_start", "result_announce"]]


@pytest.mark.parametrize("method", ["post", "put"])
def test_null_json_keeps_admin_generic_failure(client, admin, contest_factory, monkeypatch, method):
    contest = contest_factory(NOW, NOW, NOW)
    effects = observe_admin_effects(monkeypatch)
    path = "/api/admin/contests" + (f"/{contest.id}" if method == "put" else "")
    response = getattr(client, method)(path, data="null", content_type="application/json")
    assert response.status_code == 500
    assert response.get_json() == {"error": "Failed to update contest" if method == "put" else "Failed to create contest"}
    assert effects == ["rollback"]


def test_delete_original_targets_and_order_leaves_related_data_and_child(client, admin, contest_factory, monkeypatch):
    contest = contest_factory(NOW, NOW, NOW)
    child = contest_factory(NOW, NOW, NOW, parent_contest_id=contest.id)
    post = Post(contest_id=contest.id, user_id=admin.id, content="Entry")
    post.images = ["/static/uploads/keep.png"]
    db.session.add(post)
    db.session.flush()
    post_id, contest_id, child_id = post.id, contest.id, child.id
    db.session.add_all([
        Vote(contest_id=contest_id, post_id=post_id, user_id=admin.id, count=1),
        ContestResult(contest_id=contest_id, post_id=post_id, user_id=admin.id, score=1, rank=1),
        Bookmark(post_id=post_id, user_id=admin.id),
        Comment(post_id=post_id, user_id=admin.id, content="Comment"),
    ])
    db.session.commit()
    deletes = []
    delete_image = Mock()
    monkeypatch.setattr(app_module, "delete_file", delete_image)

    def record(_conn, _cursor, statement, _params, _context, _executemany):
        if statement.startswith("DELETE FROM "):
            deletes.append(statement.split()[2])

    event.listen(db.engine, "before_cursor_execute", record)
    try:
        response = client.delete(f"/api/admin/contests/{contest_id}")
    finally:
        event.remove(db.engine, "before_cursor_execute", record)
    assert response.status_code == 200
    assert response.get_json() == {"message": "大会が正常に削除されました。"}
    assert deletes == ["vote", "post", "contest_result", "contest"]
    assert Vote.query.count() == Post.query.count() == ContestResult.query.count() == 0
    assert Bookmark.query.count() == Comment.query.count() == 1
    assert db.session.get(Contest, child_id).parent_contest_id is None
    delete_image.assert_not_called()


@pytest.mark.parametrize("method", ["put", "delete"])
def test_admin_commit_failure_rolls_back_updated_or_deleted_data(client, admin, contest_factory, monkeypatch, method):
    contest = contest_factory(NOW, NOW, NOW)
    post = Post(contest_id=contest.id, user_id=admin.id, content="Entry")
    db.session.add(post)
    db.session.flush()
    db.session.add(Vote(contest_id=contest.id, post_id=post.id, user_id=admin.id, count=1))
    db.session.commit()
    contest_id = contest.id
    effects = observe_admin_effects(monkeypatch, fail_commit=True)
    response = getattr(client, method)(f"/api/admin/contests/{contest_id}", json={"name": "Changed"})
    assert response.status_code == 500
    assert effects == ["commit", "rollback"]
    assert db.session.get(Contest, contest_id).name == "Test contest"
    assert Post.query.count() == Vote.query.count() == 1


@pytest.mark.parametrize("moment,expected", [
    (NOW.replace(tzinfo=None) + timedelta(hours=1), NOW + timedelta(hours=1, seconds=10)),
    (NOW.astimezone(timezone(timedelta(hours=9))) + timedelta(hours=1), NOW + timedelta(hours=1, seconds=10)),
    (NOW - timedelta(hours=1), NOW + timedelta(seconds=10)),
    (NOW - timedelta(seconds=10), NOW),
])
def test_schedule_timestamp_url_headers_and_exact_past_boundary(app, fixed_time, fake_cloud_tasks, moment, expected):
    fixed_time(NOW)
    app_module.schedule_contest_task(42, "post_start", moment)
    request = fake_cloud_tasks.create_task.call_args.kwargs["request"]
    assert request["parent"] == "projects/test/locations/test/queues/test"
    task = request["task"]
    assert task["http_request"] == {"http_method": 1,
        "url": "https://backend.example/api/tasks/contest/42/post_start",
        "headers": {"Content-type": "application/json"}}
    assert task["schedule_time"].ToDatetime(tzinfo=timezone.utc) == expected


def test_schedule_missing_config_fallback_and_error_boundaries(app, fixed_time, fake_cloud_tasks, monkeypatch, capsys):
    fixed_time(NOW)
    monkeypatch.setenv("GCP_PROJECT_ID", "")
    app_module.schedule_contest_task(42, "post_start", NOW)
    fake_cloud_tasks.create_task.assert_not_called()
    assert capsys.readouterr().out == "Skipping task scheduling for post_start - GCP configuration missing.\n"
    monkeypatch.setenv("GCP_PROJECT_ID", "test")
    monkeypatch.setenv("TASK_HANDLER_URL", "")
    monkeypatch.setenv("GCR_URL", "https://fallback.example/")
    fake_cloud_tasks.create_task.side_effect = RuntimeError("API failed")
    assert app_module.schedule_contest_task(42, "post_start", NOW) is None
    assert fake_cloud_tasks.create_task.call_args.kwargs["request"]["task"]["http_request"]["url"] == (
        "https://fallback.example//api/tasks/contest/42/post_start")
    assert capsys.readouterr().out == "Failed to create task for post_start: API failed\n"
    fake_cloud_tasks.queue_path.side_effect = RuntimeError("queue failed")
    with pytest.raises(RuntimeError, match="queue failed"):
        app_module.schedule_contest_task(42, "post_start", NOW)


def test_schedule_client_is_lazy_and_reused(app, fake_cloud_tasks, fixed_time, monkeypatch):
    fixed_time(NOW)
    monkeypatch.setattr(scheduler_module, "_cloud_tasks_client", None)
    factory = Mock(return_value=fake_cloud_tasks)
    monkeypatch.setattr(tasks_v2, "CloudTasksClient", factory)
    monkeypatch.setenv("GCP_PROJECT_ID", "")
    app_module.schedule_contest_task(42, "post_start", NOW)
    factory.assert_not_called()
    monkeypatch.setenv("GCP_PROJECT_ID", "test")
    for event_type in ("post_start", "voting_start"):
        app_module.schedule_contest_task(42, event_type, NOW)
    factory.assert_called_once_with()
    assert fake_cloud_tasks.create_task.call_count == 2
