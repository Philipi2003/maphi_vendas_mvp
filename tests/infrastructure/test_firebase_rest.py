from unittest.mock import AsyncMock

import pytest

from firebase_rest import FirebaseFirestoreClient, FirebaseStorageClient


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
