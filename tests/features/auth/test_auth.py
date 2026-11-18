import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import flet as ft
import pytest

from features.auth.account_button_view import AccountButtonView
from features.auth.auth_logic import (
    AuthController,
    FirebaseAuthClient,
    FirebaseAuthError,
)
from features.auth.auth_view import AuthView
from features.catalog.catalog_logic import CatalogController
from features.catalog.catalog_view import CatalogView
from features.pickup_spots.pickup_spots_logic import PickupSpotController


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
async def test_google_logout_signs_out_from_firebase_bridge():
    controller = AuthController()
    controller.auth_provider = "google"
    controller.google_auth_client.sign_out = AsyncMock()

    await controller.sign_out_provider()

    controller.google_auth_client.sign_out.assert_awaited_once()


def test_mobile_header_places_account_actions_on_a_separate_row():
    page = SimpleNamespace(
        width=390,
        services=[],
        floating_action_button=None,
        update=Mock(),
    )
    view = CatalogView(
        page=page,
        controller=CatalogController(),
        pickup_spot_controller=PickupSpotController(),
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

    header = view.root.content.controls[0]
    assert isinstance(header.content, ft.ResponsiveRow)
    assert [control.col["xs"] for control in header.content.controls] == [12, 12]
    assert (
        view.root.content.horizontal_alignment
        == ft.CrossAxisAlignment.STRETCH
    )


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
