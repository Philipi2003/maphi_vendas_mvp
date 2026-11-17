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
async def test_login_success_sets_authenticated_user():
    session_storage = SimpleNamespace(set=AsyncMock(return_value=True))
    controller = AuthController(session_storage=session_storage)
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
    session_storage.set.assert_awaited_once_with(
        controller.SESSION_STORAGE_KEY,
        json.dumps(
            {"refreshToken": "refresh-123", "provider": "password"},
            separators=(",", ":"),
        ),
    )


@pytest.mark.asyncio
async def test_restore_session_refreshes_token_and_loads_user_profile():
    session_storage = SimpleNamespace(
        get=AsyncMock(
            return_value=json.dumps(
                {"refreshToken": "old-refresh", "provider": "google"}
            )
        ),
        set=AsyncMock(return_value=True),
        remove=AsyncMock(return_value=True),
    )
    controller = AuthController(session_storage=session_storage)
    controller.auth_client.refresh_session = AsyncMock(
        return_value={
            "idToken": "new-id-token",
            "refreshToken": "rotated-refresh",
            "localId": "owner-uid",
        }
    )
    controller.auth_client.lookup_account = AsyncMock(
        return_value={
            "localId": "owner-uid",
            "email": "dona@email.com",
            "displayName": "Dona",
        }
    )
    controller.firestore_client.get_document = AsyncMock(
        return_value={"fields": {"role": {"stringValue": "DONO"}}}
    )

    restored = await controller.restore_session()

    assert restored is True
    assert controller.is_owner is True
    assert controller.id_token == "new-id-token"
    assert controller.refresh_token == "rotated-refresh"
    assert controller.auth_provider == "google"
    controller.auth_client.refresh_session.assert_awaited_once_with(
        "old-refresh"
    )
    session_storage.set.assert_awaited_once_with(
        controller.SESSION_STORAGE_KEY,
        json.dumps(
            {"refreshToken": "rotated-refresh", "provider": "google"},
            separators=(",", ":"),
        ),
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
    controller.firestore_client.list_items_for_item_type = AsyncMock(
        return_value=[
            {
                "document": {
                    "name": "projects/maphi/databases/(default)/documents/items/unit-1",
                    "fields": {
                        "itemTypeName": {"stringValue": "Chocolate"},
                    },
                }
            },
            {
                "document": {
                    "name": "projects/maphi/databases/(default)/documents/items/unit-2",
                    "fields": {
                        "itemTypeName": {"stringValue": "Chocolate"},
                    },
                }
            },
        ]
    )
    controller.firestore_client.update_documents_atomically = AsyncMock(
        return_value={}
    )
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
    controller.firestore_client.update_documents_atomically.assert_awaited_once_with(
        "items",
        [
            (
                "unit-1",
                {"itemTypeName": {"stringValue": "Chocolate amargo"}},
            ),
            (
                "unit-2",
                {"itemTypeName": {"stringValue": "Chocolate amargo"}},
            ),
        ],
        ["itemTypeName"],
        "owner-token",
    )
    controller.storage_client.delete_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_item_type_update_reports_inventory_name_sync_failure():
    existing = Cake(
        "chocolate", "Chocolate", "Bolo", 1, "#F0E2D6"
    )
    controller = CatalogController(cakes=[existing])
    controller.firestore_client.update_document = AsyncMock(return_value={})
    controller.firestore_client.list_items_for_item_type = AsyncMock(
        return_value=[
            {
                "document": {
                    "name": "projects/maphi/databases/(default)/documents/items/unit-1",
                    "fields": {
                        "itemTypeName": {"stringValue": "Chocolate"},
                    },
                }
            }
        ]
    )
    controller.firestore_client.update_documents_atomically = AsyncMock(
        side_effect=FirebaseRestError("Firestore indisponível", 503)
    )

    with pytest.raises(ItemTypeNameSyncError, match="O sabor foi atualizado"):
        await controller.update_item_type(
            item_type_id="chocolate",
            name="Chocolate amargo",
            description="Bolo",
            regular_price="45",
            promotional_price="",
            is_custom_order_only=False,
            is_active=True,
            id_token="owner-token",
            user_id="owner-uid",
        )

    assert controller.cakes[0].name == "Chocolate amargo"


@pytest.mark.asyncio
async def test_item_type_name_sync_splits_large_inventory_into_batches():
    existing = Cake("chocolate", "Chocolate", "Bolo", 501, "#F0E2D6")
    controller = CatalogController(cakes=[existing])
    controller.firestore_client.update_document = AsyncMock(return_value={})
    controller.firestore_client.list_items_for_item_type = AsyncMock(
        return_value=[
            {
                "document": {
                    "name": (
                        "projects/maphi/databases/(default)/documents/"
                        f"items/unit-{index}"
                    ),
                    "fields": {
                        "itemTypeName": {"stringValue": "Chocolate"},
                    },
                }
            }
            for index in range(501)
        ]
    )
    controller.firestore_client.update_documents_atomically = AsyncMock(
        return_value={}
    )

    await controller.update_item_type(
        item_type_id="chocolate",
        name="Chocolate amargo",
        description="Bolo",
        regular_price="45",
        promotional_price="",
        is_custom_order_only=False,
        is_active=True,
        id_token="owner-token",
        user_id="owner-uid",
    )

    batches = (
        controller.firestore_client.update_documents_atomically.await_args_list
    )
    assert [len(call.args[1]) for call in batches] == [500, 1]


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
    controller.firestore_client.list_items_for_item_type = AsyncMock(
        return_value=[]
    )
    controller.firestore_client.update_documents_atomically = AsyncMock(
        return_value={}
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
    controller.firestore_client.list_items_for_item_type = AsyncMock(
        return_value=[]
    )
    controller.firestore_client.update_documents_atomically = AsyncMock(
        return_value={}
    )
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


@pytest.mark.asyncio
async def test_pickup_spots_load_and_selected_location_state():
    controller = PickupSpotController()
    controller.firestore_client.list_pickup_spots = AsyncMock(
        return_value=[
            {
                "document": {
                    "name": "projects/maphi/databases/(default)/documents/pickupSpots/centro",
                    "fields": {
                        "name": {"stringValue": "Loja do Centro"},
                        "address": {"stringValue": "Rua A, 123"},
                        "arrivalAt": {
                            "timestampValue": "2099-12-01T13:00:00Z"
                        },
                        "departureAt": {
                            "timestampValue": "2099-12-01T21:00:00Z"
                        },
                    },
                }
            }
        ]
    )

    await controller.load_active_pickup_spots()
    controller.firestore_client.list_pickup_spots.assert_awaited_once_with(
        include_inactive=False, id_token=None
    )
    controller.select_pickup_spot("centro")

    assert controller.selected_pickup_spot_id == "centro"
    assert controller.selected_pickup_spot == PickupSpot(
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

    controller.firestore_client.list_pickup_spots.return_value = []
    await controller.load_active_pickup_spots()

    assert controller.pickup_spots == []
    assert controller.selected_pickup_spot_id is None


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


@pytest.mark.asyncio
async def test_pickup_spot_creation_persists_normalized_fields():
    controller = PickupSpotController()
    controller.firestore_client.create_pickup_spot = AsyncMock(return_value={})

    pickup_spot = await controller.create_pickup_spot(
        name="  Loja do Centro ",
        address=" Rua A, 123 ",
        arrival_at="15/11/2026 09:30",
        departure_at="15/11/2026 17:45",
        id_token="owner-token",
    )

    assert pickup_spot.name == "Loja do Centro"
    assert pickup_spot.address == "Rua A, 123"
    assert pickup_spot.arrival_at == datetime(
        2026, 11, 15, 9, 30, tzinfo=ZoneInfo("America/Sao_Paulo")
    )
    assert pickup_spot.departure_at == datetime(
        2026, 11, 15, 17, 45, tzinfo=ZoneInfo("America/Sao_Paulo")
    )
    assert pickup_spot.is_active is True
    fields = controller.firestore_client.create_pickup_spot.await_args.args[1]
    assert fields["name"] == {"stringValue": "Loja do Centro"}
    assert fields["address"] == {"stringValue": "Rua A, 123"}
    assert fields["arrivalAt"] == {
        "timestampValue": "2026-11-15T12:30:00Z"
    }
    assert fields["departureAt"] == {
        "timestampValue": "2026-11-15T20:45:00Z"
    }
    assert fields["isActive"] == {"booleanValue": True}
    assert "timestampValue" in fields["createdAt"]
    assert controller.firestore_client.create_pickup_spot.await_args.args[2] == (
        "owner-token"
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
@pytest.mark.parametrize(
    ("name", "address", "arrival_at", "departure_at", "message"),
    [
        (" ", "Rua A, 123", "15/11/2026 09:00", "15/11/2026 17:00", "nome"),
        ("Centro", " ", "15/11/2026 09:00", "15/11/2026 17:00", "endereço"),
        ("Centro", "Rua A, 123", "15/11/2026 9h", "15/11/2026 17:00", "chegada"),
        ("Centro", "Rua A, 123", "15/11/2026 09:00", "15/11/2026 17h", "saída"),
        ("Centro", "Rua A, 123", "15/11/2026 18:00", "15/11/2026 17:00", "posterior"),
        ("Centro", "Rua A, 123", "15/11/2026 09:00", "15/11/2026 09:10", "15 minutos"),
    ],
)
async def test_pickup_spot_creation_requires_all_reservation_details(
    name, address, arrival_at, departure_at, message
):
    controller = PickupSpotController()
    controller.firestore_client.create_pickup_spot = AsyncMock()

    with pytest.raises(ValueError, match=message):
        await controller.create_pickup_spot(
            name=name,
            address=address,
            arrival_at=arrival_at,
            departure_at=departure_at,
            id_token="owner-token",
        )

    controller.firestore_client.create_pickup_spot.assert_not_awaited()


@pytest.mark.asyncio
async def test_pickup_spot_update_and_delete_preserve_selection_state():
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
    controller.firestore_client.update_document = AsyncMock(return_value={})
    controller.firestore_client.delete_document = AsyncMock(return_value={})

    updated = await controller.update_pickup_spot(
        pickup_spot_id="centro",
        name="Loja Central",
        address="Rua B, 456",
        arrival_at="02/12/2099 11:00",
        departure_at="02/12/2099 19:00",
        id_token="owner-token",
    )

    assert updated.name == "Loja Central"
    assert updated.arrival_at == datetime(
        2099, 12, 2, 11, 0, tzinfo=ZoneInfo("America/Sao_Paulo")
    )
    assert controller.selected_pickup_spot_id == "centro"
    saved_fields = controller.firestore_client.update_document.await_args.args[2]
    assert saved_fields["arrivalAt"] == {
        "timestampValue": "2099-12-02T14:00:00Z"
    }

    await controller.delete_pickup_spot("centro", "owner-token")

    controller.firestore_client.delete_document.assert_awaited_once_with(
        "pickupSpots", "centro", "owner-token"
    )
    assert controller.pickup_spots == []
    assert controller.selected_pickup_spot_id is None


@pytest.mark.asyncio
async def test_editing_inactive_pickup_spot_does_not_reactivate_it():
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
        is_active=False,
    )
    controller = PickupSpotController()
    controller.pickup_spots = [pickup_spot]
    controller.firestore_client.update_document = AsyncMock(return_value={})

    updated = await controller.update_pickup_spot(
        pickup_spot_id="centro",
        name="Loja Central",
        address="Rua B, 456",
        arrival_at="02/12/2099 11:00",
        departure_at="02/12/2099 19:00",
        id_token="owner-token",
    )

    assert updated.is_active is False
    fields = controller.firestore_client.update_document.await_args.args[2]
    assert fields["isActive"] == {"booleanValue": False}


@pytest.mark.asyncio
async def test_catalog_loads_saved_firestore_item_types():
    controller = CatalogController()
    assert controller.cakes == []
    controller.firestore_client.list_available_items = AsyncMock(
        return_value=[
            {
                "document": {
                    "fields": {
                        "itemTypeId": {"stringValue": "chocolate"},
                        "status": {"stringValue": "DISPONIVEL"},
                    }
                }
            },
            {
                "document": {
                    "fields": {
                        "itemTypeId": {"stringValue": "chocolate"},
                        "status": {"stringValue": "DISPONIVEL"},
                    }
                }
            },
            {
                "document": {
                    "fields": {
                        "itemTypeId": {"stringValue": "chocolate"},
                        "status": {"stringValue": "RESERVADO"},
                    }
                }
            },
        ]
    )

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
    assert controller.cakes[0].stock == 2

    controller.firestore_client.list_active_item_types = AsyncMock(return_value=[])
    controller.firestore_client.list_available_items.return_value = []
    await controller.load_item_types()

    assert controller.cakes == []
    assert controller.quantities == {}


@pytest.mark.asyncio
async def test_production_adds_multiple_units_across_flavors_atomically():
    chocolate = Cake(
        "chocolate", "Chocolate", "Bolo de chocolate", 3, "#F0E2D6"
    )
    strawberry = Cake(
        "strawberry", "Morango", "Bolo de morango", 1, "#F3E4E6"
    )
    controller = CatalogController(cakes=[chocolate, strawberry])
    controller.firestore_client.create_documents_atomically = AsyncMock(
        return_value={}
    )

    total = await controller.add_stock(
        {"chocolate": 2, "strawberry": 3},
        "owner-token",
    )

    assert total == 5
    assert {cake.id: cake.stock for cake in controller.cakes} == {
        "chocolate": 5,
        "strawberry": 4,
    }
    collection, documents, token = (
        controller.firestore_client.create_documents_atomically.await_args.args
    )
    assert collection == "items"
    assert token == "owner-token"
    assert len(documents) == 5
    assert [
        fields["itemTypeId"]["stringValue"] for _, fields in documents
    ].count("chocolate") == 2
    assert [
        fields["itemTypeId"]["stringValue"] for _, fields in documents
    ].count("strawberry") == 3
    assert all(
        fields["status"] == {"stringValue": "DISPONIVEL"}
        and "timestampValue" in fields["createdAt"]
        for _, fields in documents
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("quantities", "message"),
    [
        ({"chocolate": 0}, "inteiro positivo"),
        ({"chocolate": -1}, "inteiro positivo"),
        ({"chocolate": 501}, "no máximo 500"),
        ({"missing": 1}, "não existe mais"),
    ],
)
async def test_production_rejects_invalid_additions(quantities, message):
    controller = CatalogController(
        cakes=[Cake("chocolate", "Chocolate", "Bolo", 0, "#F0E2D6")]
    )
    controller.firestore_client.create_documents_atomically = AsyncMock()

    with pytest.raises(ValueError, match=message):
        await controller.add_stock(quantities, "owner-token")

    controller.firestore_client.create_documents_atomically.assert_not_awaited()
    assert controller.cakes[0].stock == 0


@pytest.mark.asyncio
async def test_production_keeps_local_stock_when_firestore_batch_fails():
    controller = CatalogController(
        cakes=[Cake("chocolate", "Chocolate", "Bolo", 4, "#F0E2D6")]
    )
    controller.firestore_client.create_documents_atomically = AsyncMock(
        side_effect=FirebaseRestError("Firestore indisponível", 503)
    )

    with pytest.raises(FirebaseRestError, match="Firestore indisponível"):
        await controller.add_stock({"chocolate": 2}, "owner-token")

    assert controller.cakes[0].stock == 4


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
    controller.firestore_client.list_available_items = AsyncMock(
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
async def test_customer_reservation_atomically_allocates_stock_and_snapshots_price():
    controller, client = _reservation_controller_with_available_item()

    reservation = await controller.create_reservation(
        quantities={"chocolate": 1},
        pickup_spot_id="centro",
        user_id="customer-1",
        user_name="Maria",
        is_owner=False,
        id_token="customer-token",
    )

    writes = client.commit_transaction.await_args.args[0]
    assert reservation.total_amount == Decimal("15.00")
    assert reservation.item_ids == ("unit-1",)
    assert reservation.status == "ATIVA"
    assert len(writes) == 2
    assert writes[0]["update"]["fields"]["status"] == {
        "stringValue": "RESERVADO"
    }
    reservation_fields = writes[1]["update"]["fields"]
    assert reservation_fields["saleType"] == {"stringValue": "PROMOCAO"}
    assert reservation_fields["userId"] == {"stringValue": "customer-1"}
    assert reservation_fields["totalAmount"] == {"doubleValue": 15.0}
    client.run_query_in_transaction.assert_awaited_once()
    query = client.run_query_in_transaction.await_args.args[0]
    assert query["from"] == [{"collectionId": "items"}]
    assert query["limit"] == 1
    assert {
        condition["fieldFilter"]["field"]["fieldPath"]
        for condition in query["where"]["compositeFilter"]["filters"]
    } == {"itemTypeId", "status"}


@pytest.mark.asyncio
async def test_owner_reservation_uses_regular_price_for_in_person_sale():
    controller, client = _reservation_controller_with_available_item()

    reservation = await controller.create_reservation(
        quantities={"chocolate": 1},
        pickup_spot_id="centro",
        user_id="owner-1",
        user_name="Dona",
        is_owner=True,
        id_token="owner-token",
    )

    assert reservation.total_amount == Decimal("20.00")
    assert reservation.sale_type == "NORMAL"
    item_write = client.commit_transaction.await_args.args[0][0]
    assert item_write["update"]["fields"]["reservedPrice"] == {
        "doubleValue": 20.0
    }


@pytest.mark.asyncio
async def test_reservation_rejects_insufficient_stock_without_committing():
    controller, client = _reservation_controller_with_available_item()
    client.run_query_in_transaction.return_value = []

    with pytest.raises(ReservationError, match="O estoque mudou"):
        await controller.create_reservation(
            quantities={"chocolate": 1},
            pickup_spot_id="centro",
            user_id="customer-1",
            user_name="Maria",
            is_owner=False,
            id_token="customer-token",
        )

    client.commit_transaction.assert_not_awaited()
    client.rollback_transaction.assert_awaited_once()


@pytest.mark.asyncio
async def test_reservation_retries_transaction_conflicts():
    controller, client = _reservation_controller_with_available_item()
    client.begin_transaction = AsyncMock(
        side_effect=["transaction-1", "transaction-2"]
    )
    client.commit_transaction = AsyncMock(
        side_effect=[FirebaseRestError("ABORTED", 409), {}]
    )

    await controller.create_reservation(
        quantities={"chocolate": 1},
        pickup_spot_id="centro",
        user_id="customer-1",
        user_name="Maria",
        is_owner=False,
        id_token="customer-token",
    )

    assert client.begin_transaction.await_count == 2
    assert client.commit_transaction.await_count == 2
    client.rollback_transaction.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_cancellation_releases_stock_and_records_cancellation_origin():
    controller = ReservationController()
    client = controller.firestore_client
    reservation_path = client._document_name("reservations", "reservation-1")
    item_path = client._document_name("items", "unit-1")
    reservation_document = {
        "name": reservation_path,
        "fields": {
            "status": {"stringValue": "ATIVA"},
            "userId": {"stringValue": "customer-1"},
            "itemIds": {
                "arrayValue": {
                    "values": [{"stringValue": "unit-1"}]
                }
            },
        },
    }
    item_document = {
        "name": item_path,
        "fields": {
            "status": {"stringValue": "RESERVADO"},
            "reservationId": {"stringValue": "reservation-1"},
        },
    }

    async def batch_get(document_names, *_):
        document = (
            reservation_document
            if document_names == [reservation_path]
            else item_document
        )
        return [{"found": document}]

    client.begin_transaction = AsyncMock(return_value="transaction")
    client.batch_get_in_transaction = AsyncMock(side_effect=batch_get)
    client.commit_transaction = AsyncMock(return_value={})
    client.rollback_transaction = AsyncMock()

    await controller.cancel_reservation(
        "reservation-1",
        user_id="owner-1",
        id_token="owner-token",
        is_owner=True,
    )

    item_write, reservation_write = client.commit_transaction.await_args.args[0]
    assert item_write["update"]["fields"]["status"] == {
        "stringValue": "DISPONIVEL"
    }
    assert item_write["updateMask"]["fieldPaths"] == [
        "status",
        "reservationId",
        "reservedPrice",
    ]
    assert reservation_write["update"]["fields"]["cancelledBy"] == {
        "stringValue": "DONO"
    }
    assert reservation_write["update"]["fields"]["status"] == {
        "stringValue": "CANCELADA"
    }


@pytest.mark.asyncio
async def test_deleting_pickup_spot_cancels_reservations_before_deleting_spot():
    events = []

    def record_cancellation(pickup_spot_id, *, owner_id, id_token):
        assert pickup_spot_id == "spot-1"
        assert owner_id == "owner-1"
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
        owner_id="owner-1",
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
            side_effect=FirebaseRestError("Firestore indisponível", 503)
        )
    )

    with pytest.raises(FirebaseRestError, match="Firestore indisponível"):
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


@pytest.mark.asyncio
async def test_owner_removes_only_one_available_inventory_unit():
    cake = Cake("chocolate", "Chocolate", "Bolo", 2, "#F0E2D6")
    controller = CatalogController([cake])
    client = controller.firestore_client
    available_item = {
        "name": client._document_name("items", "unit-1"),
        "fields": {
            "itemTypeId": {"stringValue": "chocolate"},
            "status": {"stringValue": "DISPONIVEL"},
        },
    }
    client.begin_transaction = AsyncMock(return_value="transaction")
    client.run_query_in_transaction = AsyncMock(
        return_value=[{"document": available_item}]
    )
    client.commit_transaction = AsyncMock(return_value={})
    client.rollback_transaction = AsyncMock()

    await controller.remove_available_unit("chocolate", "owner-token")

    writes = client.commit_transaction.await_args.args[0]
    query = client.run_query_in_transaction.await_args.args[0]
    assert writes == [{"delete": available_item["name"]}]
    assert query["limit"] == 1
    assert controller.cakes[0].stock == 1


@pytest.mark.asyncio
async def test_owner_cannot_remove_reserved_inventory_unit():
    controller = CatalogController(
        [Cake("chocolate", "Chocolate", "Bolo", 0, "#F0E2D6")]
    )
    client = controller.firestore_client
    client.begin_transaction = AsyncMock(return_value="transaction")
    client.run_query_in_transaction = AsyncMock(return_value=[])
    client.commit_transaction = AsyncMock()
    client.rollback_transaction = AsyncMock()

    with pytest.raises(ValueError, match="Não há unidades não reservadas"):
        await controller.remove_available_unit("chocolate", "owner-token")

    client.commit_transaction.assert_not_awaited()
    client.rollback_transaction.assert_awaited_once()
