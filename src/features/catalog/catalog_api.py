from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from typing import Any

from features.catalog.catalog_logic import Cake


DEFAULT_API_URL = "https://maphivendas.web.app"
CATALOG_PATH = "/api/v1/catalog"
CAKE_COLORS = ("#F0E2D6", "#F4E9D5", "#F3E4E6", "#E9EEDC", "#F2E6D5", "#F1E1DD")


class CatalogApiError(Exception):
    pass


def parse_catalog_response(payload: Any) -> list[Cake]:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise CatalogApiError("A resposta do catálogo está em um formato inválido.")

    cakes = []
    seen_ids = set()
    for index, item in enumerate(payload["items"]):
        if not isinstance(item, dict):
            raise CatalogApiError("A resposta do catálogo contém um item inválido.")

        cake_id = item.get("id")
        name = item.get("name")
        description = item.get("description")
        stock = item.get("stock")
        image_url = item.get("image_url")
        if (
            not isinstance(cake_id, str)
            or not cake_id
            or cake_id in seen_ids
            or not isinstance(name, str)
            or not name.strip()
            or (description is not None and not isinstance(description, str))
            or isinstance(stock, bool)
            or not isinstance(stock, int)
            or stock < 0
            or (image_url is not None and not isinstance(image_url, str))
        ):
            raise CatalogApiError("A resposta do catálogo contém dados inválidos.")

        seen_ids.add(cake_id)
        cakes.append(
            Cake(
                id=cake_id,
                name=name.strip(),
                description=description or "",
                stock=stock,
                color=CAKE_COLORS[index % len(CAKE_COLORS)],
                image_url=image_url.strip() or None if image_url else None,
            )
        )

    return cakes


def _catalog_url(is_pyodide: bool) -> str:
    if is_pyodide:
        return CATALOG_PATH
    api_url = os.environ.get("MAPHI_API_URL", DEFAULT_API_URL).rstrip("/")
    return f"{api_url}{CATALOG_PATH}"


def _fetch_catalog_native() -> list[Cake]:
    request = urllib.request.Request(
        _catalog_url(is_pyodide=False),
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise CatalogApiError(
            f"O servidor do catálogo respondeu com HTTP {exc.code}."
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CatalogApiError(
            "Não foi possível conectar ao servidor do catálogo."
        ) from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CatalogApiError("O servidor retornou uma resposta inválida.") from exc

    return parse_catalog_response(payload)


async def _fetch_catalog_pyodide() -> list[Cake]:
    try:
        from pyodide.ffi import JsException  # type: ignore[reportMissingImports]
        from pyodide.http import pyfetch  # type: ignore[reportMissingImports]
    except ImportError as exc:
        raise CatalogApiError(
            "O ambiente web não disponibilizou o cliente HTTP do navegador."
        ) from exc

    try:
        response = await pyfetch(_catalog_url(is_pyodide=True))
        if response.status < 200 or response.status >= 300:
            raise CatalogApiError(
                f"O servidor do catálogo respondeu com HTTP {response.status}."
            )
        payload = await response.json()
    except CatalogApiError:
        raise
    except (JsException, OSError, ValueError) as exc:
        raise CatalogApiError(
            "Não foi possível conectar ao servidor do catálogo."
        ) from exc

    return parse_catalog_response(payload)


async def fetch_catalog(is_pyodide: bool) -> list[Cake]:
    if is_pyodide:
        return await _fetch_catalog_pyodide()
    return await asyncio.to_thread(_fetch_catalog_native)
