"""Canonical helper and per-application image contracts after #69."""

from io import BytesIO
from unittest.mock import Mock

import pytest
from werkzeug.datastructures import FileStorage

from app import create_app
from app.integrations import images
from app.services.text import calculate_weighted_length


def test_pure_text_does_not_require_an_application_context():
    assert calculate_weighted_length("Aあ🙂") == 5


@pytest.mark.parametrize("use_r2,expected", [("TrUe", True), (" true ", False), ("False", False)])
def test_image_configuration_is_loaded_for_each_application(monkeypatch, use_r2, expected):
    monkeypatch.setenv("USE_R2", use_r2)
    monkeypatch.setenv("R2_BUCKET_NAME", "bucket")
    monkeypatch.setenv("R2_PUBLIC_URL", "https://images.example///")
    application = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    assert application.config["USE_R2"] is expected
    assert application.config["UPLOAD_FOLDER"] == "static/uploads"
    assert application.config["ALLOWED_EXTENSIONS"] == {"png", "jpg", "jpeg", "gif", "webp"}
    assert application.config["R2_PUBLIC_URL"] == "https://images.example"
    monkeypatch.setenv("USE_R2", "False" if expected else "True")
    other = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    assert other.config["USE_R2"] is not expected
    assert application.config["USE_R2"] is expected


def test_image_storage_uses_active_config_client_and_logger_in_any_order():
    applications = [create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "USE_R2": True, "R2_BUCKET_NAME": name, "R2_PUBLIC_URL": "https://"+name+".example"}) for name in ("first", "second")]
    clients = [Mock(), Mock()]
    for application, client in zip(applications, clients):
        application.extensions["r2_client"] = client
        application.logger = Mock()
    for index in (1, 0, 1):
        with applications[index].app_context():
            file = FileStorage(stream=BytesIO(b"image"), filename="a.JPG", content_type="image/jpeg")
            assert images.allowed_file(file.filename)
            url = images.save_file(file)
            name = "first" if index == 0 else "second"
            assert url.startswith("https://"+name+".example/")
            images.delete_file(url)
            assert clients[index].upload_fileobj.call_args.args[1] == name
            assert clients[index].delete_object.call_args.kwargs["Bucket"] == name
            applications[index].logger.info.assert_called()
    assert clients[0].upload_fileobj.call_count == 1
    assert clients[1].upload_fileobj.call_count == 2


def test_image_storage_requires_an_application_context():
    with pytest.raises(RuntimeError):
        images.allowed_file("image.png")
