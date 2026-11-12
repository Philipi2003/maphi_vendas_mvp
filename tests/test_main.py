import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

import flet as ft
import pytest

from features.auth.auth_logic import AuthController, FirebaseAuthClient, FirebaseAuthError
from features.auth.auth_view import AuthView
from features.auth.account_button_view import AccountButtonView
from features.catalog.catalog_logic import (
    Cake,
    CatalogController,
    ItemTypeImageCleanupError,
)
from features.catalog.catalog_view import CatalogView
from firebase_rest import (
    FirebaseFirestoreClient,
    FirebaseRestError,
    FirebaseStorageClient,
)


@pytest.mark.asyncio
async def test_login_success_sets_authenticated_user():
    controller = AuthController()
    controller.auth_client.sign_in = AsyncMock(
        return_value={
            "idToken": "token-123",
            "refreshToken": "refresh-123",
            "localId": "user-abc",
            "displayName": "Maria",
        }
    )
    controller.firestore_client.get_document = AsyncMock(
        return_value={"fields": {"role": {"stringValue": "CLIENTE"}}}
    )

    result = await controller.submit(email="maria@email.com", password="senha123")

    assert result == "Bem-vindo(a), Maria!"
    assert controller.user_name == "Maria"
    assert controller.user_email == "maria@email.com"
    assert controller.user_id == "user-abc"
    assert controller.id_token == "token-123"
    assert controller.refresh_token == "refresh-123"
    assert controller.is_authenticated is True
    assert controller.is_owner is False


@pytest.mark.asyncio
async def test_login_loads_owner_role_from_firestore_profile():
    controller = AuthController()
    controller.auth_client.sign_in = AsyncMock(
        return_value={
            "idToken": "owner-token",
            "refreshToken": "refresh-token",
            "localId": "owner-uid",
        }
    )
    controller.firestore_client.get_document = AsyncMock(
        return_value={
            "fields": {
                "name": {"stringValue": "Dona"},
                "role": {"stringValue": "DONO"},
            }
        }
    )

    await controller.submit(email="dona@email.com", password="senha123")

    assert controller.user_name == "Dona"
    assert controller.is_owner is True


@pytest.mark.asyncio
async def test_google_login_uses_firebase_session_and_loads_profile():
    controller = AuthController()
    controller.google_auth_client.sign_in = AsyncMock(
        return_value={
            "idToken": "google-firebase-token",
            "refreshToken": "google-refresh",
            "localId": "google-user",
            "email": "google@email.com",
            "displayName": "Google User",
        }
    )
    controller.firestore_client.get_document = AsyncMock(
        return_value={"fields": {"role": {"stringValue": "CLIENTE"}}}
    )

    await controller.submit_google()

    assert controller.user_name == "Google User"
    assert controller.user_email == "google@email.com"
    assert controller.user_id == "google-user"
    assert controller.id_token == "google-firebase-token"
    assert controller.auth_provider == "google"


@pytest.mark.asyncio
async def test_google_logout_signs_out_from_firebase_bridge():
    controller = AuthController()
    controller.auth_provider = "google"
    controller.google_auth_client.sign_out = AsyncMock()

    await controller.sign_out_provider()

    controller.google_auth_client.sign_out.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_item_type_persists_firestore_model_and_updates_catalog():
    controller = CatalogController(cakes=[])
    controller.firestore_client.create_document = AsyncMock(return_value={})
    controller.storage_client.upload_image = AsyncMock(
        return_value="https://example.com/chocolate.png"
    )

    cake = await controller.create_item_type(
        name="  Chocolate  ",
        description=" Bolo cremoso ",
        regular_price="45,00",
        promotional_price="39.90",
        is_custom_order_only=True,
        is_active=True,
        id_token="owner-token",
        user_id="owner-uid",
        image_data=b"photo",
        image_filename="chocolate.png",
        image_content_type="image/png",
    )

    assert cake.name == "Chocolate"
    assert cake.description == "Bolo cremoso"
    assert cake.stock == 0
    assert cake.is_custom_order_only is True
    assert cake.regular_price == 45.0
    assert cake.promotional_price == 39.9
    assert controller.cakes == [cake]
    saved_fields = controller.firestore_client.create_document.await_args.args[2]
    assert saved_fields["name"] == {"stringValue": "Chocolate"}
    assert saved_fields["description"] == {"stringValue": "Bolo cremoso"}
    assert saved_fields["imageUrl"] == {
        "stringValue": "https://example.com/chocolate.png"
    }
    assert saved_fields["regularPrice"] == {"doubleValue": 45.0}
    assert saved_fields["promotionalPrice"] == {"doubleValue": 39.9}
    assert saved_fields["isCustomOrderOnly"] == {"booleanValue": True}
    assert saved_fields["isActive"] == {"booleanValue": True}
    assert "timestampValue" in saved_fields["createdAt"]
    controller.storage_client.upload_image.assert_awaited_once()


@pytest.mark.asyncio
async def test_item_type_rejects_promotion_above_regular_price():
    controller = CatalogController(cakes=[])
    controller.firestore_client.create_document = AsyncMock(return_value={})

    with pytest.raises(ValueError, match="menor que o preço normal"):
        await controller.create_item_type(
            name="Chocolate",
            description="Bolo cremoso",
            regular_price="40",
            promotional_price="45",
            is_custom_order_only=False,
            is_active=True,
            id_token="owner-token",
            user_id="owner-uid",
        )

    controller.firestore_client.create_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_item_type_update_persists_activation_and_clears_old_promotion():
    existing = Cake(
        "chocolate",
        "Chocolate",
        "Bolo de chocolate",
        0,
        "#F0E2D6",
        regular_price=45.0,
        promotional_price=39.9,
    )
    controller = CatalogController(cakes=[existing])
    controller.firestore_client.update_document = AsyncMock(return_value={})
    controller.storage_client.delete_image = AsyncMock(return_value=True)

    updated = await controller.update_item_type(
        item_type_id="chocolate",
        name="Chocolate amargo",
        description="Bolo intenso",
        regular_price="50",
        promotional_price="",
        is_custom_order_only=False,
        is_active=False,
        id_token="owner-token",
        user_id="owner-uid",
    )

    assert updated.name == "Chocolate amargo"
    assert updated.is_active is False
    assert updated.promotional_price is None
    assert controller.cakes == [updated]
    saved_fields = controller.firestore_client.update_document.await_args.args[2]
    update_mask = controller.firestore_client.update_document.await_args.args[3]
    assert saved_fields["isActive"] == {"booleanValue": False}
    assert saved_fields["regularPrice"] == {"doubleValue": 50.0}
    assert "promotionalPrice" not in saved_fields
    assert "promotionalPrice" in update_mask
    controller.storage_client.delete_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_item_type_update_deletes_old_image_after_new_image_is_saved():
    old_image_url = (
        "https://firebasestorage.googleapis.com/v0/b/maphi-bucket/o/"
        "itemTypes%2Fowner-uid%2Fold.png?alt=media&token=old"
    )
    new_image_url = (
        "https://firebasestorage.googleapis.com/v0/b/maphi-bucket/o/"
        "itemTypes%2Fowner-uid%2Fnew.png?alt=media&token=new"
    )
    existing = Cake(
        "chocolate",
        "Chocolate",
        "Bolo",
        0,
        "#F0E2D6",
        image_url=old_image_url,
        regular_price=45.0,
    )
    events = []
    controller = CatalogController(cakes=[existing])
    controller.storage_client.upload_image = AsyncMock(
        side_effect=lambda *args: events.append("upload") or new_image_url
    )
    controller.firestore_client.update_document = AsyncMock(
        side_effect=lambda *args: events.append("save")
    )
    controller.storage_client.delete_image = AsyncMock(
        side_effect=lambda *args: events.append("delete") or True
    )

    updated = await controller.update_item_type(
        item_type_id="chocolate",
        name="Chocolate",
        description="Bolo",
        regular_price="45",
        promotional_price="",
        is_custom_order_only=False,
        is_active=True,
        id_token="owner-token",
        user_id="owner-uid",
        image_data=b"new photo",
        image_filename="new.png",
        image_content_type="image/png",
    )

    assert events == ["upload", "save", "delete"]
    assert updated.image_url == new_image_url
    controller.storage_client.delete_image.assert_awaited_once_with(
        old_image_url, "owner-token"
    )


@pytest.mark.asyncio
async def test_item_type_update_reports_old_image_cleanup_failure_after_save():
    old_image_url = (
        "https://firebasestorage.googleapis.com/v0/b/maphi-bucket/o/"
        "itemTypes%2Fowner-uid%2Fold.png?alt=media&token=old"
    )
    new_image_url = (
        "https://firebasestorage.googleapis.com/v0/b/maphi-bucket/o/"
        "itemTypes%2Fowner-uid%2Fnew.png?alt=media&token=new"
    )
    existing = Cake(
        "chocolate",
        "Chocolate",
        "Bolo",
        0,
        "#F0E2D6",
        image_url=old_image_url,
        regular_price=45.0,
    )
    controller = CatalogController(cakes=[existing])
    controller.storage_client.upload_image = AsyncMock(
        return_value=new_image_url
    )
    controller.firestore_client.update_document = AsyncMock(return_value={})
    controller.storage_client.delete_image = AsyncMock(
        side_effect=FirebaseRestError("Storage indisponível", 500)
    )

    with pytest.raises(ItemTypeImageCleanupError, match="sabor foi atualizado"):
        await controller.update_item_type(
            item_type_id="chocolate",
            name="Chocolate",
            description="Bolo",
            regular_price="45",
            promotional_price="",
            is_custom_order_only=False,
            is_active=True,
            id_token="owner-token",
            user_id="owner-uid",
            image_data=b"new photo",
            image_filename="new.png",
            image_content_type="image/png",
        )

    assert controller.cakes[0].image_url == new_image_url
    controller.firestore_client.update_document.assert_awaited_once()


@pytest.mark.asyncio
async def test_item_type_cannot_be_deleted_while_inventory_items_exist():
    cake = Cake(
        "chocolate",
        "Chocolate",
        "Bolo",
        0,
        "#F0E2D6",
        image_url=(
            "https://firebasestorage.googleapis.com/v0/b/maphi-bucket/o/"
            "itemTypes%2Fowner-uid%2Fchocolate.png?alt=media&token=token"
        ),
    )
    controller = CatalogController(cakes=[cake])
    controller.firestore_client.has_items_for_item_type = AsyncMock(
        return_value=True
    )
    controller.firestore_client.delete_document = AsyncMock()
    controller.storage_client.delete_image = AsyncMock(return_value=True)

    with pytest.raises(ValueError, match="há bolos associados"):
        await controller.delete_item_type("chocolate", "owner-token")

    controller.firestore_client.delete_document.assert_not_awaited()
    controller.storage_client.delete_image.assert_not_awaited()
    assert controller.cakes == [cake]

    controller.firestore_client.has_items_for_item_type.return_value = False
    await controller.delete_item_type("chocolate", "owner-token")

    controller.storage_client.delete_image.assert_awaited_once_with(
        cake.image_url, "owner-token"
    )
    controller.firestore_client.delete_document.assert_awaited_once_with(
        "itemTypes", "chocolate", "owner-token"
    )
    assert controller.cakes == []


@pytest.mark.asyncio
async def test_item_type_remains_when_storage_image_deletion_fails():
    cake = Cake(
        "chocolate",
        "Chocolate",
        "Bolo",
        0,
        "#F0E2D6",
        image_url=(
            "https://firebasestorage.googleapis.com/v0/b/maphi-bucket/o/"
            "itemTypes%2Fowner-uid%2Fchocolate.png?alt=media"
        ),
    )
    controller = CatalogController(cakes=[cake])
    controller.firestore_client.has_items_for_item_type = AsyncMock(
        return_value=False
    )
    controller.firestore_client.delete_document = AsyncMock()
    controller.storage_client.delete_image = AsyncMock(
        side_effect=RuntimeError("Storage indisponível")
    )

    with pytest.raises(RuntimeError, match="Storage indisponível"):
        await controller.delete_item_type("chocolate", "owner-token")

    controller.firestore_client.delete_document.assert_not_awaited()
    assert controller.cakes == [cake]


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
async def test_catalog_loads_saved_firestore_item_types():
    controller = CatalogController()
    assert controller.cakes == []

    controller.firestore_client.list_active_item_types = AsyncMock(
        return_value=[
            {
                "document": {
                    "name": "projects/maphi/databases/(default)/documents/itemTypes/chocolate",
                    "fields": {
                        "name": {"stringValue": "Chocolate"},
                        "description": {"stringValue": "Bolo de chocolate"},
                        "imageUrl": {"stringValue": "https://example.com/bolo.png"},
                        "isCustomOrderOnly": {"booleanValue": False},
                        "regularPrice": {"doubleValue": 45.0},
                        "promotionalPrice": {"doubleValue": 39.9},
                        "isActive": {"booleanValue": True},
                    },
                }
            }
        ]
    )

    await controller.load_item_types()

    assert len(controller.cakes) == 1
    assert controller.cakes[0].id == "chocolate"
    assert controller.cakes[0].name == "Chocolate"
    assert controller.cakes[0].image_url == "https://example.com/bolo.png"
    assert controller.cakes[0].regular_price == 45.0
    assert controller.cakes[0].promotional_price == 39.9
    assert controller.cakes[0].stock == 0

    controller.firestore_client.list_active_item_types = AsyncMock(return_value=[])
    await controller.load_item_types()

    assert controller.cakes == []
    assert controller.quantities == {}


@pytest.mark.asyncio
async def test_owner_catalog_includes_inactive_types_and_public_catalog_hides_them():
    controller = CatalogController()
    inactive_document = {
        "document": {
            "name": "projects/maphi/databases/(default)/documents/itemTypes/seasonal",
            "fields": {
                "name": {"stringValue": "Sabor sazonal"},
                "isActive": {"booleanValue": False},
            },
        }
    }
    controller.firestore_client.list_item_types = AsyncMock(
        return_value=[inactive_document]
    )
    controller.firestore_client.list_active_item_types = AsyncMock(
        return_value=[]
    )

    await controller.load_item_types(
        id_token="owner-token",
        include_inactive=True,
    )

    assert [cake.name for cake in controller.cakes] == ["Sabor sazonal"]
    assert controller.cakes[0].is_active is False
    controller.firestore_client.list_item_types.assert_awaited_once_with(
        "owner-token"
    )

    controller.hide_inactive_item_types()

    assert controller.cakes == []
    assert controller.quantities == {}


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
    view.page = SimpleNamespace(show_dialog=lambda _: None)

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
    view.page = SimpleNamespace(show_dialog=shown_dialogs.append)
    cake = Cake("chocolate", "Chocolate", "Bolo", 0, "#F0E2D6")

    card = view._cake_card(cake)
    edit_button = card.content.content.controls[0].content.controls[2].content

    assert inspect.iscoroutinefunction(edit_button.on_click)
    await edit_button.on_click(None)

    assert len(shown_dialogs) == 1
    assert shown_dialogs[0].title.value == "Editar sabor"


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
