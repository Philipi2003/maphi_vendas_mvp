import json

import pytest
from firebase_admin import auth as firebase_auth

from api import (
    ALLOWED_ORIGINS,
    ApiError,
    _timestamp,
    _validate_pickup_spot,
    handle_request,
)


class FakeRequest:
    def __init__(self, path, method="GET", headers=None, body=None, args=None):
        self.path = path
        self.method = method
        self.headers = headers or {}
        self.body = body
        self.args = args or {}

    def get_json(self, silent=False):
        if not silent:
            raise AssertionError("the handler should parse JSON silently")
        return self.body


def _payload(response):
    return json.loads(response.get_data(as_text=True))


def test_health_route_does_not_open_database():
    response = handle_request(
        FakeRequest("/api/v1/health"),
        connection_factory=lambda: pytest.fail("health must not connect to Postgres"),
    )

    assert response.status_code == 200
    assert _payload(response) == {"status": "ok"}


def test_private_route_requires_bearer_token_before_database_access():
    response = handle_request(
        FakeRequest("/api/v1/profile"),
        connection_factory=lambda: pytest.fail("unauthenticated request reached database"),
    )

    assert response.status_code == 401
    assert _payload(response)["error"]["code"] == "unauthenticated"


def test_invalid_firebase_token_is_rejected_before_database_access():
    def reject_token(token):
        assert token == "invalid"
        raise firebase_auth.InvalidIdTokenError("invalid token")

    response = handle_request(
        FakeRequest(
            "/api/v1/profile",
            headers={"Authorization": "Bearer invalid"},
        ),
        connection_factory=lambda: pytest.fail("invalid token reached database"),
        token_verifier=reject_token,
    )

    assert response.status_code == 401
    assert _payload(response)["error"]["code"] == "invalid_token"


def test_unknown_origin_is_rejected_before_route_processing():
    response = handle_request(
        FakeRequest(
            "/api/v1/health",
            headers={"Origin": "https://untrusted.example"},
        ),
        connection_factory=lambda: pytest.fail("health must not connect to Postgres"),
    )

    assert response.status_code == 403


def test_preflight_allows_configured_frontend_origin():
    origin = next(iter(ALLOWED_ORIGINS))
    response = handle_request(
        FakeRequest("/api/v1/catalog", method="OPTIONS", headers={"Origin": origin}),
        connection_factory=lambda: pytest.fail("preflight must not connect to Postgres"),
    )

    assert response.status_code == 204
    assert response.headers["Access-Control-Allow-Origin"] == origin


def test_timestamp_requires_timezone():
    with pytest.raises(ApiError, match="fuso horário"):
        _timestamp("2026-11-17T17:00:00", "window_start")


def test_pickup_spot_creation_can_omit_active_flag():
    fields = _validate_pickup_spot(
        {
            "name": "Praça",
            "address": "Rua Central, 10",
            "window_start": "2026-11-18T14:00:00-03:00",
            "window_end": "2026-11-18T17:00:00-03:00",
        },
        partial=False,
    )

    assert fields["window_end"] > fields["window_start"]
    assert "is_active" not in fields
