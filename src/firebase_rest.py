import asyncio
import json
import urllib.error
import urllib.request
from urllib.parse import quote, unquote, urlencode, urlsplit

from app_config import FIREBASE_API_KEY, PROJECT_ID, STORAGE_BUCKET

MAX_FIRESTORE_BATCH_WRITES = 500


class FirebaseRestError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class FirebaseFirestoreClient:
    def __init__(self, project_id: str | None = None):
        self.project_id = project_id or PROJECT_ID
        self.api_key = FIREBASE_API_KEY

    def _documents_resource(self) -> str:
        if not self.project_id:
            raise FirebaseRestError("Configure PROJECT_ID para acessar o Firestore.")
        return f"projects/{self.project_id}/databases/(default)/documents"

    def _documents_url(self) -> str:
        return (
            "https://firestore.googleapis.com/v1/"
            f"{self._documents_resource()}"
        )

    def _document_url(self, collection: str, document_id: str | None = None) -> str:
        path = f"{self._documents_url()}/{collection}"
        if document_id:
            path = f"{path}/{document_id}"
        return path

    def _document_name(self, collection: str, document_id: str) -> str:
        return self.document_name(collection, document_id)

    def document_name(self, collection: str, document_id: str) -> str:
        return f"{self._documents_resource()}/{collection}/{document_id}"

    async def get_document(
        self, collection: str, document_id: str, id_token: str
    ) -> dict:
        return await self._request(
            self._document_url(collection, document_id), id_token=id_token
        )

    async def create_document(
        self,
        collection: str,
        document_id: str,
        fields: dict,
        id_token: str,
    ) -> dict:
        return await self._request(
            f"{self._document_url(collection)}?documentId={document_id}",
            id_token=id_token,
            method="POST",
            payload={"fields": fields},
        )

    async def create_documents_atomically(
        self,
        collection: str,
        documents: list[tuple[str, dict]],
        id_token: str,
    ) -> dict:
        if not documents:
            raise ValueError("Informe ao menos um documento para criar.")
        if len(documents) > MAX_FIRESTORE_BATCH_WRITES:
            raise ValueError(
                f"Cada lote pode conter no máximo {MAX_FIRESTORE_BATCH_WRITES} gravações."
            )
        writes = [
            {
                "update": {
                    "name": self._document_name(collection, document_id),
                    "fields": fields,
                },
                "currentDocument": {"exists": False},
            }
            for document_id, fields in documents
        ]
        return await self._request(
            f"{self._documents_url()}:commit",
            id_token=id_token,
            method="POST",
            payload={"writes": writes},
        )

    async def update_documents_atomically(
        self,
        collection: str,
        documents: list[tuple[str, dict]],
        field_paths: list[str],
        id_token: str,
    ) -> dict:
        if not documents:
            return {}
        if len(documents) > MAX_FIRESTORE_BATCH_WRITES:
            raise ValueError(
                f"Cada lote pode conter no máximo {MAX_FIRESTORE_BATCH_WRITES} gravações."
            )
        writes = [
            {
                "update": {
                    "name": self._document_name(collection, document_id),
                    "fields": fields,
                },
                "updateMask": {"fieldPaths": field_paths},
            }
            for document_id, fields in documents
        ]
        return await self._request(
            f"{self._documents_url()}:commit",
            id_token=id_token,
            method="POST",
            payload={"writes": writes},
        )

    async def update_document(
        self,
        collection: str,
        document_id: str,
        fields: dict,
        field_paths: list[str],
        id_token: str,
    ) -> dict:
        update_mask = urlencode(
            [("updateMask.fieldPaths", path) for path in field_paths]
        )
        return await self._request(
            f"{self._document_url(collection, document_id)}?{update_mask}",
            id_token=id_token,
            method="PATCH",
            payload={"fields": fields},
        )

    async def delete_document(
        self, collection: str, document_id: str, id_token: str
    ) -> dict:
        return await self._request(
            self._document_url(collection, document_id),
            id_token=id_token,
            method="DELETE",
        )

    async def begin_transaction(self, id_token: str) -> str:
        result = await self._request(
            f"{self._documents_url()}:beginTransaction",
            id_token=id_token,
            method="POST",
            payload={"options": {"readWrite": {}}},
        )
        transaction = result.get("transaction") if isinstance(result, dict) else None
        if not transaction:
            raise FirebaseRestError(
                "O Firestore não retornou o identificador da transação."
            )
        return transaction

    async def run_query_in_transaction(
        self, structured_query: dict, transaction: str, id_token: str
    ) -> list:
        result = await self._request(
            f"{self._documents_url()}:runQuery",
            id_token=id_token,
            method="POST",
            payload={
                "structuredQuery": structured_query,
                "transaction": transaction,
            },
        )
        if not isinstance(result, list):
            raise FirebaseRestError("O Firestore retornou uma consulta inválida.")
        return result

    async def batch_get_in_transaction(
        self,
        document_names: list[str],
        transaction: str,
        id_token: str,
    ) -> list:
        if not document_names:
            return []
        result = await self._request(
            f"{self._documents_url()}:batchGet",
            id_token=id_token,
            method="POST",
            payload={
                "documents": document_names,
                "transaction": transaction,
            },
        )
        if not isinstance(result, list):
            raise FirebaseRestError("O Firestore retornou documentos inválidos.")
        return result

    async def commit_transaction(
        self, writes: list[dict], transaction: str, id_token: str
    ) -> dict:
        if len(writes) > MAX_FIRESTORE_BATCH_WRITES:
            raise ValueError(
                f"Cada transação pode conter no máximo "
                f"{MAX_FIRESTORE_BATCH_WRITES} gravações."
            )
        result = await self._request(
            f"{self._documents_url()}:commit",
            id_token=id_token,
            method="POST",
            payload={"writes": writes, "transaction": transaction},
        )
        return result if isinstance(result, dict) else {}

    async def rollback_transaction(
        self, transaction: str, id_token: str
    ) -> None:
        await self._request(
            f"{self._documents_url()}:rollback",
            id_token=id_token,
            method="POST",
            payload={"transaction": transaction},
        )

    async def list_active_item_types(self) -> list:
        return await self._request(
            f"{self._documents_url()}:runQuery",
            method="POST",
            payload={
                "structuredQuery": {
                    "from": [{"collectionId": "itemTypes"}],
                    "where": {
                        "fieldFilter": {
                            "field": {"fieldPath": "isActive"},
                            "op": "EQUAL",
                            "value": {"booleanValue": True},
                        }
                    },
                }
            },
        )

    async def list_available_items(self) -> list:
        return await self._request(
            f"{self._documents_url()}:runQuery",
            method="POST",
            payload={
                "structuredQuery": {
                    "from": [{"collectionId": "items"}],
                    "where": {
                        "fieldFilter": {
                            "field": {"fieldPath": "status"},
                            "op": "EQUAL",
                            "value": {"stringValue": "DISPONIVEL"},
                        }
                    },
                }
            },
        )

    async def list_active_pickup_spots(self) -> list:
        return await self._request(
            f"{self._documents_url()}:runQuery",
            method="POST",
            payload={
                "structuredQuery": {
                    "from": [{"collectionId": "pickupSpots"}],
                    "where": {
                        "fieldFilter": {
                            "field": {"fieldPath": "isActive"},
                            "op": "EQUAL",
                            "value": {"booleanValue": True},
                        }
                    },
                }
            },
        )

    async def list_pickup_spots(
        self, *, include_inactive: bool, id_token: str | None = None
    ) -> list:
        query = {"from": [{"collectionId": "pickupSpots"}]}
        if not include_inactive:
            query["where"] = {
                "fieldFilter": {
                    "field": {"fieldPath": "isActive"},
                    "op": "EQUAL",
                    "value": {"booleanValue": True},
                }
            }
        return await self._request(
            f"{self._documents_url()}:runQuery",
            id_token=id_token,
            method="POST",
            payload={"structuredQuery": query},
        )

    async def list_reservations(
        self,
        *,
        id_token: str,
        user_id: str | None = None,
        pickup_spot_id: str | None = None,
    ) -> list:
        filters = []
        if user_id:
            filters.append(
                {
                    "fieldFilter": {
                        "field": {"fieldPath": "userId"},
                        "op": "EQUAL",
                        "value": {"stringValue": user_id},
                    }
                }
            )
        if pickup_spot_id:
            filters.append(
                {
                    "fieldFilter": {
                        "field": {"fieldPath": "pickupSpotId"},
                        "op": "EQUAL",
                        "value": {"stringValue": pickup_spot_id},
                    }
                }
            )
        query = {"from": [{"collectionId": "reservations"}]}
        if len(filters) == 1:
            query["where"] = filters[0]
        elif filters:
            query["where"] = {
                "compositeFilter": {"op": "AND", "filters": filters}
            }
        return await self._request(
            f"{self._documents_url()}:runQuery",
            id_token=id_token,
            method="POST",
            payload={"structuredQuery": query},
        )

    async def list_item_types(self, id_token: str) -> list:
        return await self._request(
            f"{self._documents_url()}:runQuery",
            id_token=id_token,
            method="POST",
            payload={
                "structuredQuery": {
                    "from": [{"collectionId": "itemTypes"}],
                }
            },
        )

    async def has_items_for_item_type(
        self, item_type_id: str, id_token: str
    ) -> bool:
        rows = await self._request(
            f"{self._documents_url()}:runQuery",
            id_token=id_token,
            method="POST",
            payload={
                "structuredQuery": {
                    "from": [{"collectionId": "items"}],
                    "where": {
                        "fieldFilter": {
                            "field": {"fieldPath": "itemTypeId"},
                            "op": "EQUAL",
                            "value": {"stringValue": item_type_id},
                        }
                    },
                    "limit": 1,
                }
            },
        )
        return any(row.get("document") for row in rows)

    async def list_items_for_item_type(
        self, item_type_id: str, id_token: str
    ) -> list:
        return await self._request(
            f"{self._documents_url()}:runQuery",
            id_token=id_token,
            method="POST",
            payload={
                "structuredQuery": {
                    "from": [{"collectionId": "items"}],
                    "where": {
                        "fieldFilter": {
                            "field": {"fieldPath": "itemTypeId"},
                            "op": "EQUAL",
                            "value": {"stringValue": item_type_id},
                        }
                    },
                }
            },
        )

    async def create_pickup_spot(
        self, pickup_spot_id: str, fields: dict, id_token: str
    ) -> dict:
        return await self.create_document(
            "pickupSpots", pickup_spot_id, fields, id_token
        )

    async def _request(
        self,
        url: str,
        *,
        id_token: str | None = None,
        method: str = "GET",
        payload: dict | None = None,
    ) -> dict | list:
        headers = {}
        if id_token:
            headers["Authorization"] = f"Bearer {id_token}"
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload)
        if self.api_key:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{urlencode({'key': self.api_key})}"

        try:
            from pyodide.http import pyfetch
        except ModuleNotFoundError:
            return await asyncio.to_thread(
                self._request_sync, url, method, headers, body
            )

        response = await pyfetch(
            url,
            method=method,
            headers=headers,
            body=body,
        )
        response_body = await response.text()
        details = json.loads(response_body) if response_body else {}
        if not response.ok:
            self._raise_response_error(details, response.status)
        return details

    def _request_sync(
        self,
        url: str,
        method: str,
        headers: dict,
        body: str | None,
    ) -> dict | list:
        request = urllib.request.Request(
            url,
            data=body.encode("utf-8") if body is not None else None,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                response_body = response.read().decode("utf-8")
                return json.loads(response_body) if response_body else {}
        except urllib.error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="ignore")
            try:
                details = json.loads(response_body)
            except json.JSONDecodeError:
                details = {"error": {"message": response_body}}
            self._raise_response_error(details, exc.code)

    @staticmethod
    def _raise_response_error(details: dict, status_code: int) -> None:
        message = details.get("error", {}).get(
            "message", "Falha ao acessar o Cloud Firestore."
        )
        raise FirebaseRestError(message, status_code)


class FirebaseStorageClient:
    def __init__(self, bucket: str | None = None):
        self.bucket = bucket or STORAGE_BUCKET

    async def upload_image(
        self,
        object_name: str,
        image_data: bytes,
        content_type: str,
        id_token: str,
    ) -> str:
        if not self.bucket:
            raise FirebaseRestError(
                "Configure STORAGE_BUCKET para enviar fotos ao Firebase Storage."
            )
        if not id_token:
            raise FirebaseRestError("É necessário entrar para enviar uma foto.")

        url = (
            f"https://firebasestorage.googleapis.com/v0/b/{self.bucket}/o?"
            f"{urlencode({'uploadType': 'media', 'name': object_name})}"
        )
        headers = {
            "Authorization": f"Bearer {id_token}",
            "Content-Type": content_type,
        }
        details = await self._request(
            url, method="POST", headers=headers, body=image_data
        )

        download_token = (details.get("downloadTokens") or "").split(",", 1)[0]
        encoded_name = quote(object_name, safe="")
        download_url = (
            f"https://firebasestorage.googleapis.com/v0/b/{self.bucket}"
            f"/o/{encoded_name}?alt=media"
        )
        if download_token:
            download_url += f"&token={quote(download_token, safe='')}"
        return download_url

    async def delete_image(self, image_url: str, id_token: str) -> bool:
        object_name = self._object_name_from_url(image_url)
        if object_name is None:
            return False
        if not id_token:
            raise FirebaseRestError("É necessário entrar para excluir uma foto.")

        encoded_name = quote(object_name, safe="")
        url = (
            f"https://firebasestorage.googleapis.com/v0/b/{self.bucket}"
            f"/o/{encoded_name}"
        )
        try:
            await self._request(
                url,
                method="DELETE",
                headers={"Authorization": f"Bearer {id_token}"},
            )
        except FirebaseRestError as exc:
            if exc.status_code == 404:
                return False
            raise
        return True

    def _object_name_from_url(self, image_url: str) -> str | None:
        if not self.bucket:
            return None
        parsed_url = urlsplit(image_url)
        if parsed_url.hostname != "firebasestorage.googleapis.com":
            return None
        object_prefix = f"/v0/b/{self.bucket}/o/"
        if not parsed_url.path.startswith(object_prefix):
            return None
        object_name = unquote(parsed_url.path[len(object_prefix) :])
        return object_name or None

    async def _request(
        self,
        url: str,
        *,
        method: str,
        headers: dict,
        body: str | bytes | None = None,
    ) -> dict:
        try:
            from pyodide.http import pyfetch
        except ModuleNotFoundError:
            return await asyncio.to_thread(
                self._request_sync, url, method, headers, body
            )

        response = await pyfetch(
            url,
            method=method,
            headers=headers,
            body=body,
        )
        response_body = await response.text()
        details = json.loads(response_body) if response_body else {}
        if not response.ok:
            self._raise_response_error(details, response.status)
        return details

    def _request_sync(
        self,
        url: str,
        method: str,
        headers: dict,
        body: str | bytes | None,
    ) -> dict:
        request = urllib.request.Request(
            url,
            data=body.encode("utf-8") if isinstance(body, str) else body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                response_body = response.read().decode("utf-8")
                return json.loads(response_body) if response_body else {}
        except urllib.error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="ignore")
            try:
                details = json.loads(response_body)
            except json.JSONDecodeError:
                details = {"error": {"message": response_body}}
            self._raise_response_error(details, exc.code)

    @staticmethod
    def _raise_response_error(details: dict, status_code: int) -> None:
        message = details.get("error", {}).get(
            "message", "Falha ao acessar o Firebase Storage."
        )
        raise FirebaseRestError(message, status_code)
