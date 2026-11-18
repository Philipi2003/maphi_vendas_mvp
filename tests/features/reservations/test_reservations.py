from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import flet as ft
import pytest

from application import MaphiApplication
from features.reservations.reservation_logic import Reservation, ReservationController
from features.reservations.reservation_view import ReservationView


def test_reservation_card_uses_fluid_width_and_wraps_header_on_mobile():
    page = SimpleNamespace(update=Mock())
    view = ReservationView(
        page,
        on_back=Mock(),
        on_cancel=AsyncMock(),
        on_complete=AsyncMock(),
        on_delete=AsyncMock(),
        on_filter=AsyncMock(),
        on_refresh=AsyncMock(),
        on_message=Mock(),
    )
    reservation = Reservation(
        id="reservation-12345678",
        user_id="user-1",
        user_name="Cliente com nome extenso",
        pickup_spot_id="centro",
        pickup_spot_name="Loja do Centro",
        pickup_spot_address="Rua A, 123, bairro e cidade",
        pickup_arrival_at=None,
        pickup_departure_at=None,
        item_ids=("item-1",),
        item_type_names=("Sabor de bolo",),
        unit_prices=(Decimal("10.00"),),
        total_amount=Decimal("10.00"),
        sale_type="NORMAL",
        status="ATIVA",
        created_at=None,
    )

    view.set_reservations(
        [reservation],
        is_owner=True,
        pickup_spots=[],
        selected_pickup_spot_id=None,
    )

    card = view.list_column.controls[0]
    header = card.content.controls[0]
    assert card.width is None
    assert isinstance(header, ft.ResponsiveRow)
    assert [control.col["xs"] for control in header.controls] == [12, 12]
    assert view.list_column.horizontal_alignment == ft.CrossAxisAlignment.STRETCH
    assert (
        view.root.content.content.horizontal_alignment
        == ft.CrossAxisAlignment.STRETCH
    )


@pytest.mark.asyncio
async def test_reserving_multiple_flavors_creates_one_reservation():
    app = object.__new__(MaphiApplication)
    app.auth_controller = SimpleNamespace(
        is_authenticated=True,
        is_owner=False,
        id_token="customer-token",
        user_id="customer-1",
        user_name="Maria",
    )
    app.pickup_spot_controller = SimpleNamespace(
        selected_pickup_spot=SimpleNamespace(id="centro")
    )
    app.catalog_controller = SimpleNamespace(
        quantities={"chocolate": 2, "morango": 1},
        cakes=[SimpleNamespace(id="chocolate"), SimpleNamespace(id="morango")],
    )
    app.catalog_view = SimpleNamespace(
        reserve_button=SimpleNamespace(disabled=False),
        owner_reserve_button=SimpleNamespace(disabled=False),
        refresh=Mock(),
    )
    app.page = SimpleNamespace(update=Mock())
    app.is_creating_reservation = False
    app.reservation_controller = SimpleNamespace(
        create_reservation=AsyncMock(
            return_value=SimpleNamespace(total_amount=Decimal("45.00"))
        )
    )
    app.load_database_item_types = AsyncMock()
    app.show_notice = Mock()
    app.show_message = Mock()
    app.open_reservations = AsyncMock()

    await app.start_reservation()

    calls = app.reservation_controller.create_reservation.await_args_list
    assert [call.kwargs["quantities"] for call in calls] == [
        {"chocolate": 2, "morango": 1},
    ]
    assert app.catalog_controller.quantities == {
        "chocolate": 0,
        "morango": 0,
    }
    app.show_notice.assert_called_once_with(
        "1 reserva criada. Valor a pagar: R$ 45,00"
    )
    app.open_reservations.assert_awaited_once()


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
