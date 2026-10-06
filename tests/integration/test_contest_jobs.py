"""Observable database effects of scheduled and batch contest jobs."""

from datetime import datetime, timedelta, timezone

import pytest

import app as app_module
from app import db
from app.models import Contest, ContestResult, Notification, Post


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def make_finished_contest(contest_factory, user):
    contest = contest_factory(
        NOW - timedelta(hours=3),
        NOW - timedelta(hours=2),
        NOW - timedelta(hours=1),
    )
    post = Post(contest_id=contest.id, user_id=user.id, content="Entry")
    db.session.add(post)
    db.session.commit()
    return contest, post


@pytest.mark.parametrize(
    ("event", "notification_type", "flag"),
    [
        ("post_start", "contest_post_start", "notified_post_start"),
        ("voting_start", "contest_voting_start", "notified_voting_start"),
        ("result_announce", "contest_result_announce", "notified_result_announce"),
    ],
)
def test_task_processes_each_event_once(
    task_client, contest_factory, user_factory, fixed_time, event, notification_type, flag
):
    author = user_factory("author")
    recipient = user_factory("recipient")
    contest, post = make_finished_contest(contest_factory, author)
    fixed_time(NOW)
    path = f"/api/tasks/contest/{contest.id}/{event}"

    first = task_client.post(path)
    repeat = task_client.post(path)

    assert first.status_code == repeat.status_code == 200
    assert first.get_json() == {"message": f"Processed {event}"}
    assert repeat.get_json() == {
        "message": "Task skipped (time not reached or already processed)"
    }
    assert getattr(db.session.get(Contest, contest.id), flag) is True
    assert {
        (notification.user_id, notification.type)
        for notification in Notification.query.filter_by(contest_id=contest.id).all()
    } == {(author.id, notification_type), (recipient.id, notification_type)}
    assert Notification.query.filter_by(contest_id=contest.id).count() == 2
    assert ContestResult.query.filter_by(contest_id=contest.id).count() == (
        1 if event == "result_announce" else 0
    )
    if event == "result_announce":
        assert ContestResult.query.filter_by(post_id=post.id).one().rank == 1


def test_task_waits_for_event_time(task_client, contest_factory, fixed_time):
    contest = contest_factory(NOW + timedelta(minutes=1), NOW + timedelta(hours=1), NOW + timedelta(hours=2))
    fixed_time(NOW)

    response = task_client.post(f"/api/tasks/contest/{contest.id}/post_start")

    assert response.get_json()["message"].startswith("Task skipped")
    assert db.session.get(Contest, contest.id).notified_post_start is False
    assert Notification.query.count() == 0


def test_cli_persists_notifications_and_results_once(
    runner, contest_factory, user_factory, fixed_time
):
    author = user_factory("author")
    recipient = user_factory("recipient")
    contest, post = make_finished_contest(contest_factory, author)
    fixed_time(NOW)

    first = runner.invoke(args=["process-contests"])
    repeat = runner.invoke(args=["process-contests"])

    assert first.exit_code == repeat.exit_code == 0
    saved = db.session.get(Contest, contest.id)
    assert saved.notified_post_start is True
    assert saved.notified_voting_start is True
    assert saved.notified_result_announce is True
    expected_types = {
        "contest_post_start",
        "contest_voting_start",
        "contest_result_announce",
    }
    assert {
        (notification.user_id, notification.type)
        for notification in Notification.query.filter_by(contest_id=contest.id).all()
    } == {(user.id, kind) for user in (author, recipient) for kind in expected_types}
    assert Notification.query.filter_by(contest_id=contest.id).count() == 6
    result = ContestResult.query.filter_by(contest_id=contest.id).one()
    assert result.post_id == post.id
    assert result.rank == 1


def test_overdue_task_is_scheduled_ten_seconds_from_now(
    app, fixed_time, fake_cloud_tasks
):
    fixed_time(NOW)

    app_module.schedule_contest_task(42, "result_announce", NOW - timedelta(hours=1))

    request = fake_cloud_tasks.create_task.call_args.kwargs["request"]
    assert request["parent"] == "projects/test/locations/test/queues/test"
    assert request["task"]["http_request"]["url"] == (
        "https://backend.example/api/tasks/contest/42/result_announce"
    )
    assert request["task"]["schedule_time"].ToDatetime(tzinfo=timezone.utc) == (
        NOW + timedelta(seconds=10)
    )
