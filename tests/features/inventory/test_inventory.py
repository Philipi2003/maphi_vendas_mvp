from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import flet as ft
import pytest

from features.catalog.catalog_card_view import CatalogCardView
from features.catalog.catalog_logic import Cake, CatalogController
from features.catalog.catalog_view import CatalogView
from features.inventory.production_view import ProductionFormView
from maphi_api import MaphiApiClient


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


def test_mobile_production_form_uses_fullscreen_sheet_and_stacked_entries():
    page = SimpleNamespace(
        width=390,
        show_dialog=Mock(),
        update=Mock(),
    )
    view = ProductionFormView(
        page,
        on_submit=AsyncMock(),
        on_notice=Mock(),
        on_message=Mock(),
    )

    view.open_form([Cake("chocolate", "Chocolate", "Bolo", 0, "#F0E2D6")])

    assert isinstance(view.dialog, ft.BottomSheet)
    assert view.dialog.fullscreen is True
    assert isinstance(view.entries[0].control, ft.Column)


@pytest.mark.asyncio
async def test_remove_stock_confirmation_shows_reserved_count_and_cancellation_guidance():
    shown_dialogs = []
    view = object.__new__(CatalogView)
    view.is_owner = True
    view.on_remove_stock = AsyncMock(return_value=2)
    view.on_notice = Mock()
    view.on_message = Mock()
    view.refresh = Mock()
    view.page = SimpleNamespace(
        show_dialog=shown_dialogs.append,
        pop_dialog=Mock(),
        update=Mock(),
    )

    await view._ask_remove_stock(
        Cake(
            "chocolate",
            "Chocolate",
            "Bolo",
            3,
            "#F0E2D6",
            reserved_stock=2,
        )
    )

    dialog = shown_dialogs[0]
    content = dialog.content.controls[0].value
    quantity_field = dialog.content.controls[1]
    assert "3 unidades não reservadas" in content
    assert "2 unidades reservadas" in content
    assert "cancele primeiro uma reserva" in content
    quantity_field.value = "4"
    await dialog.actions[1].on_click(None)
    assert dialog.content.controls[2].visible
    assert "Há somente 3 unidades não reservadas" in dialog.content.controls[2].value
    view.on_remove_stock.assert_not_awaited()

    quantity_field.value = "2"
    await dialog.actions[1].on_click(None)
    view.on_remove_stock.assert_awaited_once_with("chocolate", 2)
    view.on_notice.assert_called_once_with(
        "2 unidades não reservadas removidas do estoque."
    )


def test_remove_stock_button_is_disabled_when_all_units_are_reserved():
    view = CatalogCardView(
        Cake(
            "chocolate",
            "Chocolate",
            "Bolo",
            0,
            "#F0E2D6",
            reserved_stock=2,
        ),
        quantity=0,
        is_owner=True,
        on_quantity_change=lambda _: None,
        on_remove_stock=AsyncMock(),
    )

    card = view.build()
    footer = card.content.content.controls[-1]
    remove_button = next(
        control
        for control in footer.controls
        if isinstance(control, ft.TextButton)
    )

    assert remove_button.disabled
    assert "Reservados: 2" in footer.controls[-1].value
    assert "cancele uma reserva" in footer.controls[-1].value


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
