import asyncio
import inspect
import json
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import flet as ft
import pytest

from application import MaphiApplication
from features.auth.auth_logic import AuthController, FirebaseAuthClient, FirebaseAuthError
from features.auth.auth_view import AuthView
from features.auth.account_button_view import AccountButtonView
from features.catalog.catalog_logic import (
    Cake,
    CatalogController,
    ItemTypeImageCleanupError,
    ItemTypeNameSyncError,
)
from features.catalog.catalog_view import CatalogView
from features.inventory.production_view import ProductionFormView
from features.pickup_spots.pickup_spots_logic import (
    PickupSpot,
    PickupSpotController,
)
from features.pickup_spots.pickup_spots_view import PickupSpotFormView
from features.reservations.reservation_logic import (
    ReservationController,
    ReservationError,
)
from firebase_rest import (
    FirebaseFirestoreClient,
    FirebaseRestError,
    FirebaseStorageClient,
)






@pytest.mark.asyncio
async def test_restore_session_removes_revoked_refresh_token():
    session_storage = SimpleNamespace(
        get=AsyncMock(
            return_value=json.dumps(
                {"refreshToken": "revoked-refresh", "provider": "password"}
            )
        ),
        set=AsyncMock(return_value=True),
        remove=AsyncMock(return_value=True),
    )
    controller = AuthController(session_storage=session_storage)
    controller.auth_client.refresh_session = AsyncMock(
        side_effect=FirebaseAuthError(
            "INVALID_REFRESH_TOKEN", code="INVALID_REFRESH_TOKEN"
        )
    )

    with pytest.raises(FirebaseAuthError, match="expirou ou foi revogada"):
        await controller.restore_session()

    session_storage.remove.assert_awaited_once_with(
        controller.SESSION_STORAGE_KEY
    )


@pytest.mark.asyncio
async def test_restore_session_discards_malformed_saved_data():
    session_storage = SimpleNamespace(
        get=AsyncMock(return_value="[]"),
        set=AsyncMock(return_value=True),
        remove=AsyncMock(return_value=True),
    )
    controller = AuthController(session_storage=session_storage)

    with pytest.raises(FirebaseAuthError, match="sessão salva está inválida"):
        await controller.restore_session()

    session_storage.remove.assert_awaited_once_with(
        controller.SESSION_STORAGE_KEY
    )


@pytest.mark.asyncio
async def test_application_restores_session_before_loading_catalog():
    events = []
    app = object.__new__(MaphiApplication)
    app.auth_controller = SimpleNamespace(
        restore_session=AsyncMock(
            side_effect=lambda: events.append("restore") or True
        ),
        is_owner=True,
        is_authenticated=True,
    )
    app.auth_view = SimpleNamespace(
        refresh_account_button=Mock(
            side_effect=lambda: events.append("account")
        )
    )
    app.catalog_controller = SimpleNamespace(hide_inactive_item_types=Mock())
    app.catalog_view = SimpleNamespace(
        set_account_state=Mock(
            side_effect=lambda **_: events.append("account-state")
        )
    )
    app.load_database_item_types = AsyncMock(
        side_effect=lambda: events.append("items")
    )
    app.load_database_pickup_spots = AsyncMock(
        side_effect=lambda: events.append("pickups")
    )
    app.show_notice = Mock()

    await app.initialize()

    app.auth_controller.restore_session.assert_awaited_once()
    app.auth_view.refresh_account_button.assert_called_once()
    app.catalog_view.set_account_state.assert_called_once_with(
        is_authenticated=True, is_owner=True
    )
    app.load_database_item_types.assert_awaited_once()
    app.load_database_pickup_spots.assert_awaited_once()
    assert events == [
        "restore",
        "account-state",
        "account",
        "items",
        "pickups",
    ]






@pytest.mark.asyncio
async def test_google_logout_signs_out_from_firebase_bridge():
    controller = AuthController()
    controller.auth_provider = "google"
    controller.google_auth_client.sign_out = AsyncMock()

    await controller.sign_out_provider()

    controller.google_auth_client.sign_out.assert_awaited_once()




















@pytest.mark.asyncio
async def test_saving_item_type_updates_catalog_after_closing_form():
    events = []
    view = object.__new__(CatalogView)
    view.item_type_name = SimpleNamespace(value="Limão")
    view.item_type_description = SimpleNamespace(value="Bolo cítrico")
    view.item_type_regular_price = SimpleNamespace(value="42,00")
    view.item_type_promotional_price = SimpleNamespace(value="")
    view.item_type_custom_order = SimpleNamespace(value=False)
    view.item_type_is_active = SimpleNamespace(value=True)
    view.item_type_submit_button = SimpleNamespace(disabled=False)
    view.editing_item_type = None
    view.item_type_dialog = object()
    view.selected_image_data = None
    view.selected_image_name = None
    view.selected_image_content_type = None
    view.on_create_item_type = AsyncMock()
    view.refresh = lambda: events.append("refresh")
    view.on_notice = lambda _: events.append("notice")
    view.on_message = lambda message: events.append(("message", message))
    view.page = SimpleNamespace(update=lambda: events.append("update"))

    def close_form():
        events.append("close")
        view.item_type_dialog = None

    view._close_item_type_form = close_form

    await view._submit_item_type()

    close_index = events.index("close")
    catalog_update_index = events.index("update", close_index + 1)
    assert events.index("refresh") < close_index < catalog_update_index
    assert catalog_update_index < events.index("notice")
    view.on_create_item_type.assert_awaited_once()


@pytest.mark.asyncio
async def test_storage_upload_returns_public_download_url():
    client = FirebaseStorageClient(bucket="maphi-bucket")
    client._request = AsyncMock(return_value={
        "downloadTokens": "download-token"
    })

    url = await client.upload_image(
        "itemTypes/owner-uid/chocolate cake.png",
        b"image bytes",
        "image/png",
        "owner-token",
    )

    assert url == (
        "https://firebasestorage.googleapis.com/v0/b/maphi-bucket/o/"
        "itemTypes%2Fowner-uid%2Fchocolate%20cake.png"
        "?alt=media&token=download-token"
    )
    client._request.assert_awaited_once()


@pytest.mark.asyncio
async def test_storage_delete_uses_encoded_object_path_and_auth_token():
    client = FirebaseStorageClient(bucket="maphi-bucket")
    client._request = AsyncMock(return_value={})

    deleted = await client.delete_image(
        "https://firebasestorage.googleapis.com/v0/b/maphi-bucket/o/"
        "itemTypes%2Fowner-uid%2Fchocolate%20cake.png?alt=media&token=secret",
        "owner-token",
    )

    assert deleted is True
    request_url = client._request.await_args.args[0]
    request_options = client._request.await_args.kwargs
    assert request_url.endswith(
        "/o/itemTypes%2Fowner-uid%2Fchocolate%20cake.png"
    )
    assert request_options["method"] == "DELETE"
    assert request_options["headers"] == {
        "Authorization": "Bearer owner-token"
    }


@pytest.mark.asyncio
async def test_storage_delete_ignores_external_image_urls():
    client = FirebaseStorageClient(bucket="maphi-bucket")
    client._request = AsyncMock()

    deleted = await client.delete_image(
        "https://example.com/chocolate.png", "owner-token"
    )

    assert deleted is False
    client._request.assert_not_awaited()


@pytest.mark.asyncio
async def test_item_type_query_uses_firestore_run_query_endpoint():
    client = FirebaseFirestoreClient(project_id="maphi-project")
    client._request = AsyncMock(return_value=[])

    await client.list_active_item_types()

    request_url = client._request.await_args.args[0]
    request_options = client._request.await_args.kwargs
    assert request_url == (
        "https://firestore.googleapis.com/v1/projects/maphi-project/"
        "databases/(default)/documents:runQuery"
    )
    assert request_options["payload"]["structuredQuery"]["from"] == [
        {"collectionId": "itemTypes"}
    ]


@pytest.mark.asyncio
async def test_inventory_check_queries_item_type_with_owner_token():
    client = FirebaseFirestoreClient(project_id="maphi-project")
    client._request = AsyncMock(return_value=[{"document": {"name": "item-1"}}])

    assert await client.has_items_for_item_type("chocolate", "owner-token")

    request_options = client._request.await_args.kwargs
    query = request_options["payload"]["structuredQuery"]
    assert request_options["id_token"] == "owner-token"
    assert query["from"] == [{"collectionId": "items"}]
    assert query["where"]["fieldFilter"]["field"]["fieldPath"] == "itemTypeId"
    assert query["limit"] == 1


@pytest.mark.asyncio
async def test_item_type_inventory_query_includes_all_item_statuses():
    client = FirebaseFirestoreClient(project_id="maphi-project")
    client._request = AsyncMock(return_value=[])

    await client.list_items_for_item_type("chocolate", "owner-token")

    query = client._request.await_args.kwargs["payload"]["structuredQuery"]
    assert client._request.await_args.kwargs["id_token"] == "owner-token"
    assert query["from"] == [{"collectionId": "items"}]
    assert query["where"]["fieldFilter"] == {
        "field": {"fieldPath": "itemTypeId"},
        "op": "EQUAL",
        "value": {"stringValue": "chocolate"},
    }


@pytest.mark.asyncio
async def test_firestore_updates_item_names_with_field_mask():
    client = FirebaseFirestoreClient(project_id="maphi-project")
    client._request = AsyncMock(return_value={})

    await client.update_documents_atomically(
        "items",
        [
            (
                "unit-1",
                {"itemTypeName": {"stringValue": "Chocolate amargo"}},
            )
        ],
        ["itemTypeName"],
        "owner-token",
    )

    request_options = client._request.await_args.kwargs
    assert request_options["payload"]["writes"] == [
        {
            "update": {
                "name": (
                    "projects/maphi-project/databases/(default)/documents/"
                    "items/unit-1"
                ),
                "fields": {
                    "itemTypeName": {"stringValue": "Chocolate amargo"}
                },
            },
            "updateMask": {"fieldPaths": ["itemTypeName"]},
        }
    ]


@pytest.mark.asyncio
async def test_available_item_query_filters_for_in_stock_status():
    client = FirebaseFirestoreClient(project_id="maphi-project")
    client._request = AsyncMock(return_value=[])

    await client.list_available_items()

    query = client._request.await_args.kwargs["payload"]["structuredQuery"]
    assert query["from"] == [{"collectionId": "items"}]
    assert query["where"]["fieldFilter"] == {
        "field": {"fieldPath": "status"},
        "op": "EQUAL",
        "value": {"stringValue": "DISPONIVEL"},
    }


@pytest.mark.asyncio
async def test_firestore_creates_inventory_documents_atomically():
    client = FirebaseFirestoreClient(project_id="maphi-project")
    client._request = AsyncMock(return_value={})

    await client.create_documents_atomically(
        "items",
        [
            (
                "unit-1",
                {
                    "itemTypeId": {"stringValue": "chocolate"},
                    "status": {"stringValue": "DISPONIVEL"},
                },
            ),
            (
                "unit-2",
                {
                    "itemTypeId": {"stringValue": "morango"},
                    "status": {"stringValue": "DISPONIVEL"},
                },
            ),
        ],
        "owner-token",
    )

    request_url = client._request.await_args.args[0]
    request_options = client._request.await_args.kwargs
    assert request_url.endswith("/documents:commit")
    assert request_options["id_token"] == "owner-token"
    writes = request_options["payload"]["writes"]
    assert len(writes) == 2
    assert writes[0]["update"]["name"] == (
        "projects/maphi-project/databases/(default)/documents/items/unit-1"
    )
    assert writes[1]["update"]["fields"]["itemTypeId"] == {
        "stringValue": "morango"
    }
    assert all(
        write["currentDocument"] == {"exists": False} for write in writes
    )


@pytest.mark.asyncio
async def test_active_pickup_spot_query_only_returns_active_locations():
    client = FirebaseFirestoreClient(project_id="maphi-project")
    client._request = AsyncMock(return_value=[])

    await client.list_active_pickup_spots()

    request_url = client._request.await_args.args[0]
    request_options = client._request.await_args.kwargs
    assert request_url.endswith("/documents:runQuery")
    assert request_options["payload"]["structuredQuery"]["from"] == [
        {"collectionId": "pickupSpots"}
    ]
    assert (
        request_options["payload"]["structuredQuery"]["where"]["fieldFilter"]
        == {
            "field": {"fieldPath": "isActive"},
            "op": "EQUAL",
            "value": {"booleanValue": True},
        }
    )




def test_catalog_displays_pickup_location_and_schedule():
    pickup_spot = PickupSpot(
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
    controller = PickupSpotController()
    controller.pickup_spots = [pickup_spot]
    controller.select_pickup_spot("centro")
    view = object.__new__(CatalogView)
    view.pickup_spot_controller = controller
    view.is_owner = False
    view.pickup_spot_dropdown = SimpleNamespace()
    view.pickup_spot_details = SimpleNamespace()
    view.pickup_spot_edit_button = SimpleNamespace()
    view.pickup_spot_delete_button = SimpleNamespace()
    view.reserve_button = SimpleNamespace()
    view.owner_reserve_button = SimpleNamespace()

    view.refresh_pickup_spot_options()

    option = view.pickup_spot_dropdown.options[0]
    assert option.key == "centro"
    assert option.text == "Loja do Centro · 01/12/2099 10:00 às 01/12/2099 18:00"
    assert view.pickup_spot_dropdown.value == "centro"
    assert view.pickup_spot_dropdown.disabled is False
    assert "Rua A, 123" in view.pickup_spot_details.value
    assert "01/12/2099 10:00 às 01/12/2099 18:00" in view.pickup_spot_details.value
    assert view.pickup_spot_edit_button.visible is False
    assert view.pickup_spot_delete_button.visible is False


def test_obsolete_pickup_spots_are_hidden_from_customers_but_manageable_by_owner():
    obsolete_spot = PickupSpot(
        id="centro",
        name="Loja do Centro",
        address="Rua A, 123",
        arrival_at=datetime(
            2020, 12, 1, 10, 0, tzinfo=ZoneInfo("America/Sao_Paulo")
        ),
        departure_at=datetime(
            2020, 12, 1, 18, 0, tzinfo=ZoneInfo("America/Sao_Paulo")
        ),
    )
    controller = PickupSpotController()
    controller.pickup_spots = [obsolete_spot]
    view = object.__new__(CatalogView)
    view.pickup_spot_controller = controller
    view.is_owner = False
    view.pickup_spot_dropdown = SimpleNamespace()
    view.pickup_spot_details = SimpleNamespace()
    view.pickup_spot_edit_button = SimpleNamespace()
    view.pickup_spot_delete_button = SimpleNamespace()
    view.reserve_button = SimpleNamespace()
    view.owner_reserve_button = SimpleNamespace()

    view.refresh_pickup_spot_options()

    assert view.pickup_spot_dropdown.options == []
    assert view.pickup_spot_dropdown.disabled is True
    assert view.pickup_spot_dropdown.hint_text == "Nenhum local de retirada disponível"

    view.is_owner = True
    controller.select_pickup_spot("centro", allow_unavailable=True)
    view.refresh_pickup_spot_options()

    assert len(view.pickup_spot_dropdown.options) == 1
    assert view.pickup_spot_dropdown.options[0].text.endswith("indisponível")
    assert view.pickup_spot_edit_button.visible is True
    assert view.pickup_spot_delete_button.visible is True


@pytest.mark.asyncio
async def test_catalog_view_builds_pickup_selector_with_owner_actions():
    pickup_controller = PickupSpotController()
    pickup_controller.pickup_spots = [
        PickupSpot(
            id="old",
            name="Local antigo",
            address="Rua A",
            arrival_at=datetime(
                2020, 12, 1, 10, 0, tzinfo=ZoneInfo("America/Sao_Paulo")
            ),
            departure_at=datetime(
                2020, 12, 1, 18, 0, tzinfo=ZoneInfo("America/Sao_Paulo")
            ),
        )
    ]
    page = SimpleNamespace(
        services=[],
        floating_action_button=None,
        update=Mock(),
    )
    view = CatalogView(
        page=page,
        controller=CatalogController(),
        pickup_spot_controller=pickup_controller,
        account_button=ft.Text("Conta"),
        on_reserve=AsyncMock(),
        on_add_stock=AsyncMock(),
        on_create_pickup_spot=AsyncMock(),
        on_edit_pickup_spot=AsyncMock(),
        on_delete_pickup_spot=AsyncMock(),
        on_create_item_type=AsyncMock(),
        on_update_item_type=AsyncMock(),
        on_delete_item_type=AsyncMock(),
        on_check_item_type_inventory=AsyncMock(),
        on_notice=Mock(),
        on_message=Mock(),
    )

    view.set_owner(True)
    assert view.production_button.visible is True
    assert page.floating_action_button is view.production_button
    assert view.pickup_spot_edit_button.visible is True
    assert view.pickup_spot_edit_button.disabled is True
    assert view.pickup_spot_delete_button.visible is True
    assert view.pickup_spot_delete_button.disabled is True

    pickup_controller.select_pickup_spot("old", allow_unavailable=True)
    view.refresh_pickup_spot_options()

    assert view.pickup_spot_dropdown.hint_text == "Selecione um local de retirada"
    assert view.pickup_spot_dropdown.options[0].text.endswith("indisponível")
    assert view.pickup_spot_edit_button.visible is True
    assert view.pickup_spot_edit_button.disabled is False
    assert view.pickup_spot_delete_button.visible is True
    assert view.pickup_spot_delete_button.disabled is False

    view.set_owner(False)
    assert view.production_button.visible is False
    assert page.floating_action_button is view.reserve_button

    await view.reserve_button.on_click(None)
    await view.owner_reserve_button.on_click(None)
    assert view.on_reserve.await_count == 2


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
async def test_production_form_submits_multiple_flavors_and_quantities():
    page = SimpleNamespace(
        show_dialog=Mock(),
        update=Mock(),
        pop_dialog=Mock(),
    )
    on_submit = AsyncMock(return_value=5)
    on_notice = Mock()
    view = ProductionFormView(
        page,
        on_submit=on_submit,
        on_notice=on_notice,
        on_message=Mock(),
    )
    view.open_form(
        [
            Cake("chocolate", "Chocolate", "Bolo", 0, "#F0E2D6"),
            Cake("strawberry", "Morango", "Bolo", 0, "#F3E4E6"),
        ]
    )
    view.entries[0].item_type.value = "chocolate"
    view.entries[0].quantity.value = "2"
    view._add_entry()
    view.entries[1].item_type.value = "strawberry"
    view.entries[1].quantity.value = "3"

    await view._submit()

    on_submit.assert_awaited_once_with({"chocolate": 2, "strawberry": 3})
    on_notice.assert_called_once_with("5 bolos adicionados ao estoque.")
    assert view.dialog is None




@pytest.mark.asyncio
@pytest.mark.parametrize("can_delete", [True, False])
async def test_edit_form_shows_delete_only_when_no_inventory_exists(can_delete):
    cake = Cake(
        "seasonal",
        "Sabor sazonal",
        "Bolo especial",
        0,
        "#F0E2D6",
        is_active=False,
    )
    view = object.__new__(CatalogView)
    view.on_check_item_type_inventory = AsyncMock(return_value=can_delete)
    view.on_message = lambda _: None
    view.page = SimpleNamespace(show_dialog=lambda _: None, update=Mock())

    await view._open_item_type_form(item_type=cake)

    assert view.item_type_is_active.value is False
    assert view.item_type_delete_button.visible is can_delete
    assert view.item_type_name.value == "Sabor sazonal"


@pytest.mark.asyncio
async def test_edit_button_opens_edit_form():
    shown_dialogs = []
    view = object.__new__(CatalogView)
    view.is_owner = True
    view.controller = SimpleNamespace(quantities={"chocolate": 0})
    view.on_check_item_type_inventory = AsyncMock(return_value=True)
    view.on_message = lambda _: None
    view.on_remove_stock = None
    view.page = SimpleNamespace(show_dialog=shown_dialogs.append, update=Mock())
    cake = Cake("chocolate", "Chocolate", "Bolo", 0, "#F0E2D6")

    card = view._cake_card(cake)
    edit_button = card.content.content.controls[0].content.controls[2].content

    assert inspect.iscoroutinefunction(edit_button.on_click)
    await edit_button.on_click(None)

    assert len(shown_dialogs) == 1
    assert shown_dialogs[0].title.value == "Editar sabor"


@pytest.mark.asyncio
async def test_edit_button_opens_form_if_inventory_check_fails():
    shown_dialogs = []
    view = object.__new__(CatalogView)
    view.is_owner = True
    view.controller = SimpleNamespace(quantities={"chocolate": 0})
    view.on_check_item_type_inventory = AsyncMock(
        side_effect=FirebaseRestError("Firestore indisponível", 503)
    )
    view.on_message = Mock()
    view.on_remove_stock = None
    view.page = SimpleNamespace(show_dialog=shown_dialogs.append, update=Mock())
    cake = Cake("chocolate", "Chocolate", "Bolo", 0, "#F0E2D6")

    card = view._cake_card(cake)
    edit_button = card.content.content.controls[0].content.controls[2].content
    await edit_button.on_click(None)

    assert len(shown_dialogs) == 1
    assert shown_dialogs[0].title.value == "Editar sabor"
    assert shown_dialogs[0].modal is False
    assert view.item_type_inventory_error.visible is True
    assert "Firestore indisponível" in view.item_type_inventory_error.value
    assert view.item_type_delete_button.visible is False
    view.on_message.assert_not_called()


@pytest.mark.asyncio
async def test_edit_form_opens_before_inventory_check_finishes():
    inventory_check = asyncio.Event()
    shown_dialogs = []
    view = object.__new__(CatalogView)
    view.is_owner = True
    view.controller = SimpleNamespace(quantities={"chocolate": 0})

    async def check_inventory(_item_type_id):
        await inventory_check.wait()
        return False

    view.on_check_item_type_inventory = check_inventory
    view.page = SimpleNamespace(show_dialog=shown_dialogs.append, update=Mock())
    cake = Cake("chocolate", "Chocolate", "Bolo", 0, "#F0E2D6")

    opening = asyncio.create_task(view._open_item_type_form(item_type=cake))
    await asyncio.sleep(0)

    assert len(shown_dialogs) == 1
    assert shown_dialogs[0].title.value == "Editar sabor"

    inventory_check.set()
    await opening

    assert view.item_type_delete_button.visible is False


@pytest.mark.asyncio
async def test_item_type_form_dismisses_outside_and_clears_edit_state():
    view = object.__new__(CatalogView)
    view.on_check_item_type_inventory = AsyncMock(return_value=True)
    view.page = SimpleNamespace(show_dialog=Mock(), update=Mock())
    cake = Cake("chocolate", "Chocolate", "Bolo", 0, "#F0E2D6")

    await view._open_item_type_form(item_type=cake)

    assert view.item_type_dialog.modal is False
    assert view.item_type_dialog.on_dismiss == view._on_item_type_form_dismiss
    view.item_type_dialog.on_dismiss(None)

    assert view.item_type_dialog is None
    assert view.editing_item_type is None


@pytest.mark.asyncio
async def test_registration_requires_name():
    controller = AuthController()
    controller.show_registration()

    with pytest.raises(FirebaseAuthError, match="Informe o nome"):
        await controller.submit(
            name="",
            email="maria@email.com",
            password="senha123",
        )


@pytest.mark.asyncio
async def test_submit_requires_api_key_configuration():
    controller = AuthController()
    controller.auth_client.api_key = ""

    with pytest.raises(FirebaseAuthError, match="Configure a variável FIREBASE_API_KEY"):
        await controller.submit(email="maria@email.com", password="senha123")


@pytest.mark.asyncio
async def test_successful_login_closes_form_before_showing_confirmation():
    events = []
    view = object.__new__(AuthView)
    view.controller = SimpleNamespace(
        submit=AsyncMock(return_value="Bem-vinda, Maria!")
    )
    view._name_field = None
    view._email_field = SimpleNamespace(value="maria@email.com")
    view._password_field = SimpleNamespace(value="senha123")
    view._submit_button = None
    view._form_error = None
    view.account_button_view = SimpleNamespace(
        refresh=lambda: events.append("refresh_account")
    )
    view.on_auth_changed = lambda: events.append("auth_changed")
    view.close = lambda: events.append("close_form")
    view.page = SimpleNamespace(update=lambda: events.append("update"))
    view.on_message = lambda message: events.append(("message", message))
    view.on_notice = lambda message: events.append(("notice", message))
    view.dialog = None
    view.root = SimpleNamespace(visible=False)

    await view._submit_form()

    assert events.index("close_form") < events.index(
        ("notice", "Login realizado com sucesso.")
    )
    assert not any(isinstance(event, tuple) and event[0] == "message" for event in events)
    assert "refresh_account" in events


@pytest.mark.asyncio
async def test_invalid_login_credentials_are_shown_inside_auth_form():
    messages = []
    view = object.__new__(AuthView)
    view.controller = SimpleNamespace(
        submit=AsyncMock(
            side_effect=FirebaseAuthError(
                "E-mail ou senha inválidos.",
                code="INVALID_LOGIN_CREDENTIALS",
            )
        )
    )
    view._name_field = None
    view._email_field = SimpleNamespace(value="maria@email.com")
    view._password_field = SimpleNamespace(value="senha-errada")
    view._submit_button = None
    view._form_error = ft.Text(visible=False)
    view.dialog = None
    view.root = SimpleNamespace(visible=False)
    view.page = SimpleNamespace(update=lambda: None)
    view.on_message = messages.append

    await view._submit_form()

    assert view._form_error.visible is True
    assert view._form_error.value == (
        "E-mail ou senha incorretos. Confira seus dados e tente novamente."
    )
    assert messages == []


def test_firebase_invalid_credentials_error_text_is_localized():
    assert FirebaseAuthClient._friendly_error("INVALID_LOGIN_CREDENTIALS") == (
        "E-mail ou senha inválidos."
    )


def test_logout_clears_user_and_firebase_tokens():
    controller = AuthController()
    controller.set_user("Maria", "maria@email.com", "user-abc")
    controller.id_token = "id-token"
    controller.refresh_token = "refresh-token"

    controller.logout()

    assert controller.is_authenticated is False
    assert controller.user_email is None
    assert controller.user_id is None
    assert controller.id_token is None
    assert controller.refresh_token is None


@pytest.mark.asyncio
async def test_logout_removes_persisted_session():
    view = object.__new__(AuthView)
    view.controller = SimpleNamespace(
        sign_out_provider=AsyncMock(),
        clear_persisted_session=AsyncMock(),
        logout=Mock(),
    )
    view.on_auth_changed = Mock()
    view.refresh_account_button = Mock()
    view.on_message = Mock()
    view.on_notice = Mock()

    await view._logout()

    view.controller.clear_persisted_session.assert_awaited_once()
    view.controller.logout.assert_called_once()
    view.on_notice.assert_called_once_with("Você saiu da sua conta.")
    view.on_message.assert_not_called()


def test_authenticated_account_button_offers_logout():
    controller = AuthController()
    controller.set_user("Maria")
    logout_calls = []
    account_button = AccountButtonView(
        controller,
        on_login=lambda: None,
        on_logout=lambda: logout_calls.append(True),
    )

    menu = account_button.button.content
    assert isinstance(menu, ft.PopupMenuButton)
    assert menu.items[0].content == "Sair"
    menu.items[0].on_click()
    assert logout_calls == [True]


def test_reopening_auth_view_after_registration_starts_at_login():
    controller = AuthController()
    controller.show_registration()
    dialogs = []
    view = object.__new__(AuthView)
    view.controller = controller
    view.page = SimpleNamespace(
        width=1024,
        show_dialog=lambda dialog: dialogs.append(dialog),
    )
    view.root = SimpleNamespace(visible=False)
    view.on_mobile_open = lambda: None
    view._desktop_content = lambda: ft.Text("login")
    view._on_dialog_dismiss = lambda _: None

    view.open()

    assert controller.is_registration is False
    assert len(dialogs) == 1


def _reservation_controller_with_available_item():
    controller = ReservationController()
    client = controller.firestore_client
    pickup_path = client._document_name("pickupSpots", "centro")
    item_type_path = client._document_name("itemTypes", "chocolate")
    now = datetime.now(timezone.utc)
    pickup_document = {
        "name": pickup_path,
        "fields": {
            "isActive": {"booleanValue": True},
            "name": {"stringValue": "Loja do Centro"},
            "address": {"stringValue": "Rua A, 123"},
            "arrivalAt": {
                "timestampValue": (now + timedelta(hours=1))
                .isoformat()
                .replace("+00:00", "Z")
            },
            "departureAt": {
                "timestampValue": (now + timedelta(hours=3))
                .isoformat()
                .replace("+00:00", "Z")
            },
        },
    }
    item_type_document = {
        "name": item_type_path,
        "fields": {
            "name": {"stringValue": "Chocolate"},
            "isActive": {"booleanValue": True},
            "regularPrice": {"doubleValue": 20.0},
            "promotionalPrice": {"doubleValue": 15.0},
        },
    }
    available_item = {
        "name": client._document_name("items", "unit-1"),
        "fields": {
            "itemTypeId": {"stringValue": "chocolate"},
            "itemTypeName": {"stringValue": "Chocolate"},
            "status": {"stringValue": "DISPONIVEL"},
        },
    }

    async def batch_get(document_names, *_):
        documents = (
            [pickup_document]
            if document_names == [pickup_path]
            else [item_type_document]
        )
        return [{"found": document} for document in documents]

    client.begin_transaction = AsyncMock(return_value="transaction")
    client.batch_get_in_transaction = AsyncMock(side_effect=batch_get)
    client.run_query_in_transaction = AsyncMock(
        return_value=[{"document": available_item}]
    )
    client.commit_transaction = AsyncMock(return_value={})
    client.rollback_transaction = AsyncMock()
    return controller, client












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
async def test_reserving_more_than_two_selected_units_creates_multiple_reservations():
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
            side_effect=[
                SimpleNamespace(total_amount=Decimal("30.00")),
                SimpleNamespace(total_amount=Decimal("15.00")),
            ]
        )
    )
    app.load_database_item_types = AsyncMock()
    app.show_notice = Mock()
    app.show_message = Mock()
    app.open_reservations = AsyncMock()

    await app.start_reservation()

    calls = app.reservation_controller.create_reservation.await_args_list
    assert [call.kwargs["quantities"] for call in calls] == [
        {"chocolate": 2},
        {"morango": 1},
    ]
    assert app.catalog_controller.quantities == {
        "chocolate": 0,
        "morango": 0,
    }
    app.show_notice.assert_called_once_with(
        "2 reservas criadas. Valor a pagar: R$ 45,00"
    )
    app.open_reservations.assert_awaited_once()
