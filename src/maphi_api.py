from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from firebase_rest import FirebaseRestError


DEFAULT_API_URL = "https://maphivendas.web.app"
API_PREFIX = "/api/v1"


class MaphiApiClient:
    async def get_profile(self, id_token: str) -> dict:
        response = await self._request("GET", "/profile", id_token=id_token)
        return self._required_object(response, "profile")

    async def upsert_profile(self, name: str, id_token: str) -> dict:
        response = await self._request(
            "POST",
            "/profile",
            id_token=id_token,
            payload={"name": name},
        )
        return self._required_object(response, "profile")

    async def list_item_types(
        self, *, include_inactive: bool = False, id_token: str | None = None
    ) -> list[dict]:
        if include_inactive:
            if not id_token:
                raise ValueError("A listagem administrativa exige autenticação.")
            response = await self._request(
                "GET", "/admin/item-types", id_token=id_token
            )
            return self._required_list(response, "item_types")

        response = await self._request("GET", "/catalog")
        return self._required_list(response, "items")

    async def list_pickup_spots(
        self, *, include_inactive: bool = False, id_token: str | None = None
    ) -> list[dict]:
        if include_inactive:
            if not id_token:
                raise ValueError("A listagem administrativa exige autenticação.")
            response = await self._request(
                "GET", "/admin/pickup-spots", id_token=id_token
            )
        else:
            response = await self._request("GET", "/pickup-spots")
        return self._required_list(response, "pickup_spots")

    async def list_items(
        self,
        *,
        id_token: str,
        item_type_id: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        response = await self._request(
            "GET",
            "/admin/items",
            id_token=id_token,
            query={
                "item_type_id": item_type_id,
                "status": status,
                "limit": limit,
            },
        )
        return self._required_list(response, "items")

    async def create_items(
        self, items: list[dict], id_token: str
    ) -> list[dict]:
        response = await self._request(
            "POST",
            "/admin/items",
            id_token=id_token,
            payload={"items": items},
        )
        return self._required_list(response, "items")

    async def create_item_type(
        self, fields: dict, id_token: str
    ) -> dict:
        response = await self._request(
            "POST", "/admin/item-types", id_token=id_token, payload=fields
        )
        return self._required_object(response, "item_type")

    async def update_item_type(
        self, item_type_id: str, fields: dict, id_token: str
    ) -> dict:
        response = await self._request(
            "PATCH",
            f"/admin/item-types/{item_type_id}",
            id_token=id_token,
            payload=fields,
        )
        return self._required_object(response, "item_type")

    async def delete_item_type(self, item_type_id: str, id_token: str) -> None:
        await self._request(
            "DELETE", f"/admin/item-types/{item_type_id}", id_token=id_token
        )

    async def delete_item(self, item_id: str, id_token: str) -> None:
        await self._request(
            "DELETE", f"/admin/items/{item_id}", id_token=id_token
        )

    async def create_pickup_spot(
        self, fields: dict, id_token: str
    ) -> dict:
        response = await self._request(
            "POST", "/admin/pickup-spots", id_token=id_token, payload=fields
        )
        return self._required_object(response, "pickup_spot")

    async def update_pickup_spot(
        self, pickup_spot_id: str, fields: dict, id_token: str
    ) -> dict:
        response = await self._request(
            "PATCH",
            f"/admin/pickup-spots/{pickup_spot_id}",
            id_token=id_token,
            payload=fields,
        )
        return self._required_object(response, "pickup_spot")

    async def delete_pickup_spot(
        self, pickup_spot_id: str, id_token: str
    ) -> None:
        await self._request(
            "DELETE",
            f"/admin/pickup-spots/{pickup_spot_id}",
            id_token=id_token,
        )

    async def list_reservations(
        self,
        *,
        id_token: str,
        is_owner: bool,
        pickup_spot_id: str | None = None,
    ) -> list[dict]:
        path = "/admin/reservations" if is_owner else "/reservations"
        response = await self._request(
            "GET",
            path,
            id_token=id_token,
            query={"pickup_spot_id": pickup_spot_id},
        )
        return self._required_list(response, "reservations")

    async def create_reservation(self, payload: dict, id_token: str) -> dict:
        response = await self._request(
            "POST", "/reservations", id_token=id_token, payload=payload
        )
        return self._required_object(response, "reservation")

    async def cancel_reservation(
        self, reservation_id: str, id_token: str
    ) -> dict:
        response = await self._request(
            "POST",
            f"/reservations/{reservation_id}/cancel",
            id_token=id_token,
        )
        return self._required_object(response, "reservation")

    async def complete_reservation(
        self, reservation_id: str, id_token: str
    ) -> dict:
        response = await self._request(
            "PATCH",
            f"/admin/reservations/{reservation_id}",
            id_token=id_token,
            payload={"status": "CONCLUIDA"},
        )
        return self._required_object(response, "reservation")

    async def delete_reservation(
        self, reservation_id: str, id_token: str
    ) -> None:
        await self._request(
            "DELETE",
            f"/admin/reservations/{reservation_id}",
            id_token=id_token,
        )

    @staticmethod
    def _required_list(payload: dict, key: str) -> list[dict]:
        value = payload.get(key)
        if not isinstance(value, list) or any(
            not isinstance(item, dict) for item in value
        ):
            raise FirebaseRestError(
                f"A API retornou uma lista inválida para {key}."
            )
        return value

    @staticmethod
    def _required_object(payload: dict, key: str) -> dict:
        value = payload.get(key)
        if not isinstance(value, dict):
            raise FirebaseRestError(
                f"A API retornou um objeto inválido para {key}."
            )
        return value

    async def _request(
        self,
        method: str,
        path: str,
        *,
        id_token: str | None = None,
        payload: dict | None = None,
        query: dict | None = None,
    ) -> dict:
        try:
            from pyodide.ffi import JsException  # type: ignore[reportMissingImports]
            from pyodide.http import pyfetch  # type: ignore[reportMissingImports]
        except ModuleNotFoundError:
            url = self._url(path, is_browser=False, query=query)
            return await asyncio.to_thread(
                self._request_sync, method, url, id_token, payload
            )

        url = self._url(path, is_browser=True, query=query)
        headers = self._headers(id_token, payload)
        body = json.dumps(payload, ensure_ascii=False) if payload is not None else None
        try:
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
            if not isinstance(details, dict):
                raise FirebaseRestError("A API retornou uma resposta inválida.")
            return details
        except FirebaseRestError:
            raise
        except (JsException, OSError, ValueError) as exc:
            raise FirebaseRestError("Não foi possível acessar a API do Maphi.") from exc

    def _request_sync(
        self,
        method: str,
        url: str,
        id_token: str | None,
        payload: dict | None,
    ) -> dict:
        body = (
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if payload is not None
            else None
        )
        request = urllib.request.Request(
            url,
            data=body,
            headers=self._headers(id_token, payload),
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                details = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = self._read_error_response(exc)
            self._raise_response_error(details, exc.code)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise FirebaseRestError(
                "Não foi possível acessar a API do Maphi."
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise FirebaseRestError("A API retornou uma resposta inválida.") from exc

        if not isinstance(details, dict):
            raise FirebaseRestError("A API retornou uma resposta inválida.")
        return details

    @staticmethod
    def _headers(id_token: str | None, payload: dict | None) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if id_token:
            headers["Authorization"] = f"Bearer {id_token}"
        if payload is not None:
            headers["Content-Type"] = "application/json"
        return headers

    @staticmethod
    def _url(
        path: str,
        *,
        is_browser: bool,
        query: dict | None,
    ) -> str:
        configured_url = os.getenv("MAPHI_API_URL")
        base_url = (
            configured_url.rstrip("/")
            if configured_url
            else "" if is_browser else DEFAULT_API_URL
        )
        url = f"{base_url}{API_PREFIX}{path}"
        query_values = {
            key: value
            for key, value in (query or {}).items()
            if value is not None
        }
        if query_values:
            url = f"{url}?{urllib.parse.urlencode(query_values)}"
        return url

    @staticmethod
    def _read_error_response(exc: urllib.error.HTTPError) -> dict:
        body = exc.read().decode("utf-8", errors="ignore")
        try:
            details = json.loads(body)
        except json.JSONDecodeError:
            details = {"error": {"message": body}}
        return details if isinstance(details, dict) else {}

    @staticmethod
    def _raise_response_error(details: dict, status_code: int) -> None:
        error = details.get("error")
        message = (
            error.get("message", "Falha ao acessar a API do Maphi.")
            if isinstance(error, dict)
            else "Falha ao acessar a API do Maphi."
        )
        raise FirebaseRestError(message, status_code)
