from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from features.auth.auth_logic import AuthController
from features.catalog.catalog_logic import Cake, CatalogController
from features.pickup_spots.pickup_spots_logic import (
    PickupSpot,
    PickupSpotController,
)
from features.reservations.reservation_logic import ReservationController
from maphi_api import MaphiApiClient


@pytest.mark.asyncio
async def test_remove_items_api_sends_bulk_quantity():
    client = MaphiApiClient()
    client._request = AsyncMock(return_value={"result": {"removed": 3}})

    removed = await client.remove_items(
        "type-1", 3, "owner-token"
    )

    assert removed == 3
    client._request.assert_awaited_once_with(
        "POST",
        "/admin/items/remove",
        id_token="owner-token",
        payload={"item_type_id": "type-1", "quantity": 3},
    )


@pytest.mark.asyncio
async def test_authentication_loads_role_from_supabase_profile():
    controller = AuthController()
    controller.auth_client.sign_in = AsyncMock(
        return_value={
            "idToken": "firebase-id-token",
            "refreshToken": "firebase-refresh-token",
            "localId": "owner-uid",
            "displayName": "Dona",
        }
    )
    controller.api_client.upsert_profile = AsyncMock(
        return_value={"name": "Dona", "role": "DONO"}
    )

    await controller.submit(email="dona@example.com", password="secret")

    assert controller.is_owner
    controller.api_client.upsert_profile.assert_awaited_once_with(
        "Dona", "firebase-id-token"
    )


@pytest.mark.asyncio
async def test_catalog_maps_supabase_fields_and_stock():
    controller = CatalogController()
    controller.api_client.list_item_types = AsyncMock(
        return_value=[
            {
                "id": "type-1",
                "name": "Brigadeiro",
                "description": "Chocolate",
                "image_url": "https://example.com/brigadeiro.png",
                "regular_price": 45,
                "promotional_price": 39.9,
                "is_custom_order_only": False,
                "is_active": True,
                "stock": 3,
                "reserved_stock": 2,
            }
        ]
    )

    await controller.load_item_types()

    assert controller.cakes == [
        Cake(
            id="type-1",
            name="Brigadeiro",
            description="Chocolate",
            stock=3,
            color="#F0E2D6",
            image_url="https://example.com/brigadeiro.png",
            regular_price=45,
            promotional_price=39.9,
            is_active=True,
            reserved_stock=2,
        )
    ]


@pytest.mark.asyncio
async def test_production_sends_grouped_quantities_to_api():
    controller = CatalogController(
        [
            Cake("type-1", "Brigadeiro", "", 2, "#F0E2D6"),
            Cake("type-2", "Morango", "", 1, "#F3E4E6"),
        ]
    )
    controller.api_client.create_items = AsyncMock(return_value=[])

    total = await controller.add_stock(
        {"type-1": 2, "type-2": 3}, "owner-token"
    )

    assert total == 5
    controller.api_client.create_items.assert_awaited_once_with(
        [
            {"item_type_id": "type-1", "quantity": 2},
            {"item_type_id": "type-2", "quantity": 3},
        ],
        "owner-token",
    )
    assert {cake.id: cake.stock for cake in controller.cakes} == {
        "type-1": 4,
        "type-2": 4,
    }


@pytest.mark.asyncio
async def test_item_type_creation_sends_prices_and_uses_server_id():
    controller = CatalogController()
    controller.api_client.create_item_type = AsyncMock(
        return_value={"id": "server-type-id"}
    )
    controller.storage_client.upload_image = AsyncMock(
        return_value="https://example.com/image.png"
    )

    cake = await controller.create_item_type(
        name="Brigadeiro",
        description="Chocolate",
        regular_price="45,00",
        promotional_price="39,90",
        is_custom_order_only=False,
        is_active=True,
        id_token="owner-token",
        user_id="owner-uid",
        image_data=b"photo",
        image_filename="cake.png",
        image_content_type="image/png",
    )

    assert cake.id == "server-type-id"
    controller.api_client.create_item_type.assert_awaited_once_with(
        {
            "name": "Brigadeiro",
            "description": "Chocolate",
            "image_url": "https://example.com/image.png",
            "regular_price": 45.0,
            "promotional_price": 39.9,
            "is_custom_order_only": False,
            "is_active": True,
        },
        "owner-token",
    )


@pytest.mark.asyncio
async def test_item_type_update_clears_promotion_on_server():
    cake = Cake(
        "type-1",
        "Brigadeiro",
        "Chocolate",
        0,
        "#F0E2D6",
        regular_price=45,
        promotional_price=39.9,
        reserved_stock=2,
    )
    controller = CatalogController([cake])
    controller.api_client.update_item_type = AsyncMock(return_value={})

    updated = await controller.update_item_type(
        item_type_id="type-1",
        name="Brigadeiro",
        description="Chocolate",
        regular_price="45",
        promotional_price="",
        is_custom_order_only=False,
        is_active=True,
        id_token="owner-token",
        user_id="owner-uid",
    )

    assert updated.promotional_price is None
    assert updated.reserved_stock == 2
    fields = controller.api_client.update_item_type.await_args.args[1]
    assert fields["regular_price"] == 45.0
    assert fields["promotional_price"] is None


@pytest.mark.asyncio
async def test_removing_multiple_available_units_preserves_reserved_count():
    controller = CatalogController(
        [
            Cake(
                "type-1",
                "Brigadeiro",
                "",
                5,
                "#F0E2D6",
                reserved_stock=2,
            )
        ]
    )
    controller.quantities["type-1"] = 4
    controller.api_client.remove_items = AsyncMock(return_value=3)

    removed = await controller.remove_available_units(
        "type-1", 3, "owner-token"
    )

    assert removed == 3
    controller.api_client.remove_items.assert_awaited_once_with(
        "type-1", 3, "owner-token"
    )
    assert controller.cakes[0].stock == 2
    assert controller.cakes[0].reserved_stock == 2
    assert controller.quantities["type-1"] == 2


@pytest.mark.asyncio
async def test_pickup_spots_decode_and_encode_timestamp_fields():
    controller = PickupSpotController()
    controller.api_client.list_pickup_spots = AsyncMock(
        return_value=[
            {
                "id": "spot-1",
                "name": "Loja",
                "address": "Rua A",
                "window_start": "2099-12-01T13:00:00+00:00",
                "window_end": "2099-12-01T21:00:00+00:00",
                "is_active": True,
            }
        ]
    )

    await controller.load_active_pickup_spots()

    assert controller.pickup_spots == [
        PickupSpot(
            id="spot-1",
            name="Loja",
            address="Rua A",
            arrival_at=datetime(
                2099, 12, 1, 10, 0, tzinfo=ZoneInfo("America/Sao_Paulo")
            ),
            departure_at=datetime(
                2099, 12, 1, 18, 0, tzinfo=ZoneInfo("America/Sao_Paulo")
            ),
            is_active=True,
        )
    ]

    controller.api_client.create_pickup_spot = AsyncMock(
        return_value={
            "id": "server-spot-id",
            "name": "Loja",
            "address": "Rua A",
            "window_start": "2099-12-01T13:00:00+00:00",
            "window_end": "2099-12-01T21:00:00+00:00",
            "is_active": True,
        }
    )
    await controller.create_pickup_spot(
        name="Loja",
        address="Rua A",
        arrival_at="01/12/2099 10:00",
        departure_at="01/12/2099 18:00",
        id_token="owner-token",
    )
    request = controller.api_client.create_pickup_spot.await_args.args
    assert request[0]["window_start"] == "2099-12-01T13:00:00Z"
    assert request[0]["window_end"] == "2099-12-01T21:00:00Z"


@pytest.mark.asyncio
async def test_reservation_sends_multiple_flavors_in_one_request():
    controller = ReservationController()
    controller.api_client.create_reservation = AsyncMock(
        return_value={
            "id": "reservation-1",
            "user_id": "user-1",
            "user_name": "Cliente",
            "pickup_spot_id": "spot-1",
            "pickup_spot_name": "Loja",
            "pickup_spot_address": "Rua A",
            "window_start": "2099-12-01T13:00:00+00:00",
            "window_end": "2099-12-01T21:00:00+00:00",
            "items": [
                {
                    "item_id": "unit-1",
                    "item_type_id": "type-1",
                    "item_type_name": "Brigadeiro",
                    "unit_price": 39.9,
                },
                {
                    "item_id": "unit-2",
                    "item_type_id": "type-2",
                    "item_type_name": "Morango",
                    "unit_price": 45,
                },
            ],
            "total_amount": 84.9,
            "sale_type": "PROMOCAO",
            "status": "ATIVA",
            "created_at": "2099-11-30T12:00:00+00:00",
        }
    )

    reservation = await controller.create_reservation(
        quantities={"type-1": 2, "type-2": 1},
        pickup_spot_id="spot-1",
        id_token="firebase-token",
    )

    assert reservation.total_amount == Decimal("84.90")
    assert reservation.item_ids == ("unit-1", "unit-2")
    controller.api_client.create_reservation.assert_awaited_once_with(
        {
            "pickup_spot_id": "spot-1",
            "items": [
                {"item_type_id": "type-1", "quantity": 2},
                {"item_type_id": "type-2", "quantity": 1},
            ],
        },
        "firebase-token",
    )


@pytest.mark.asyncio
async def test_reservation_listing_uses_server_side_pickup_filter():
    controller = ReservationController()
    controller.api_client.list_reservations = AsyncMock(return_value=[])

    await controller.load_reservations(
        user_id="owner-uid",
        id_token="firebase-token",
        is_owner=True,
        pickup_spot_id="spot-1",
    )

    controller.api_client.list_reservations.assert_awaited_once_with(
        id_token="firebase-token",
        is_owner=True,
        pickup_spot_id="spot-1",
    )


@pytest.mark.asyncio
async def test_cancelling_reservation_uses_api_response_for_local_state():
    controller = ReservationController()
    controller.api_client.cancel_reservation = AsyncMock(
        return_value={
            "id": "reservation-1",
            "user_id": "user-1",
            "user_name": "Cliente",
            "pickup_spot_id": "spot-1",
            "pickup_spot_name": "Loja",
            "pickup_spot_address": "Rua A",
            "window_start": None,
            "window_end": None,
            "items": [],
            "total_amount": 0,
            "sale_type": "PROMOCAO",
            "status": "CANCELADA",
            "created_at": None,
            "cancelled_by": "CLIENTE",
            "cancelled_at": "2099-12-01T12:00:00+00:00",
        }
    )

    await controller.cancel_reservation(
        "reservation-1", id_token="firebase-token"
    )

    controller.api_client.cancel_reservation.assert_awaited_once_with(
        "reservation-1", "firebase-token"
    )
