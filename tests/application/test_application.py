from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from application import MaphiApplication


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
