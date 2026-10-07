from datetime import datetime, timedelta, timezone
import json
import pytest


@pytest.mark.parametrize("body", [None, [], True, 42, "text", {"password": 123}, {"password": True}, {"password": []}, {"password": {}}, {"password": "s" * 121}])
def test_invalid_judge_password_is_400_and_preserves_session(client, user_factory, contest_factory, login, body):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    contest = contest_factory(now, now + timedelta(hours=1), now + timedelta(hours=2), judge_password="secret")
    login(user_factory("judge"), judge_contests=[999])
    response = client.post(f"/api/contests/{contest.id}/judge/login", data=json.dumps(body), content_type="application/json")
    assert response.status_code == 400
    assert "error" in response.get_json()
    with client.session_transaction() as session:
        assert session["judge_for_contest_ids"] == [999]
