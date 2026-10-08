import json
import pytest

from app.models import News


@pytest.mark.parametrize("body", [None, [], True, 42, "text", {"tweet_id": 123}, {"tweet_id": True}, {"tweet_id": [123]}, {"tweet_id": {"id": 123}}, {"tweet_id": "x" * 81}])
def test_news_invalid_input_is_400_without_write(client, user_factory, login, body):
    login(user_factory("test_admin"))
    response = client.post("/api/admin/news", data=json.dumps(body), content_type="application/json")
    assert response.status_code == 400
    assert "error" in response.get_json()
    assert News.query.count() == 0
