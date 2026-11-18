from datetime import date, datetime, time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import flet as ft
import pytest

from application import MaphiApplication
from features.pickup_spots.pickup_spots_logic import PickupSpot, PickupSpotController
from features.pickup_spots.pickup_spots_view import PickupSpotFormView
from firebase_rest import FirebaseRestError


def test_pickup_spot_availability_requires_fifteen_minutes_before_closing():
    now = datetime(
        2099, 12, 1, 10, 0, tzinfo=ZoneInfo("America/Sao_Paulo")
    )
    available_spot = PickupSpot(
        id="available",
        name="Aberto",
        address="Rua A",
        arrival_at=datetime(
            2099, 12, 1, 9, 0, tzinfo=ZoneInfo("America/Sao_Paulo")
        ),
        departure_at=datetime(
            2099, 12, 1, 10, 16, tzinfo=ZoneInfo("America/Sao_Paulo")
        ),
    )
    closing_in_fifteen_minutes = PickupSpot(
        id="closing",
        name="Fechando",
        address="Rua B",
        arrival_at=available_spot.arrival_at,
        departure_at=datetime(
            2099, 12, 1, 10, 15, tzinfo=ZoneInfo("America/Sao_Paulo")
        ),
    )
    too_short_window = PickupSpot(
        id="short",
        name="Janela curta",
        address="Rua C",
        arrival_at=datetime(
            2099, 12, 1, 10, 10, tzinfo=ZoneInfo("America/Sao_Paulo")
        ),
        departure_at=datetime(
            2099, 12, 1, 10, 20, tzinfo=ZoneInfo("America/Sao_Paulo")
        ),
    )

    assert PickupSpotController.is_pickup_spot_available(
        available_spot, now=now
    )
    assert not PickupSpotController.is_pickup_spot_available(
        closing_in_fifteen_minutes, now=now
    )
    assert not PickupSpotController.is_pickup_spot_available(
        too_short_window, now=now
    )


def test_pickup_spot_form_builds_with_calendar_and_time_pickers():
    page = SimpleNamespace(show_dialog=Mock())
    view = PickupSpotFormView(
        page,
        on_create=AsyncMock(),
        on_update=AsyncMock(),
        on_notice=Mock(),
        on_message=Mock(),
    )

    view.open_form()

    assert isinstance(view.arrival_date_picker, ft.DatePicker)
    assert isinstance(view.arrival_time_picker, ft.TimePicker)
    assert isinstance(view.departure_date_picker, ft.DatePicker)
    assert isinstance(view.departure_time_picker, ft.TimePicker)
    assert view.arrival_time_picker.hour_format == ft.TimePickerHourFormat.H24
    assert (
        view.arrival_time_picker.entry_mode
        == ft.TimePickerEntryMode.INPUT_ONLY
    )
    assert view.arrival_date_picker.locale == ft.Locale("pt", "BR")
    assert view.departure_date_picker.locale == ft.Locale("pt", "BR")
    assert view.arrival_date_label.value == "Selecionar data"
    assert view.departure_time_label.value == "Selecionar horário"
    assert view.dialog.modal is False
    assert view.dialog.on_dismiss == view._on_dismiss
    page.show_dialog.assert_called_once_with(view.dialog)
    view._open_arrival_date_picker()
    assert page.show_dialog.call_args.args[0] is view.arrival_date_picker


def test_mobile_pickup_spot_form_uses_fullscreen_bottom_sheet():
    page = SimpleNamespace(
        width=390,
        show_dialog=Mock(),
        update=Mock(),
    )
    view = PickupSpotFormView(
        page,
        on_create=AsyncMock(),
        on_update=AsyncMock(),
        on_notice=Mock(),
        on_message=Mock(),
    )

    view.open_form()

    assert isinstance(view.dialog, ft.BottomSheet)
    assert view.dialog.fullscreen is True
    assert view.dialog.show_drag_handle is True
    page.show_dialog.assert_called_once_with(view.dialog)


@pytest.mark.asyncio
async def test_pickup_spot_edit_form_submits_selected_id_and_datetime():
    page = SimpleNamespace(
        show_dialog=Mock(),
        update=Mock(),
        pop_dialog=Mock(),
    )
    existing = PickupSpot(
        id="centro",
        name="Loja do Centro",
        address="Rua A, 123",
        arrival_at=datetime(
            2099, 12, 1, 10, 0, tzinfo=ZoneInfo("America/Sao_Paulo")
        ),
        departure_at=datetime(
            2099, 12, 1, 18, 0, tzinfo=ZoneInfo("America/Sao_Paulo")
        ),
    )
    on_update = AsyncMock()
    view = PickupSpotFormView(
        page,
        on_create=AsyncMock(),
        on_update=on_update,
        on_notice=Mock(),
        on_message=Mock(),
    )
    view.open_form(existing)
    assert view.arrival_date == date(2099, 12, 1)
    assert view.arrival_time == time(10, 0)
    assert view.departure_date == date(2099, 12, 1)
    assert view.departure_time == time(18, 0)
    assert view.arrival_date_picker.value == date(2099, 12, 1)
    assert view.departure_time_picker.value == time(18, 0)
    view._arrival_date_changed(
        SimpleNamespace(
            control=SimpleNamespace(value=date(2099, 12, 2))
        )
    )
    view._arrival_time_changed(
        SimpleNamespace(control=SimpleNamespace(value=time(11, 0)))
    )
    view._departure_date_changed(
        SimpleNamespace(
            control=SimpleNamespace(value=date(2099, 12, 2))
        )
    )
    view._departure_time_changed(
        SimpleNamespace(control=SimpleNamespace(value=time(19, 0)))
    )

    await view._submit()

    on_update.assert_awaited_once_with(
        pickup_spot_id="centro",
        name="Loja do Centro",
        address="Rua A, 123",
        arrival_at="02/12/2099 11:00",
        departure_at="02/12/2099 19:00",
    )
    assert view.dialog is None


@pytest.mark.asyncio
async def test_pickup_spot_form_requires_date_and_time_selection():
    page = SimpleNamespace(
        show_dialog=Mock(),
        update=Mock(),
        pop_dialog=Mock(),
    )
    on_create = AsyncMock()
    view = PickupSpotFormView(
        page,
        on_create=on_create,
        on_update=AsyncMock(),
        on_notice=Mock(),
        on_message=Mock(),
    )
    view.open_form()
    view.name_field.value = "Loja do Centro"
    view.address_field.value = "Rua A, 123"

    await view._submit()

    assert view.form_error.visible is True
    assert "data e o horário de chegada" in view.form_error.value
    on_create.assert_not_awaited()


def test_dismissing_pickup_spot_form_clears_dialog_state():
    page = SimpleNamespace(show_dialog=Mock(), pop_dialog=Mock())
    view = PickupSpotFormView(
        page,
        on_create=AsyncMock(),
        on_update=AsyncMock(),
        on_notice=Mock(),
        on_message=Mock(),
    )
    view.open_form()

    view.dialog.on_dismiss(None)

    assert view.dialog is None
    view._close()
    page.pop_dialog.assert_not_called()


@pytest.mark.asyncio
async def test_pickup_spot_validation_error_is_shown_inside_the_form():
    page = SimpleNamespace(
        show_dialog=Mock(),
        update=Mock(),
        pop_dialog=Mock(),
    )
    on_message = Mock()
    view = PickupSpotFormView(
        page,
        on_create=AsyncMock(
            side_effect=ValueError(
                "A saída deve ser posterior à chegada."
            )
        ),
        on_update=AsyncMock(),
        on_notice=Mock(),
        on_message=on_message,
    )
    view.open_form()
    view.name_field.value = "Loja do Centro"
    view.address_field.value = "Rua A, 123"
    view._arrival_date_changed(
        SimpleNamespace(
            control=SimpleNamespace(value=date(2026, 11, 12))
        )
    )
    view._arrival_time_changed(
        SimpleNamespace(control=SimpleNamespace(value=time(18, 0)))
    )
    view._departure_date_changed(
        SimpleNamespace(
            control=SimpleNamespace(value=date(2026, 11, 12))
        )
    )
    view._departure_time_changed(
        SimpleNamespace(control=SimpleNamespace(value=time(17, 0)))
    )

    await view._submit()

    assert view.form_error.visible is True
    assert "posterior" in view.form_error.value
    assert view.dialog is not None
    on_message.assert_not_called()

    view._arrival_time_changed(
        SimpleNamespace(control=SimpleNamespace(value=time(18, 0)))
    )

    assert view.form_error.visible is False


@pytest.mark.asyncio
async def test_deleting_pickup_spot_cancels_reservations_before_deleting_spot():
    events = []

    def record_cancellation(pickup_spot_id, *, id_token):
        assert pickup_spot_id == "spot-1"
        assert id_token == "owner-token"
        events.append("cancel")

    app = object.__new__(MaphiApplication)
    app.auth_controller = SimpleNamespace(
        is_owner=True,
        id_token="owner-token",
        user_id="owner-1",
    )
    app.pickup_spot_controller = SimpleNamespace(
        deactivate_pickup_spot=AsyncMock(
            side_effect=lambda *_: events.append("deactivate")
        ),
        delete_pickup_spot=AsyncMock(
            side_effect=lambda *_: events.append("delete")
        ),
    )
    app.reservation_controller = SimpleNamespace(
        cancel_active_for_pickup=AsyncMock(
            side_effect=record_cancellation
        )
    )
    app.catalog_view = SimpleNamespace(
        refresh_pickup_spot_options=Mock(
            side_effect=lambda: events.append("refresh")
        )
    )
    app.page = SimpleNamespace(update=lambda: events.append("update"))
    app.load_database_item_types = AsyncMock(
        side_effect=lambda: events.append("items")
    )

    await app.delete_pickup_spot("spot-1")

    assert events == [
        "deactivate",
        "refresh",
        "update",
        "cancel",
        "delete",
        "refresh",
        "update",
        "items",
    ]
    app.reservation_controller.cancel_active_for_pickup.assert_awaited_once_with(
        "spot-1",
        id_token="owner-token",
    )


@pytest.mark.asyncio
async def test_pickup_spot_is_not_deleted_when_reservation_cancellation_fails():
    app = object.__new__(MaphiApplication)
    app.auth_controller = SimpleNamespace(
        is_owner=True,
        id_token="owner-token",
        user_id="owner-1",
    )
    app.pickup_spot_controller = SimpleNamespace(
        deactivate_pickup_spot=AsyncMock(),
        delete_pickup_spot=AsyncMock(),
    )
    app.catalog_view = SimpleNamespace(
        refresh_pickup_spot_options=Mock()
    )
    app.page = SimpleNamespace(update=Mock())
    app.reservation_controller = SimpleNamespace(
        cancel_active_for_pickup=AsyncMock(
            side_effect=FirebaseRestError("API indisponível", 503)
        )
    )

    with pytest.raises(FirebaseRestError, match="API indisponível"):
        await app.delete_pickup_spot("spot-1")

    app.pickup_spot_controller.deactivate_pickup_spot.assert_awaited_once()
    app.pickup_spot_controller.delete_pickup_spot.assert_not_awaited()


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
