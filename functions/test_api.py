import json

import pytest
from firebase_admin import auth as firebase_auth

from api import (
    ALLOWED_ORIGINS,
    ApiError,
    _create_items,
    _create_reservation,
    _only_fields,
    _resolve_private_route,
    _sync_firebase_storage_role,
    _timestamp,
    _validate_item_type,
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


def test_item_type_prices_are_required_and_promotion_must_be_lower():
    fields = _validate_item_type(
        {"name": "Chocolate", "regular_price": 45, "promotional_price": 39.9},
        partial=False,
    )

    assert str(fields["regular_price"]) == "45.00"
    assert str(fields["promotional_price"]) == "39.90"
    with pytest.raises(ApiError, match="menor que o preço normal"):
        _validate_item_type(
            {
                "name": "Chocolate",
                "regular_price": 45,
                "promotional_price": 45,
            },
            partial=False,
        )


def test_item_type_creation_accepts_the_app_form_payload():
    fields = _validate_item_type(
        {
            "name": "Churros",
            "description": "Massa de chocolate com recheio de churros",
            "image_url": "https://example.com/churros.jpg",
            "regular_price": 12,
            "promotional_price": None,
            "is_custom_order_only": False,
            "is_active": True,
        },
        partial=False,
    )

    assert fields["name"] == "Churros"
    assert fields["regular_price"] == 12
    assert fields["image_url"] == "https://example.com/churros.jpg"


def test_unknown_fields_are_named_in_the_validation_error():
    with pytest.raises(ApiError, match="image_data") as exc_info:
        _only_fields(
            {"name": "Churros", "image_data": "not-an-api-field"},
            {"name"},
        )

    assert exc_info.value.code == "unknown_fields"


def test_reservations_cannot_exceed_two_units_before_database_access():
    with pytest.raises(ApiError, match="no máximo 2 unidades"):
        _create_reservation(
            connection=None,
            claims={"uid": "user-1"},
            payload={
                "pickup_spot_id": "00000000-0000-0000-0000-000000000001",
                "items": [
                    {
                        "item_type_id": "00000000-0000-0000-0000-000000000002",
                        "quantity": 3,
                    }
                ],
            },
        )


def test_stock_batches_cannot_exceed_500_units_before_database_access():
    with pytest.raises(ApiError, match="no máximo 500"):
        _create_items(
            connection=None,
            payload={
                "items": [
                    {
                        "item_type_id": "00000000-0000-0000-0000-000000000001",
                        "quantity": 501,
                    }
                ]
            },
        )


def test_admin_routes_include_stock_listing_and_reservation_deletion():
    assert _resolve_private_route("/api/v1/admin/items", "GET") == "admin_items_list"
    assert (
        _resolve_private_route("/api/v1/admin/reservations/res-1", "DELETE")
        == "admin_reservation_delete:res-1"
    )


def test_storage_role_mirror_uses_the_supabase_profile_role(monkeypatch):
    class Snapshot:
        exists = False

    class Document:
        def __init__(self):
            self.value = None

        def get(self):
            return Snapshot()

        def set(self, value, merge):
            self.value = (value, merge)

    document = Document()
    collection = type(
        "Collection",
        (),
        {"document": lambda self, user_id: document},
    )()
    client = type(
        "Client",
        (),
        {"collection": lambda self, name: collection},
    )()
    monkeypatch.setattr("api._firebase_app", lambda: object())
    monkeypatch.setattr("api.firebase_firestore.client", lambda app: client)

    _sync_firebase_storage_role({"auth_uid": "owner-uid", "role": "DONO"})

    assert document.value == ({"role": "DONO"}, True)
