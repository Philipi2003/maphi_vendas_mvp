import asyncio
from datetime import datetime
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import flet as ft
import pytest

from features.catalog.catalog_api import CatalogApiError, parse_catalog_response
from features.catalog.catalog_logic import Cake, CatalogController
from features.catalog.catalog_view import CatalogView
from features.pickup_spots.pickup_spots_logic import PickupSpot, PickupSpotController
from firebase_rest import FirebaseRestError


def test_parse_catalog_response_maps_database_fields():
    cakes = parse_catalog_response(
        {
            "items": [
                {
                    "id": "cake-1",
                    "name": "  Brigadeiro ",
                    "description": None,
                    "image_url": " https://example.com/cake.jpg ",
                    "stock": 2,
                }
            ]
        }
    )

    assert cakes == [
        Cake(
            id="cake-1",
            name="Brigadeiro",
            description="",
            stock=2,
            color="#F0E2D6",
            image_url="https://example.com/cake.jpg",
        )
    ]


@pytest.mark.parametrize("stock", [True, -1, "2"])
def test_parse_catalog_response_rejects_invalid_stock(stock):
    with pytest.raises(CatalogApiError):
        parse_catalog_response(
            {
                "items": [
                    {
                        "id": "cake-1",
                        "name": "Brigadeiro",
                        "description": "",
                        "image_url": None,
                        "stock": stock,
                    }
                ]
            }
        )


def test_controller_replaces_cakes_and_clamps_existing_selection():
    controller = CatalogController(
        [Cake("cake-1", "Brigadeiro", "", 4, "#F0E2D6")]
    )
    controller.change_quantity("cake-1", 3)

    controller.set_cakes([Cake("cake-1", "Brigadeiro", "", 2, "#F0E2D6")])

    assert controller.quantities == {"cake-1": 2}
    assert controller.selected_count == 2


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


@pytest.mark.parametrize("width", [390, 768, 1280])
def test_pickup_selector_uses_responsive_surface_and_selects_location(width):
    pickup_controller = PickupSpotController()
    pickup_controller.pickup_spots = [
        PickupSpot(
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
    ]
    page = SimpleNamespace(
        width=width,
        height=800,
        services=[],
        floating_action_button=None,
        show_dialog=Mock(),
        pop_dialog=Mock(),
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

    view.pickup_spot_selector_button.on_click(None)

    sheet = page.show_dialog.call_args.args[0]
    if width < 768:
        assert isinstance(sheet, ft.BottomSheet)
        options = sheet.content.content.content.controls[2]
    else:
        assert isinstance(sheet, ft.AlertDialog)
        options = sheet.content.content.controls[1]
    assert isinstance(options, ft.ListView)
    options.controls[0].on_click(None)

    assert pickup_controller.selected_pickup_spot_id == "centro"
    page.pop_dialog.assert_called_once()


@pytest.mark.asyncio
async def test_mobile_item_type_form_uses_fullscreen_bottom_sheet():
    view = object.__new__(CatalogView)
    view.on_message = Mock()
    view.page = SimpleNamespace(
        width=390,
        show_dialog=Mock(),
        update=Mock(),
    )

    await view._open_item_type_form()

    assert isinstance(view.item_type_dialog, ft.BottomSheet)
    assert view.item_type_dialog.fullscreen is True


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
