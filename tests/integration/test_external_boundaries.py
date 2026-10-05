from datetime import datetime, timedelta, timezone
from io import BytesIO

import app as app_module
from werkzeug.datastructures import FileStorage


def test_anonymous_session_uses_test_database(client, app):
    assert app.config["SQLALCHEMY_DATABASE_URI"] == "sqlite:///:memory:"
    assert client.get("/api/me").get_json() == {"logged_in": False}


def test_x_authorization_is_faked(client, fake_x_authorization):
    response = client.get("/api/login/twitter")

    assert response.status_code == 200
    assert response.get_json() == {"authorization_url": "https://x.example/authorize"}
    with client.session_transaction() as session:
        assert session["oauth_state"] == "test-oauth-state"
        assert session["code_verifier"]


def test_r2_upload_is_faked(app, fake_r2):
    image = FileStorage(
        stream=BytesIO(b"test image"), filename="photo.png", content_type="image/png"
    )

    url = app_module.save_file(image)

    assert url.startswith("https://r2.example/")
    fake_r2.upload_fileobj.assert_called_once()
    assert fake_r2.upload_fileobj.call_args.args[1] == "test-bucket"


def test_cloud_task_creation_is_faked(app, fake_cloud_tasks):
    scheduled_at = datetime.now(timezone.utc) + timedelta(hours=1)

    app_module.schedule_contest_task(42, "post_start", scheduled_at)

    fake_cloud_tasks.create_task.assert_called_once()
    task = fake_cloud_tasks.create_task.call_args.kwargs["request"]["task"]
    assert task["http_request"]["url"] == (
        "https://backend.example/api/tasks/contest/42/post_start"
    )
    assert task["schedule_time"].ToDatetime(tzinfo=timezone.utc) == (
        scheduled_at + timedelta(seconds=10)
    )
