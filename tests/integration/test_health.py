"""Health-check integration tests."""

import pytest


@pytest.mark.parametrize("path", ["/health", "/api/v1/health"])
def test_health_check(client, path):
    response = client.get(path)

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ok",
        "service": "yottaflex-transaction-risk",
        "phase": 1,
    }
