"""Task and CLI contracts captured before the issue #11 extraction."""

from datetime import datetime, timedelta, timezone

import pytest

import app as app_module
from app.services import results as results_service
from app.models import Contest, ContestResult, Notification, Post, UserStats, db


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
EVENTS = (
    ("post_start", "start_time", "notified_post_start"),
    ("voting_start", "end_time", "notified_voting_start"),
    ("result_announce", "voting_end_time", "notified_result_announce"),
)


def observe_effects(monkeypatch):
    """Record ordering while allowing real writes to the fixture database."""
    events = []

    def wrap(target, name, label):
        original = getattr(target, name)

        def recorded(*args, **kwargs):
            events.append(label)
            return original(*args, **kwargs)

        monkeypatch.setattr(target, name, recorded)

    wrap(results_service, "generate_contest_results", "generate")
    wrap(db.session, "bulk_save_objects", "results")
    wrap(db.session, "bulk_insert_mappings", "notifications")
    wrap(db.session, "commit", "commit")
    original_add = db.session.add

    def add(instance, **kwargs):
        if isinstance(instance, Notification):
            events.append(instance.type)
        return original_add(instance, **kwargs)

    monkeypatch.setattr(db.session, "add", add)
    return events


@pytest.mark.parametrize("event,time_field,flag", EVENTS)
def test_task_effect_order_commit_counts_and_reexecution(
    task_client, contest_factory, user_factory, fixed_time, monkeypatch,
    event, time_field, flag,
):
    author = user_factory("author")
    deleted_user = user_factory("deleted_user")
    deleted_user.deleted_at = NOW
    contest = contest_factory(
        NOW - timedelta(hours=3), NOW - timedelta(hours=2), NOW - timedelta(hours=1)
    )
    db.session.add(Post(contest_id=contest.id, user_id=author.id, content="Entry"))
    db.session.commit()
    fixed_time(NOW)
    events = observe_effects(monkeypatch)
    path = f"/api/tasks/contest/{contest.id}/{event}"

    response = task_client.post(path)
    assert response.status_code == 200
    assert response.get_json() == {"message": f"Processed {event}"}
    expected = ["notifications", "commit"]
    if event == "result_announce":
        expected = ["generate", "results"] + expected
    assert events == expected
    assert getattr(db.session.get(Contest, contest.id), flag) is True
    # Preserve the current recipient selection, which includes soft-deleted users.
    assert {n.user_id for n in Notification.query.all()} == {author.id, deleted_user.id}
    events.clear()
    repeat = task_client.post(path)
    assert repeat.status_code == 200
    assert repeat.get_json() == {
        "message": "Task skipped (time not reached or already processed)"
    }
    assert events == []


@pytest.mark.parametrize("event,time_field,flag", EVENTS)
def test_task_exact_time_boundary(
    task_client, contest_factory, fixed_time, event, time_field, flag
):
    contest = contest_factory(NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2))
    event_time = getattr(contest, time_field).replace(tzinfo=timezone.utc)
    path = f"/api/tasks/contest/{contest.id}/{event}"
    fixed_time(event_time - timedelta(microseconds=1))
    before = task_client.post(path)
    assert before.status_code == 200
    assert before.get_json() == {
        "message": "Task skipped (time not reached or already processed)"
    }
    assert getattr(db.session.get(Contest, contest.id), flag) is False

    fixed_time(event_time)
    reached = task_client.post(path)
    assert reached.status_code == 200
    assert reached.get_json() == {"message": f"Processed {event}"}
    assert getattr(db.session.get(Contest, contest.id), flag) is True


def test_missing_contest_and_unknown_task_do_not_commit(
    task_client, contest_factory, fixed_time, monkeypatch
):
    contest = contest_factory(NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2))
    fixed_time(NOW)
    events = observe_effects(monkeypatch)
    missing = task_client.post("/api/tasks/contest/999/post_start")
    assert missing.status_code == 404
    assert missing.get_json() == {"error": "Contest not found"}
    unknown = task_client.post(f"/api/tasks/contest/{contest.id}/unknown")
    assert unknown.status_code == 200
    assert unknown.get_json() == {
        "message": "Task skipped (time not reached or already processed)"
    }
    assert events == []


def test_process_contests_commit_order_and_cleanup_boundary(
    runner, contest_factory, user_factory, fixed_time, monkeypatch
):
    user = user_factory("author")
    contest = contest_factory(
        NOW - timedelta(hours=3), NOW - timedelta(hours=2), NOW - timedelta(hours=1)
    )
    old = Notification(
        user_id=user.id, type="like",
        created_at=NOW - timedelta(days=30, microseconds=1),
    )
    boundary = Notification(user_id=user.id, type="like", created_at=NOW - timedelta(days=30))
    db.session.add_all([
        Post(contest_id=contest.id, user_id=user.id, content="Entry"), old, boundary,
    ])
    db.session.commit()
    old_id, boundary_id = old.id, boundary.id
    fixed_time(NOW)
    events = observe_effects(monkeypatch)

    result = runner.invoke(args=["process-contests"])
    assert result.exit_code == 0, result.output
    assert events == [
        "contest_post_start", "contest_voting_start", "generate", "results",
        "contest_result_announce", "commit", "commit",
    ]
    assert "Deleted 1 old notifications (older than 30 days)" in result.output
    db.session.expire_all()
    assert db.session.get(Notification, old_id) is None
    assert db.session.get(Notification, boundary_id) is not None
    assert ContestResult.query.filter_by(contest_id=contest.id).count() == 1
    events.clear()
    repeat = runner.invoke(args=["process-contests"])
    assert repeat.exit_code == 0
    assert events == []


def test_process_contests_cleanup_failure_rolls_back_and_finishes(
    runner, fixed_time, monkeypatch
):
    from flask_sqlalchemy.query import Query

    fixed_time(NOW)
    events = []
    original_rollback = db.session.rollback

    def reject_delete(*_args, **_kwargs):
        raise RuntimeError("cleanup failure")

    def rollback():
        events.append("rollback")
        original_rollback()

    monkeypatch.setattr(Query, "delete", reject_delete)
    monkeypatch.setattr(db.session, "rollback", rollback)
    result = runner.invoke(args=["process-contests"])
    assert result.exit_code == 0
    assert "Failed to delete old notifications: cleanup failure" in result.output
    assert result.output.endswith("--- process-contests batch completed ---\n")
    assert events == ["rollback"]


def test_update_user_stats_counts_ties_and_existing_rows(
    runner, contest_factory, user_factory, monkeypatch
):
    alpha = user_factory("alpha")
    beta = user_factory("beta")
    daily_winner = user_factory("daily_winner")
    empty = user_factory("empty")
    deleted = user_factory("deleted")
    deleted.deleted_at = NOW
    gp = contest_factory(NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2), type="grandprix")
    daily = contest_factory(NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2), type="daily")
    existing = UserStats(user_id=alpha.id, rank=99, gp_1st=99, daily_1st=99)
    db.session.add(existing)
    for contest, user, rank, award in (
        (gp, alpha, 1, True), (gp, beta, 1, True), (gp, deleted, 2, False),
        (daily, daily_winner, 1, False),
    ):
        post = Post(contest_id=contest.id, user_id=user.id, content="Entry")
        db.session.add(post)
        db.session.flush()
        db.session.add(ContestResult(
            contest_id=contest.id, user_id=user.id, post_id=post.id,
            rank=rank, score=0, is_judge_award=award,
        ))
    db.session.commit()
    existing_id = existing.id
    events = observe_effects(monkeypatch)

    for _ in range(2):
        events.clear()
        result = runner.invoke(args=["update-user-stats"])
        assert result.exit_code == 0, result.output
        assert result.output == (
            "--- update-user-stats batch started ---\n"
            "--- update-user-stats batch completed ---\n"
        )
        assert events == ["commit"]
        stats = {s.user_id: s for s in UserStats.query.all()}
        assert len(stats) == 5
        assert {uid: s.rank for uid, s in stats.items()} == {
            alpha.id: 1, beta.id: 1, deleted.id: 3, daily_winner.id: 4, empty.id: 5,
        }
        assert stats[alpha.id].id == existing_id
        assert (stats[alpha.id].gp_1st, stats[alpha.id].daily_1st, stats[alpha.id].judge_awards) == (1, 0, 1)
        assert stats[deleted.id].gp_2nd == 1
        assert stats[daily_winner.id].daily_1st == 1
        assert stats[empty.id].gp_1st == stats[empty.id].judge_awards == 0


def test_empty_stats_batch_keeps_single_commit(runner, monkeypatch):
    events = observe_effects(monkeypatch)
    result = runner.invoke(args=["update-user-stats"])
    assert result.exit_code == 0
    assert events == ["commit"]
    assert UserStats.query.count() == 0


@pytest.mark.parametrize("entry_point", ("task", "app.cli"))
def test_result_generation_failure_propagates_before_notification_commit(
    task_client, runner, contest_factory, fixed_time, monkeypatch, entry_point
):
    contest = contest_factory(
        NOW - timedelta(hours=3), NOW - timedelta(hours=2), NOW - timedelta(hours=1),
        notified_post_start=True, notified_voting_start=True,
    )
    fixed_time(NOW)
    events = observe_effects(monkeypatch)

    def fail_generation(_contest_id, **_kwargs):
        events.append("generate failure")
        raise RuntimeError("generation failed")

    monkeypatch.setattr(results_service, "generate_contest_results", fail_generation)
    if entry_point == "task":
        with pytest.raises(RuntimeError, match="generation failed"):
            task_client.post(f"/api/tasks/contest/{contest.id}/result_announce")
    else:
        result = runner.invoke(args=["process-contests"])
        assert result.exit_code == 1
        assert isinstance(result.exception, RuntimeError)
        assert str(result.exception) == "generation failed"
    assert events == ["generate failure"]
    assert contest.notified_result_announce is False
    assert Notification.query.count() == ContestResult.query.count() == 0


@pytest.mark.parametrize("command", ("process-contests", "update-user-stats"))
def test_cli_supplies_its_own_application_context(command):
    from flask import has_app_context
    from app.models import User

    application = app_module.create_app({
        "TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    })
    with application.app_context():
        db.create_all()
        db.session.add(User(twitter_id="standalone", screen_name="standalone", name="Standalone"))
        db.session.commit()
    try:
        assert not has_app_context()
        result = application.test_cli_runner().invoke(args=[command])
        assert result.exit_code == 0, result.output
        assert result.output.startswith(f"--- {command} batch started ---\n")
        assert result.output.endswith(f"--- {command} batch completed ---\n")
        assert not has_app_context()
        with application.app_context():
            assert UserStats.query.count() == (1 if command == "update-user-stats" else 0)
    finally:
        with application.app_context():
            db.session.remove()
            db.drop_all()


def test_task_and_cli_registration_preserve_compatibility_names(app):
    from app.routes.tasks import handle_contest_task
    from app.cli.process_contests import process_contests_command
    from app.cli.user_stats import update_user_stats

    assert app_module.handle_contest_task is handle_contest_task
    assert app_module.process_contests_command is process_contests_command
    assert app_module.update_user_stats is update_user_stats
    for application in (app_module.app, app):
        assert "tasks" in application.blueprints
        assert application.view_functions["tasks.handle_contest_task"] is handle_contest_task
        assert application.cli.commands["process-contests"] is process_contests_command
        assert application.cli.commands["update-user-stats"] is update_user_stats
        assert process_contests_command.callback.__module__ == "app.cli.process_contests"
        assert update_user_stats.callback.__module__ == "app.cli.user_stats"
