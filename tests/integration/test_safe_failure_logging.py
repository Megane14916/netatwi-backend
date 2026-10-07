"""Failure diagnostics retain context without exception payloads or source lines."""

from io import BytesIO

import pytest
from werkzeug.datastructures import FileStorage

from app.diagnostics import log_failure
from app.integrations import cloud_tasks, images


def test_diagnostics_exclude_exception_chain_and_source_line(app, caplog):
    def fail_with_secret():
        raise RuntimeError("oauth-code private-key")

    try:
        fail_with_secret()
    except RuntimeError as error:
        log_failure("test.operation", error)
    assert "test.operation" in caplog.text and "RuntimeError" in caplog.text
    assert "fail_with_secret" in caplog.text
    assert "oauth-code" not in caplog.text and "private-key" not in caplog.text


def test_storage_failure_logs_context_and_retains_compensation_url(fake_r2, caplog, capsys):
    fake_r2.upload_fileobj.side_effect = RuntimeError("private-key")
    file = FileStorage(stream=BytesIO(b"image"), filename="image.png", content_type="image/png")
    with pytest.raises(RuntimeError) as failure:
        images.save_file(file)
    assert failure.value.uploaded_image_url.startswith("https://r2.example/")
    assert "images.upload_r2" in caplog.text and "RuntimeError" in caplog.text
    output = capsys.readouterr()
    assert "private-key" not in caplog.text + output.out + output.err


def test_task_scheduling_failure_is_safe_and_remains_best_effort(fake_cloud_tasks, caplog, capsys):
    from datetime import datetime, timezone

    fake_cloud_tasks.create_task.side_effect = RuntimeError("private-key")
    assert cloud_tasks.schedule_contest_task(123, "post_start", datetime.now(timezone.utc)) is None
    assert "cloud_tasks.schedule_contest_task" in caplog.text
    assert "RuntimeError" in caplog.text
    output = capsys.readouterr()
    assert "private-key" not in caplog.text + output.out + output.err
