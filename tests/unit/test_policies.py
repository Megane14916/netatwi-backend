from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services import policies


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize("offset, expected", [(-1, False), (0, True), (1, True), (999999, True), (1000000, False), (1000001, False)])
def test_half_open_period(offset, expected):
    assert policies.in_period(NOW + timedelta(microseconds=offset), NOW.replace(tzinfo=None), NOW + timedelta(seconds=1)) is expected


@pytest.mark.parametrize("offset, expected", [(-1, False), (0, True), (1, True)])
def test_reached_boundary(offset, expected):
    assert policies.has_reached(NOW + timedelta(microseconds=offset), NOW.replace(tzinfo=None)) is expected


@pytest.mark.parametrize("session, expected", [({}, False), ({"screen_name": "admin"}, False), ({"user_id": 1, "screen_name": "member"}, False), ({"user_id": 1, "screen_name": "admin"}, True)])
def test_admin_requires_login_and_configured_screen_name(monkeypatch, session, expected):
    monkeypatch.setenv("ADMIN_SCREEN_NAMES", " admin, , other ")
    assert policies.is_admin(session) is expected


def test_judge_and_owner_are_specific_to_contest_and_resource():
    assert policies.is_judge(1, [1])
    assert not policies.is_judge(2, [1])
    resource = SimpleNamespace(user_id=1)
    assert policies.is_owner(resource, 1)
    assert not policies.is_owner(resource, 2)
