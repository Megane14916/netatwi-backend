import pytest

from app.models import Contest
from tests.api.test_contest_input_validation import BASE, admin_case


@pytest.mark.parametrize("length, status", [(117, 201), (118, 400), (120, 400)])
def test_qualifier_and_final_names_fit_database_limit(client, admin_case, length, status):
    response = client.post("/api/admin/contests", json=dict(BASE, name="x" * length, hasQualifier=True))
    assert response.status_code == status
    assert Contest.query.count() == (3 if status == 201 else 1)
    if status == 400:
        assert response.get_json() == {"error": "Invalid field: name"}
        admin_case[1].assert_not_called()
    else:
        data = response.get_json()
        assert len(Contest.query.filter_by(id=data["id"]).one().name) == 120
        assert len(Contest.query.filter_by(id=data["qualifier_id"]).one().name) == 120
