from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Callable
from uuid import UUID

import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin.exceptions import FirebaseError
from firebase_admin import firestore as firebase_firestore
from google.api_core.exceptions import GoogleAPIError
import psycopg
from firebase_functions import https_fn


REGION = "southamerica-east1"
API_PREFIX = "/api/v1"
MAX_STOCK_BATCH_UNITS = 500
ALLOWED_ORIGINS = {
    "https://maphivendas.web.app",
    "https://maphivendas.firebaseapp.com",
    "http://localhost:5000",
    "http://127.0.0.1:5000",
    "http://localhost:8550",
    "http://127.0.0.1:8550",
}

ITEM_STATUSES = {
    "DISPONIVEL",
    "RESERVADO",
    "VENDIDO",
    "VENDIDO_PRESENCIAL",
    "EM_OFERTA_PRESENCIAL",
    "REMOVIDO",
}
RESERVATION_STATUSES = {"ATIVA", "CONCLUIDA", "CANCELADA"}
ITEM_TYPE_FIELDS = {
    "name",
    "description",
    "image_url",
    "regular_price",
    "promotional_price",
    "is_custom_order_only",
    "is_active",
}
PICKUP_SPOT_FIELDS = {
    "name",
    "address",
    "window_start",
    "window_end",
    "is_active",
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _json_default(value: Any) -> Any:
    if isinstance(value, (UUID, datetime)):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def _response(
    request: https_fn.Request,
    payload: dict[str, Any],
    status: int = 200,
    extra_headers: dict[str, str] | None = None,
) -> https_fn.Response:
    headers = {
        "Cache-Control": "no-store",
        "Content-Type": "application/json; charset=utf-8",
    }
    origin = request.headers.get("Origin")
    if origin in ALLOWED_ORIGINS:
        headers.update(
            {
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Headers": "Authorization, Content-Type",
                "Access-Control-Allow-Methods": "GET, POST, PATCH, DELETE, OPTIONS",
                "Vary": "Origin",
            }
        )
    if extra_headers:
        headers.update(extra_headers)
    body = json.dumps(payload, default=_json_default, ensure_ascii=False)
    return https_fn.Response(body, status=status, headers=headers)


def _error(
    request: https_fn.Request,
    status: int,
    code: str,
    message: str,
    extra_headers: dict[str, str] | None = None,
) -> https_fn.Response:
    return _response(
        request,
        {"error": {"code": code, "message": message}},
        status=status,
        extra_headers=extra_headers,
    )


def _body(request: https_fn.Request) -> dict[str, Any]:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiError(400, "invalid_json", "Envie um objeto JSON válido.")
    return payload


def _only_fields(payload: dict[str, Any], allowed: set[str]) -> None:
    unknown = set(payload) - allowed
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise ApiError(
            400,
            "unknown_fields",
            f"A requisição contém campos não aceitos: {fields}.",
        )


def _required_text(value: Any, field: str, max_length: int = 500) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApiError(400, "invalid_field", f"O campo {field} é obrigatório.")
    result = value.strip()
    if len(result) > max_length:
        raise ApiError(400, "invalid_field", f"O campo {field} excede o tamanho permitido.")
    return result


def _optional_text(value: Any, field: str, max_length: int = 4000) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError(400, "invalid_field", f"O campo {field} deve ser texto.")
    result = value.strip()
    if len(result) > max_length:
        raise ApiError(400, "invalid_field", f"O campo {field} excede o tamanho permitido.")
    return result or None


def _required_bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise ApiError(400, "invalid_field", f"O campo {field} deve ser booleano.")
    return value


def _uuid(value: Any, field: str) -> UUID:
    if not isinstance(value, str):
        raise ApiError(400, "invalid_field", f"O campo {field} deve ser um UUID.")
    try:
        return UUID(value)
    except ValueError as exc:
        raise ApiError(400, "invalid_field", f"O campo {field} deve ser um UUID válido.") from exc


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ApiError(400, "invalid_field", f"O campo {field} deve ser uma data ISO 8601.")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApiError(400, "invalid_field", f"O campo {field} deve ser uma data ISO 8601.") from exc
    if result.utcoffset() is None:
        raise ApiError(
            400,
            "invalid_field",
            f"O campo {field} precisa incluir o fuso horário.",
        )
    return result


def _price(value: Any, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(400, "invalid_field", f"O campo {field} deve ser um preço válido.")
    try:
        result = Decimal(str(value)).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ApiError(400, "invalid_field", f"O campo {field} deve ser um preço válido.") from exc
    if not result.is_finite() or result <= 0 or not math.isfinite(float(result)):
        raise ApiError(400, "invalid_field", f"O campo {field} deve ser um preço válido.")
    return result


def _firebase_app() -> firebase_admin.App:
    try:
        return firebase_admin.get_app()
    except ValueError:
        return firebase_admin.initialize_app()


def _verify_firebase_token(token: str) -> dict[str, Any]:
    return firebase_auth.verify_id_token(
        token,
        app=_firebase_app(),
        check_revoked=True,
    )


def _authenticate(
    request: https_fn.Request,
    token_verifier: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    authorization = request.headers.get("Authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise ApiError(401, "unauthenticated", "Envie um Firebase ID token como Bearer token.")

    try:
        claims = token_verifier(token.strip())
    except (
        firebase_auth.InvalidIdTokenError,
        firebase_auth.ExpiredIdTokenError,
        firebase_auth.RevokedIdTokenError,
        firebase_auth.UserDisabledError,
        ValueError,
    ) as exc:
        raise ApiError(401, "invalid_token", "O token Firebase é inválido ou expirou.") from exc
    except FirebaseError as exc:
        logging.exception("Firebase token verification failed")
        raise ApiError(
            503,
            "authentication_unavailable",
            "Não foi possível verificar a autenticação no momento.",
        ) from exc

    if not isinstance(claims.get("uid"), str):
        raise ApiError(401, "invalid_token", "O token Firebase não contém um usuário válido.")
    return claims


def _profile(
    connection: psycopg.Connection,
    claims: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if payload is not None:
        _only_fields(payload, {"name", "phone"})

    uid = claims["uid"]
    email = claims.get("email")
    if not isinstance(email, str) or not email.strip():
        raise ApiError(403, "email_required", "A conta Firebase precisa ter um e-mail.")
    email = email.strip().lower()

    update_name = payload is not None and "name" in payload
    name = (
        _required_text(payload["name"], "name", 160)
        if update_name
        else str(claims.get("name") or email.split("@", 1)[0])[:160]
    )
    update_phone = payload is not None and "phone" in payload
    phone = _optional_text(payload.get("phone"), "phone", 40) if update_phone else None

    row = connection.execute(
        """
        INSERT INTO public.users (auth_uid, name, email, phone, role)
        VALUES (%s, %s, %s, %s, 'CLIENTE')
        ON CONFLICT (auth_uid) DO UPDATE
        SET email = EXCLUDED.email,
            name = CASE WHEN %s THEN EXCLUDED.name ELSE public.users.name END,
            phone = CASE WHEN %s THEN EXCLUDED.phone ELSE public.users.phone END
        RETURNING id, auth_uid, name, email, phone, role, created_at
        """,
        (uid, name, email, phone, update_name, update_phone),
    ).fetchone()
    return row


def _require_owner(
    connection: psycopg.Connection,
    claims: dict[str, Any],
) -> dict[str, Any]:
    profile = _profile(connection, claims)
    _sync_firebase_storage_role(profile)
    if profile["role"] != "DONO":
        raise ApiError(403, "forbidden", "Esta operação exige o papel DONO.")
    return profile


def _sync_firebase_storage_role(profile: dict[str, Any]) -> None:
    document = (
        firebase_firestore.client(app=_firebase_app())
        .collection("users")
        .document(str(profile["auth_uid"]))
    )
    existing = document.get()
    if existing.exists and (existing.to_dict() or {}).get("role") == profile["role"]:
        return
    document.set({"role": profile["role"]}, merge=True)


def _public_catalog(connection: psycopg.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT t.id, t.name, t.description, t.image_url,
               t.regular_price, t.promotional_price,
               t.is_custom_order_only, t.is_active,
               COUNT(i.id) FILTER (WHERE i.status = 'DISPONIVEL') AS stock
        FROM public.item_types AS t
        LEFT JOIN public.items AS i ON i.item_type_id = t.id
        WHERE t.is_active = TRUE
          AND t.is_custom_order_only = FALSE
        GROUP BY t.id
        ORDER BY t.name
        """
    ).fetchall()
    return [dict(row, stock=int(row["stock"])) for row in rows]


def _pickup_spots(
    connection: psycopg.Connection,
    include_inactive: bool = False,
) -> list[dict[str, Any]]:
    if include_inactive:
        rows = connection.execute(
            """
            SELECT id, name, address, window_start, window_end, is_active, created_at
            FROM public.pickup_spots
            WHERE deleted_at IS NULL
            ORDER BY window_start DESC
            LIMIT 200
            """
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT id, name, address, window_start, window_end
            FROM public.pickup_spots
            WHERE is_active = TRUE
              AND deleted_at IS NULL
              AND window_end > now() + interval '15 minutes'
            ORDER BY window_start
            LIMIT 200
            """
        ).fetchall()
    return [dict(row) for row in rows]


def _reservation_rows(
    connection: psycopg.Connection,
    user_id: UUID | None = None,
    status: str | None = None,
    pickup_spot_id: UUID | None = None,
    reservation_id: UUID | None = None,
) -> list[dict[str, Any]]:
    query = """
        SELECT r.id, r.user_id,
               COALESCE(r.user_name_snapshot, u.name) AS user_name,
               u.email AS user_email, u.phone AS user_phone,
               r.pickup_spot_id,
               COALESCE(r.pickup_spot_name_snapshot, p.name) AS pickup_spot_name,
               COALESCE(r.pickup_spot_address_snapshot, p.address) AS pickup_spot_address,
               COALESCE(r.pickup_window_start_snapshot, p.window_start) AS window_start,
               COALESCE(r.pickup_window_end_snapshot, p.window_end) AS window_end,
               r.sale_type, r.status, r.cancelled_by, r.cancelled_at,
               r.completed_at, r.created_at,
               SUM(ri.unit_price_snapshot) AS total_amount,
               COALESCE(
                   json_agg(
                       json_build_object(
                           'item_id', ri.item_id,
                           'item_type_id', ri.item_type_id_snapshot,
                           'item_type_name', ri.item_type_name_snapshot,
                           'unit_price', ri.unit_price_snapshot
                       ) ORDER BY ri.item_id
                   ) FILTER (WHERE ri.item_id IS NOT NULL),
                   '[]'::json
               ) AS items
        FROM public.reservations AS r
        JOIN public.users AS u ON u.id = r.user_id
        JOIN public.pickup_spots AS p ON p.id = r.pickup_spot_id
        LEFT JOIN public.reservation_items AS ri ON ri.reservation_id = r.id
        WHERE r.deleted_at IS NULL
    """
    params: list[Any] = []
    if user_id is not None:
        query += " AND r.user_id = %s"
        params.append(user_id)
    if status is not None:
        query += " AND r.status = %s"
        params.append(status)
    if pickup_spot_id is not None:
        query += " AND r.pickup_spot_id = %s"
        params.append(pickup_spot_id)
    if reservation_id is not None:
        query += " AND r.id = %s"
        params.append(reservation_id)
    query += """
        GROUP BY r.id, u.id, p.id
        ORDER BY r.created_at DESC
        LIMIT 200
    """
    return [dict(row) for row in connection.execute(query, params).fetchall()]


def _reservation_quantities(raw_items: Any) -> dict[UUID, int]:
    if not isinstance(raw_items, list) or not raw_items:
        raise ApiError(400, "invalid_items", "Informe ao menos um sabor para reservar.")

    quantities: dict[UUID, int] = {}
    for entry in raw_items:
        if not isinstance(entry, dict):
            raise ApiError(400, "invalid_items", "A lista de sabores é inválida.")
        _only_fields(entry, {"item_type_id", "quantity"})
        item_type_id = _uuid(entry.get("item_type_id"), "item_type_id")
        quantity = entry.get("quantity")
        if type(quantity) is not int or quantity < 1:
            raise ApiError(400, "invalid_quantity", "quantity deve ser um inteiro positivo.")
        if item_type_id in quantities:
            raise ApiError(400, "duplicate_items", "A lista contém sabores repetidos.")
        quantities[item_type_id] = quantity
    return quantities


def _create_reservation(
    connection: psycopg.Connection,
    claims: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    _only_fields(payload, {"pickup_spot_id", "items"})
    pickup_spot_id = _uuid(payload.get("pickup_spot_id"), "pickup_spot_id")
    quantities = _reservation_quantities(payload.get("items"))

    profile = _profile(connection, claims)
    pickup_spot = connection.execute(
        """
        SELECT id, name, address, window_start, window_end, is_active, deleted_at
        FROM public.pickup_spots
        WHERE id = %s
        FOR SHARE
        """,
        (pickup_spot_id,),
    ).fetchone()
    if (
        pickup_spot is None
        or pickup_spot["deleted_at"] is not None
        or not pickup_spot["is_active"]
    ):
        raise ApiError(409, "pickup_unavailable", "O local ou horário de retirada não está disponível.")
    if pickup_spot["window_end"] - pickup_spot["window_start"] < timedelta(minutes=15):
        raise ApiError(409, "pickup_unavailable", "A janela de retirada precisa ter pelo menos 15 minutos.")
    if (
        profile["role"] != "DONO"
        and pickup_spot["window_end"] <= datetime.now(pickup_spot["window_end"].tzinfo)
        + timedelta(minutes=15)
    ):
        raise ApiError(409, "pickup_unavailable", "O local ou horário de retirada não está disponível.")

    reserved_items: list[dict[str, Any]] = []
    for item_type_id, quantity in sorted(quantities.items(), key=lambda entry: str(entry[0])):
        item_type = connection.execute(
            """
            SELECT id, name, is_active, is_custom_order_only,
                   regular_price, promotional_price
            FROM public.item_types
            WHERE id = %s
            FOR SHARE
            """,
            (item_type_id,),
        ).fetchone()
        if (
            item_type is None
            or item_type["is_custom_order_only"]
            or (profile["role"] != "DONO" and not item_type["is_active"])
        ):
            raise ApiError(409, "items_unavailable", "Um dos sabores não está disponível para reserva.")
        if item_type["regular_price"] is None:
            raise ApiError(409, "price_unavailable", "Um dos sabores ainda não tem preço cadastrado.")

        unit_price = (
            item_type["regular_price"]
            if profile["role"] == "DONO" or item_type["promotional_price"] is None
            else item_type["promotional_price"]
        )
        available = connection.execute(
            """
            SELECT id
            FROM public.items
            WHERE item_type_id = %s AND status = 'DISPONIVEL'
            ORDER BY created_at, id
            LIMIT %s
            FOR UPDATE SKIP LOCKED
            """,
            (item_type_id, quantity),
        ).fetchall()
        if len(available) != quantity:
            raise ApiError(409, "items_unavailable", "O estoque mudou. Atualize o catálogo e tente novamente.")

        item_ids = [row["id"] for row in available]
        changed = connection.execute(
            """
            UPDATE public.items
            SET status = 'RESERVADO'
            WHERE id = ANY(%s) AND status = 'DISPONIVEL'
            RETURNING id
            """,
            (item_ids,),
        ).fetchall()
        if len(changed) != quantity:
            raise ApiError(409, "items_unavailable", "O estoque mudou. Atualize o catálogo e tente novamente.")
        reserved_items.extend(
            {
                "id": item_id,
                "item_type_id": item_type["id"],
                "item_type_name": item_type["name"],
                "unit_price": unit_price,
            }
            for item_id in item_ids
        )

    sale_type = "NORMAL" if profile["role"] == "DONO" else "PROMOCAO"
    reservation = connection.execute(
        """
        INSERT INTO public.reservations (
            user_id, pickup_spot_id, user_name_snapshot,
            pickup_spot_name_snapshot, pickup_spot_address_snapshot,
            pickup_window_start_snapshot, pickup_window_end_snapshot,
            sale_type, status
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'ATIVA')
        RETURNING id, user_id, pickup_spot_id, sale_type, status, created_at
        """,
        (
            profile["id"],
            pickup_spot_id,
            profile["name"],
            pickup_spot["name"],
            pickup_spot["address"],
            pickup_spot["window_start"],
            pickup_spot["window_end"],
            sale_type,
        ),
    ).fetchone()
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO public.reservation_items
                (
                    reservation_id, item_id, item_type_id_snapshot,
                    item_type_name_snapshot, unit_price_snapshot
                )
            VALUES (%s, %s, %s, %s, %s)
            """,
            [
                (
                    reservation["id"],
                    item["id"],
                    item["item_type_id"],
                    item["item_type_name"],
                    item["unit_price"],
                )
                for item in reserved_items
            ],
        )
    return _reservation_rows(
        connection, reservation_id=reservation["id"]
    )[0]


def _cancel_reservation(
    connection: psycopg.Connection,
    claims: dict[str, Any],
    reservation_id: UUID,
) -> dict[str, Any]:
    profile = _profile(connection, claims)
    reservation = connection.execute(
        """
        SELECT id, user_id, status
        FROM public.reservations
        WHERE id = %s AND deleted_at IS NULL
        FOR UPDATE
        """,
        (reservation_id,),
    ).fetchone()
    if reservation is None or (
        reservation["user_id"] != profile["id"] and profile["role"] != "DONO"
    ):
        raise ApiError(404, "reservation_not_found", "A reserva não foi encontrada.")
    if reservation["status"] != "ATIVA":
        raise ApiError(409, "reservation_not_active", "Somente reservas ativas podem ser canceladas.")

    item_rows = connection.execute(
        """
        SELECT i.id, i.status
        FROM public.reservation_items AS ri
        JOIN public.items AS i ON i.id = ri.item_id
        WHERE ri.reservation_id = %s
        ORDER BY i.id
        FOR UPDATE OF i
        """,
        (reservation_id,),
    ).fetchall()
    if any(row["status"] != "RESERVADO" for row in item_rows):
        raise ApiError(
            409,
            "reservation_inventory_conflict",
            "O estoque da reserva mudou; a operação foi cancelada sem alterações.",
        )
    item_ids = [row["id"] for row in item_rows]
    if item_ids:
        restored = connection.execute(
            """
            UPDATE public.items
            SET status = 'DISPONIVEL'
            WHERE id = ANY(%s)
              AND status = 'RESERVADO'
            RETURNING id
            """,
            (item_ids,),
        ).fetchall()
        if len(restored) != len(item_ids):
            raise ApiError(
                409,
                "reservation_inventory_conflict",
                "O estoque da reserva mudou; a operação foi cancelada sem alterações.",
            )

    updated = connection.execute(
        """
        UPDATE public.reservations
        SET status = 'CANCELADA',
            cancelled_by = %s,
            cancelled_at = now()
        WHERE id = %s AND status = 'ATIVA'
        RETURNING id, status
        """,
        ("DONO" if profile["role"] == "DONO" else "CLIENTE", reservation_id),
    ).fetchone()
    if updated is None:
        raise ApiError(409, "reservation_not_active", "A reserva não está mais ativa.")
    return dict(updated)


def _validate_item_type(payload: dict[str, Any], partial: bool) -> dict[str, Any]:
    _only_fields(payload, ITEM_TYPE_FIELDS)
    if not partial and not {"name", "regular_price"}.issubset(payload):
        raise ApiError(400, "invalid_field", "Informe nome e preço normal.")
    result: dict[str, Any] = {}
    for field in ("name", "description", "image_url"):
        if field in payload:
            if field == "name":
                result[field] = _required_text(payload[field], field, 160)
            else:
                result[field] = _optional_text(payload[field], field)
    if "regular_price" in payload:
        result["regular_price"] = _price(payload["regular_price"], "regular_price")
    elif not partial:
        raise ApiError(400, "invalid_field", "O campo regular_price é obrigatório.")
    if "promotional_price" in payload:
        result["promotional_price"] = (
            None
            if payload["promotional_price"] is None
            else _price(payload["promotional_price"], "promotional_price")
        )
    if (
        result.get("promotional_price") is not None
        and "regular_price" in result
        and result["promotional_price"] >= result["regular_price"]
    ):
        raise ApiError(
            400,
            "invalid_price",
            "O preço promocional deve ser menor que o preço normal.",
        )
    for field in ("is_custom_order_only", "is_active"):
        if field in payload:
            result[field] = _required_bool(payload[field], field)
    return result


def _validate_pickup_spot(payload: dict[str, Any], partial: bool) -> dict[str, Any]:
    _only_fields(payload, PICKUP_SPOT_FIELDS)
    required_fields = {"name", "address", "window_start", "window_end"}
    if not partial and not required_fields.issubset(payload):
        raise ApiError(400, "invalid_field", "Informe nome, endereço e janela do local.")
    result: dict[str, Any] = {}
    for field in ("name", "address"):
        if field in payload:
            result[field] = _required_text(payload[field], field, 500)
    for field in ("window_start", "window_end"):
        if field in payload:
            result[field] = _timestamp(payload[field], field)
    if "is_active" in payload:
        result["is_active"] = _required_bool(payload["is_active"], "is_active")
    if not partial and (
        result["window_end"] <= result["window_start"]
        or result["window_end"] - result["window_start"] < timedelta(minutes=15)
    ):
        raise ApiError(
            400,
            "invalid_window",
            "A janela de retirada deve ter pelo menos 15 minutos.",
        )
    return result


def _patch_row(
    connection: psycopg.Connection,
    table: str,
    fields: dict[str, Any],
    row_id: UUID,
) -> dict[str, Any]:
    columns = {
        "item_types": ITEM_TYPE_FIELDS,
        "pickup_spots": PICKUP_SPOT_FIELDS,
    }[table]
    if not fields or not set(fields).issubset(columns):
        raise ApiError(400, "invalid_fields", "Informe ao menos um campo válido para atualizar.")
    assignments = ", ".join(f"{field} = %s" for field in fields)
    row = connection.execute(
        f"UPDATE public.{table} SET {assignments} WHERE id = %s RETURNING *",
        [*fields.values(), row_id],
    ).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "O registro não foi encontrado.")
    return dict(row)


def _create_item_type(
    connection: psycopg.Connection,
    payload: dict[str, Any],
) -> dict[str, Any]:
    fields = _validate_item_type(payload, partial=False)
    fields.setdefault("description", None)
    fields.setdefault("image_url", None)
    fields.setdefault("promotional_price", None)
    fields.setdefault("is_custom_order_only", False)
    fields.setdefault("is_active", True)
    row = connection.execute(
        """
        INSERT INTO public.item_types
            (
                name, description, image_url, regular_price,
                promotional_price, is_custom_order_only, is_active
            )
        VALUES (
            %(name)s, %(description)s, %(image_url)s, %(regular_price)s,
            %(promotional_price)s, %(is_custom_order_only)s, %(is_active)s
        )
        RETURNING *
        """,
        fields,
    ).fetchone()
    return dict(row)


def _create_items(
    connection: psycopg.Connection,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    if "items" in payload:
        _only_fields(payload, {"items"})
        raw_items = payload["items"]
        if not isinstance(raw_items, list) or not raw_items:
            raise ApiError(400, "invalid_items", "Informe ao menos um sabor para a produção.")
        stock: dict[UUID, tuple[int, datetime | None]] = {}
        for entry in raw_items:
            if not isinstance(entry, dict):
                raise ApiError(400, "invalid_items", "A lista de produção é inválida.")
            _only_fields(entry, {"item_type_id", "quantity", "expiration_at"})
            item_type_id = _uuid(entry.get("item_type_id"), "item_type_id")
            quantity = entry.get("quantity")
            if type(quantity) is not int or quantity < 1:
                raise ApiError(400, "invalid_quantity", "quantity deve ser um inteiro positivo.")
            if item_type_id in stock:
                raise ApiError(400, "duplicate_items", "A produção contém sabores repetidos.")
            expiration_at = (
                _timestamp(entry["expiration_at"], "expiration_at")
                if entry.get("expiration_at") is not None
                else None
            )
            stock[item_type_id] = (quantity, expiration_at)
    else:
        _only_fields(payload, {"item_type_id", "quantity", "expiration_at"})
        item_type_id = _uuid(payload.get("item_type_id"), "item_type_id")
        quantity = payload.get("quantity")
        if type(quantity) is not int or quantity < 1:
            raise ApiError(400, "invalid_quantity", "quantity deve ser um inteiro positivo.")
        expiration_at = (
            _timestamp(payload["expiration_at"], "expiration_at")
            if payload.get("expiration_at") is not None
            else None
        )
        stock = {item_type_id: (quantity, expiration_at)}

    total_units = sum(quantity for quantity, _ in stock.values())
    if total_units > MAX_STOCK_BATCH_UNITS:
        raise ApiError(
            400,
            "invalid_quantity",
            f"Cada inserção pode conter no máximo {MAX_STOCK_BATCH_UNITS} unidades.",
        )
    created = []
    for item_type_id, (quantity, expiration_at) in stock.items():
        item_type = connection.execute(
            """
            SELECT id
            FROM public.item_types
            WHERE id = %s
              AND is_active = TRUE
              AND is_custom_order_only = FALSE
            FOR SHARE
            """,
            (item_type_id,),
        ).fetchone()
        if item_type is None:
            raise ApiError(404, "item_type_not_found", "O sabor ativo não foi encontrado.")
        rows = connection.execute(
            """
            INSERT INTO public.items (item_type_id, expiration_at)
            SELECT %s, %s
            FROM generate_series(1, %s)
            RETURNING id, item_type_id, status, expiration_at, created_at
            """,
            (item_type_id, expiration_at, quantity),
        ).fetchall()
        created.extend(dict(row) for row in rows)
    return created


def _update_item(
    connection: psycopg.Connection,
    item_id: UUID,
    payload: dict[str, Any],
) -> dict[str, Any]:
    _only_fields(payload, {"status", "expiration_at"})
    if not payload:
        raise ApiError(400, "invalid_fields", "Informe status ou expiration_at.")
    fields: dict[str, Any] = {}
    if "status" in payload:
        status = payload["status"]
        allowed = ITEM_STATUSES - {"RESERVADO"}
        if not isinstance(status, str) or status not in allowed:
            raise ApiError(400, "invalid_status", "O status solicitado não pode ser definido manualmente.")
        fields["status"] = status
    if "expiration_at" in payload:
        fields["expiration_at"] = (
            _timestamp(payload["expiration_at"], "expiration_at")
            if payload["expiration_at"] is not None
            else None
        )

    current = connection.execute(
        "SELECT id, status FROM public.items WHERE id = %s FOR UPDATE",
        (item_id,),
    ).fetchone()
    if current is None:
        raise ApiError(404, "item_not_found", "A unidade não foi encontrada.")
    if current["status"] == "RESERVADO" and "status" in fields:
        raise ApiError(409, "item_reserved", "Uma unidade reservada não pode ser alterada pelo estoque.")
    assignments = ", ".join(f"{field} = %s" for field in fields)
    row = connection.execute(
        f"""
        UPDATE public.items
        SET {assignments}
        WHERE id = %s
        RETURNING id, item_type_id, status, expiration_at, created_at
        """,
        [*fields.values(), item_id],
    ).fetchone()
    return dict(row)


def _delete_item(connection: psycopg.Connection, item_id: UUID) -> dict[str, str]:
    row = connection.execute(
        """
        UPDATE public.items
        SET status = 'REMOVIDO'
        WHERE id = %s AND status = 'DISPONIVEL'
        RETURNING id
        """,
        (item_id,),
    ).fetchone()
    if row is not None:
        return {"id": str(row["id"]), "status": "REMOVIDO"}
    current = connection.execute(
        "SELECT status FROM public.items WHERE id = %s",
        (item_id,),
    ).fetchone()
    if current is None:
        raise ApiError(404, "item_not_found", "A unidade não foi encontrada.")
    raise ApiError(
        409,
        "item_not_available_for_removal",
        "Somente unidades disponíveis podem ser removidas do estoque.",
    )


def _remove_items(
    connection: psycopg.Connection,
    payload: dict[str, Any],
) -> dict[str, Any]:
    _only_fields(payload, {"item_type_id", "quantity"})
    item_type_id = _uuid(payload.get("item_type_id"), "item_type_id")
    quantity = payload.get("quantity")
    if type(quantity) is not int or quantity < 1:
        raise ApiError(400, "invalid_quantity", "quantity deve ser um inteiro positivo.")

    available = connection.execute(
        """
        SELECT id
        FROM public.items
        WHERE item_type_id = %s AND status = 'DISPONIVEL'
        ORDER BY created_at, id
        LIMIT %s
        FOR UPDATE SKIP LOCKED
        """,
        (item_type_id, quantity),
    ).fetchall()
    if len(available) != quantity:
        raise ApiError(
            409,
            "insufficient_available_stock",
            "O estoque não reservado mudou. Atualize os sabores e tente novamente.",
        )

    item_ids = [row["id"] for row in available]
    removed = connection.execute(
        """
        UPDATE public.items
        SET status = 'REMOVIDO'
        WHERE id = ANY(%s) AND status = 'DISPONIVEL'
        RETURNING id
        """,
        (item_ids,),
    ).fetchall()
    if len(removed) != quantity:
        raise ApiError(
            409,
            "insufficient_available_stock",
            "O estoque não reservado mudou. Atualize os sabores e tente novamente.",
        )
    return {"item_type_id": str(item_type_id), "removed": len(removed)}


def _create_pickup_spot(
    connection: psycopg.Connection,
    payload: dict[str, Any],
) -> dict[str, Any]:
    fields = _validate_pickup_spot(payload, partial=False)
    fields.setdefault("is_active", True)
    row = connection.execute(
        """
        INSERT INTO public.pickup_spots
            (name, address, window_start, window_end, is_active)
        VALUES (%(name)s, %(address)s, %(window_start)s, %(window_end)s, %(is_active)s)
        RETURNING *
        """,
        fields,
    ).fetchone()
    return dict(row)


def _update_pickup_spot(
    connection: psycopg.Connection,
    spot_id: UUID,
    payload: dict[str, Any],
) -> dict[str, Any]:
    fields = _validate_pickup_spot(payload, partial=True)
    if not fields:
        raise ApiError(400, "invalid_fields", "Informe ao menos um campo válido para atualizar.")
    current = connection.execute(
        """
        SELECT window_start, window_end, deleted_at
        FROM public.pickup_spots
        WHERE id = %s
        FOR UPDATE
        """,
        (spot_id,),
    ).fetchone()
    if current is None or current["deleted_at"] is not None:
        raise ApiError(404, "pickup_spot_not_found", "O local não foi encontrado.")
    if set(fields) - {"is_active"}:
        has_active_reservations = connection.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM public.reservations
                WHERE pickup_spot_id = %s
                  AND status = 'ATIVA'
                  AND deleted_at IS NULL
            ) AS has_active
            """,
            (spot_id,),
        ).fetchone()["has_active"]
        if has_active_reservations:
            raise ApiError(
                409,
                "pickup_spot_has_active_reservations",
                "Crie um novo local/horário para não alterar reservas existentes.",
            )
    start = fields.get("window_start", current["window_start"])
    end = fields.get("window_end", current["window_end"])
    if end <= start or end - start < timedelta(minutes=15):
        raise ApiError(
            400,
            "invalid_window",
            "A janela de retirada deve ter pelo menos 15 minutos.",
        )
    assignments = ", ".join(f"{field} = %s" for field in fields)
    row = connection.execute(
        f"""
        UPDATE public.pickup_spots
        SET {assignments}
        WHERE id = %s AND deleted_at IS NULL
        RETURNING *
        """,
        [*fields.values(), spot_id],
    ).fetchone()
    if row is None:
        raise ApiError(404, "pickup_spot_not_found", "O local não foi encontrado.")
    return dict(row)


def _list_item_types(connection: psycopg.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT t.id, t.name, t.description, t.image_url, t.regular_price,
               t.promotional_price, t.is_custom_order_only, t.is_active,
               t.created_at,
               COUNT(i.id) FILTER (WHERE i.status = 'DISPONIVEL') AS stock,
               COUNT(i.id) FILTER (WHERE i.status = 'RESERVADO') AS reserved_stock
        FROM public.item_types AS t
        LEFT JOIN public.items AS i ON i.item_type_id = t.id
        GROUP BY t.id
        ORDER BY t.name
        LIMIT 200
        """
    ).fetchall()
    return [
        dict(
            row,
            stock=int(row["stock"]),
            reserved_stock=int(row["reserved_stock"]),
        )
        for row in rows
    ]


def _list_items(
    connection: psycopg.Connection,
    item_type_id: UUID | None,
    status: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    if status is not None and status not in ITEM_STATUSES:
        raise ApiError(400, "invalid_status", "O filtro status é inválido.")
    if not 1 <= limit <= 500:
        raise ApiError(400, "invalid_limit", "limit deve estar entre 1 e 500.")
    query = """
        SELECT i.id, i.item_type_id, t.name AS item_type_name,
               i.status, i.expiration_at, i.created_at
        FROM public.items AS i
        JOIN public.item_types AS t ON t.id = i.item_type_id
        WHERE TRUE
    """
    params: list[Any] = []
    if item_type_id is not None:
        query += " AND i.item_type_id = %s"
        params.append(item_type_id)
    if status is not None:
        query += " AND i.status = %s"
        params.append(status)
    query += " ORDER BY i.created_at, i.id LIMIT %s"
    params.append(limit)
    return [dict(row) for row in connection.execute(query, params).fetchall()]


def _delete_pickup_spot(
    connection: psycopg.Connection,
    claims: dict[str, Any],
    spot_id: UUID,
) -> dict[str, Any]:
    spot = connection.execute(
        """
        SELECT id, deleted_at
        FROM public.pickup_spots
        WHERE id = %s
        FOR UPDATE
        """,
        (spot_id,),
    ).fetchone()
    if spot is None or spot["deleted_at"] is not None:
        raise ApiError(404, "pickup_spot_not_found", "O local não foi encontrado.")

    active_reservations = connection.execute(
        """
        SELECT id
        FROM public.reservations
        WHERE pickup_spot_id = %s
          AND status = 'ATIVA'
          AND deleted_at IS NULL
        ORDER BY id
        FOR UPDATE
        """,
        (spot_id,),
    ).fetchall()
    for row in active_reservations:
        _cancel_reservation(connection, claims, row["id"])

    row = connection.execute(
        """
        UPDATE public.pickup_spots
        SET is_active = FALSE, deleted_at = now()
        WHERE id = %s AND deleted_at IS NULL
        RETURNING id
        """,
        (spot_id,),
    ).fetchone()
    if row is None:
        raise ApiError(404, "pickup_spot_not_found", "O local não foi encontrado.")
    return {"deleted": True, "id": row["id"]}


def _request_path(request: https_fn.Request) -> str:
    path = request.path.rstrip("/") or "/"
    return path


def handle_request(
    request: https_fn.Request,
    connection_factory: Callable[[], psycopg.Connection],
    token_verifier: Callable[[str], dict[str, Any]] = _verify_firebase_token,
) -> https_fn.Response:
    origin = request.headers.get("Origin")
    if origin and origin not in ALLOWED_ORIGINS:
        return _error(request, 403, "origin_not_allowed", "A origem desta requisição não está permitida.")
    if request.method == "OPTIONS":
        return https_fn.Response(
            "",
            status=204,
            headers={
                "Access-Control-Allow-Origin": origin or "",
                "Access-Control-Allow-Headers": "Authorization, Content-Type",
                "Access-Control-Allow-Methods": "GET, POST, PATCH, DELETE, OPTIONS",
                "Vary": "Origin",
            },
        )

    path = _request_path(request)
    method = request.method.upper()
    if path == f"{API_PREFIX}/health":
        if method != "GET":
            return _error(request, 405, "method_not_allowed", "Método não permitido.", {"Allow": "GET"})
        return _response(request, {"status": "ok"})
    if path == f"{API_PREFIX}/catalog":
        if method != "GET":
            return _error(request, 405, "method_not_allowed", "Método não permitido.", {"Allow": "GET"})
        try:
            with connection_factory() as connection:
                return _response(request, {"items": _public_catalog(connection)})
        except psycopg.Error:
            logging.exception("Supabase catalog query failed")
            return _error(request, 503, "database_unavailable", "Não foi possível carregar o catálogo.")
    if path == f"{API_PREFIX}/pickup-spots":
        if method != "GET":
            return _error(request, 405, "method_not_allowed", "Método não permitido.", {"Allow": "GET"})
        try:
            with connection_factory() as connection:
                return _response(request, {"pickup_spots": _pickup_spots(connection)})
        except psycopg.Error:
            logging.exception("Supabase pickup spot query failed")
            return _error(request, 503, "database_unavailable", "Não foi possível carregar os locais.")

    private_route = _resolve_private_route(path, method)
    if private_route is None:
        return _error(request, 404, "not_found", "Rota não encontrada.")
    if private_route == "method_not_allowed":
        return _error(
            request,
            405,
            "method_not_allowed",
            "Método não permitido.",
            {"Allow": _allowed_methods(path)},
        )

    try:
        claims = _authenticate(request, token_verifier)
        with connection_factory() as connection:
            result, status = _run_private_route(private_route, request, claims, connection)
            return _response(request, result, status)
    except ApiError as exc:
        return _error(request, exc.status, exc.code, exc.message)
    except psycopg.errors.UniqueViolation:
        logging.exception("Supabase unique constraint violation")
        return _error(request, 409, "conflict", "O registro conflita com dados existentes.")
    except psycopg.errors.ForeignKeyViolation:
        logging.exception("Supabase foreign key constraint violation")
        return _error(request, 409, "conflict", "O registro está associado a outros dados e não pode ser removido.")
    except psycopg.errors.CheckViolation:
        logging.exception("Supabase check constraint violation")
        return _error(request, 400, "invalid_data", "Os dados não atendem às regras do banco.")
    except GoogleAPIError:
        logging.exception("Firebase profile role synchronization failed")
        return _error(
            request,
            503,
            "profile_sync_unavailable",
            "Não foi possível sincronizar as permissões do perfil.",
        )
    except psycopg.Error:
        logging.exception("Supabase operation failed")
        return _error(request, 503, "database_unavailable", "Não foi possível concluir a operação.")


def _resolve_private_route(path: str, method: str) -> str | None:
    fixed_routes = {
        f"{API_PREFIX}/profile": {"GET": "profile_get", "POST": "profile_upsert"},
        f"{API_PREFIX}/reservations": {
            "GET": "reservations_list",
            "POST": "reservation_create",
        },
        f"{API_PREFIX}/admin/reservations": {"GET": "admin_reservations_list"},
        f"{API_PREFIX}/admin/item-types": {
            "GET": "admin_item_types_list",
            "POST": "admin_item_type_create",
        },
        f"{API_PREFIX}/admin/items": {
            "GET": "admin_items_list",
            "POST": "admin_items_create",
        },
        f"{API_PREFIX}/admin/items/remove": {"POST": "admin_items_remove"},
        f"{API_PREFIX}/admin/pickup-spots": {
            "GET": "admin_pickup_spots_list",
            "POST": "admin_pickup_spot_create",
        },
    }
    if path in fixed_routes:
        return fixed_routes[path].get(method, "method_not_allowed")

    patterns = (
        (r"/api/v1/reservations/([^/]+)/cancel", {"POST": "reservation_cancel"}),
        (r"/api/v1/admin/item-types/([^/]+)", {
            "PATCH": "admin_item_type_update",
            "DELETE": "admin_item_type_delete",
        }),
        (r"/api/v1/admin/items/([^/]+)", {
            "PATCH": "admin_item_update",
            "DELETE": "admin_item_delete",
        }),
        (r"/api/v1/admin/pickup-spots/([^/]+)", {
            "PATCH": "admin_pickup_spot_update",
            "DELETE": "admin_pickup_spot_delete",
        }),
        (r"/api/v1/admin/reservations/([^/]+)", {
            "PATCH": "admin_reservation_update",
            "DELETE": "admin_reservation_delete",
        }),
    )
    for pattern, methods in patterns:
        match = re.fullmatch(pattern, path)
        if match:
            route = methods.get(method)
            return f"{route}:{match.group(1)}" if route else "method_not_allowed"
    return None


def _allowed_methods(path: str) -> str:
    if path.endswith("/cancel"):
        return "POST"
    if path.endswith("/admin/items/remove"):
        return "POST"
    if "/admin/item-types/" in path or "/admin/items/" in path or "/admin/pickup-spots/" in path:
        return "PATCH, DELETE"
    if "/admin/reservations/" in path:
        return "PATCH, DELETE"
    route = _resolve_private_route(path, "")
    if route == "method_not_allowed":
        if path.endswith("/profile"):
            return "GET, POST"
        if path.endswith("/reservations"):
            return "GET, POST"
        if path.endswith("/admin/reservations"):
            return "GET"
        if path.endswith("/admin/item-types"):
            return "GET, POST"
        if path.endswith("/admin/items"):
            return "GET, POST"
        if path.endswith("/admin/pickup-spots"):
            return "GET, POST"
    return "GET, POST, PATCH, DELETE"


def _route_id(route: str) -> tuple[str, UUID]:
    name, raw_id = route.split(":", 1)
    return name, _uuid(raw_id, "id")


def _run_private_route(
    route: str,
    request: https_fn.Request,
    claims: dict[str, Any],
    connection: psycopg.Connection,
) -> tuple[dict[str, Any], int]:
    if route == "profile_get":
        profile = _profile(connection, claims)
        _sync_firebase_storage_role(profile)
        return {"profile": profile}, 200
    if route == "profile_upsert":
        profile = _profile(connection, claims, _body(request))
        _sync_firebase_storage_role(profile)
        return {"profile": profile}, 200
    if route == "reservation_create":
        return {"reservation": _create_reservation(connection, claims, _body(request))}, 201
    if route == "reservations_list":
        profile = _profile(connection, claims)
        status = request.args.get("status")
        if status is not None and status not in RESERVATION_STATUSES:
            raise ApiError(400, "invalid_status", "O filtro status é inválido.")
        return {
            "reservations": _reservation_rows(connection, profile["id"], status)
        }, 200

    if route.startswith("reservation_cancel:"):
        _, reservation_id = _route_id(route)
        _cancel_reservation(connection, claims, reservation_id)
        return {
            "reservation": _reservation_rows(
                connection, reservation_id=reservation_id
            )[0]
        }, 200

    if route == "admin_reservations_list":
        _require_owner(connection, claims)
        status = request.args.get("status")
        if status is not None and status not in RESERVATION_STATUSES:
            raise ApiError(400, "invalid_status", "O filtro status é inválido.")
        raw_spot_id = request.args.get("pickup_spot_id")
        pickup_spot_id = (
            _uuid(raw_spot_id, "pickup_spot_id")
            if raw_spot_id is not None
            else None
        )
        return {
            "reservations": _reservation_rows(
                connection, status=status, pickup_spot_id=pickup_spot_id
            )
        }, 200
    if route.startswith("admin_reservation_update:"):
        _require_owner(connection, claims)
        _, reservation_id = _route_id(route)
        payload = _body(request)
        _only_fields(payload, {"status"})
        if payload.get("status") != "CONCLUIDA":
            raise ApiError(400, "invalid_status", "O único status permitido nesta operação é CONCLUIDA.")
        connection.execute(
            """
            SELECT id
            FROM public.reservations
            WHERE id = %s AND status = 'ATIVA' AND deleted_at IS NULL
            FOR UPDATE
            """,
            (reservation_id,),
        )
        item_rows = connection.execute(
            """
            SELECT i.id, i.status
            FROM public.reservation_items AS ri
            JOIN public.items AS i ON i.id = ri.item_id
            WHERE ri.reservation_id = %s
            ORDER BY i.id
            FOR UPDATE OF i
            """,
            (reservation_id,),
        ).fetchall()
        if not item_rows or any(row["status"] != "RESERVADO" for row in item_rows):
            raise ApiError(
                409,
                "reservation_inventory_conflict",
                "O estoque da reserva mudou; a operação não foi concluída.",
            )
        item_ids = [row["id"] for row in item_rows]
        connection.execute(
            """
            UPDATE public.items
            SET status = 'VENDIDO'
            WHERE id = ANY(%s) AND status = 'RESERVADO'
            """,
            (item_ids,),
        )
        row = connection.execute(
            """
            UPDATE public.reservations
            SET status = 'CONCLUIDA', completed_at = now()
            WHERE id = %s AND status = 'ATIVA' AND deleted_at IS NULL
            RETURNING id, status
            """,
            (reservation_id,),
        ).fetchone()
        if row is None:
            raise ApiError(409, "reservation_not_active", "A reserva não está ativa ou não foi encontrada.")
        return {
            "reservation": _reservation_rows(
                connection, reservation_id=reservation_id
            )[0]
        }, 200
    if route.startswith("admin_reservation_delete:"):
        _require_owner(connection, claims)
        _, reservation_id = _route_id(route)
        row = connection.execute(
            """
            UPDATE public.reservations
            SET deleted_at = now()
            WHERE id = %s
              AND status IN ('CONCLUIDA', 'CANCELADA')
              AND deleted_at IS NULL
            RETURNING id
            """,
            (reservation_id,),
        ).fetchone()
        if row is None:
            raise ApiError(
                409,
                "reservation_not_deletable",
                "Só é possível apagar reservas canceladas ou concluídas.",
            )
        return {"deleted": True, "id": row["id"]}, 200

    if route == "admin_item_types_list":
        _require_owner(connection, claims)
        return {"item_types": _list_item_types(connection)}, 200
    if route == "admin_item_type_create":
        _require_owner(connection, claims)
        return {"item_type": _create_item_type(connection, _body(request))}, 201
    if route.startswith("admin_item_type_update:"):
        _require_owner(connection, claims)
        _, item_type_id = _route_id(route)
        fields = _validate_item_type(_body(request), partial=True)
        return {
            "item_type": _patch_row(connection, "item_types", fields, item_type_id)
        }, 200
    if route.startswith("admin_item_type_delete:"):
        _require_owner(connection, claims)
        _, item_type_id = _route_id(route)
        item_type = connection.execute(
            "SELECT id FROM public.item_types WHERE id = %s FOR UPDATE",
            (item_type_id,),
        ).fetchone()
        if item_type is None:
            raise ApiError(404, "item_type_not_found", "O sabor não foi encontrado.")
        has_items = connection.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM public.items WHERE item_type_id = %s
            ) AS has_items
            """,
            (item_type_id,),
        ).fetchone()["has_items"]
        if has_items:
            raise ApiError(
                409,
                "item_type_has_items",
                "O sabor possui unidades de estoque ou histórico e não pode ser excluído.",
            )
        row = connection.execute(
            "DELETE FROM public.item_types WHERE id = %s RETURNING id",
            (item_type_id,),
        ).fetchone()
        if row is None:
            raise ApiError(404, "item_type_not_found", "O sabor não foi encontrado.")
        return {"deleted": True, "id": row["id"]}, 200

    if route == "admin_items_list":
        _require_owner(connection, claims)
        raw_item_type_id = request.args.get("item_type_id")
        item_type_id = (
            _uuid(raw_item_type_id, "item_type_id")
            if raw_item_type_id is not None
            else None
        )
        status = request.args.get("status")
        raw_limit = request.args.get("limit", "200")
        try:
            limit = int(raw_limit)
        except ValueError as exc:
            raise ApiError(400, "invalid_limit", "limit deve ser um inteiro.") from exc
        return {
            "items": _list_items(connection, item_type_id, status, limit)
        }, 200
    if route == "admin_items_create":
        _require_owner(connection, claims)
        return {"items": _create_items(connection, _body(request))}, 201
    if route == "admin_items_remove":
        _require_owner(connection, claims)
        return {"result": _remove_items(connection, _body(request))}, 200
    if route.startswith("admin_item_update:"):
        _require_owner(connection, claims)
        _, item_id = _route_id(route)
        return {"item": _update_item(connection, item_id, _body(request))}, 200
    if route.startswith("admin_item_delete:"):
        _require_owner(connection, claims)
        _, item_id = _route_id(route)
        return {"item": _delete_item(connection, item_id)}, 200

    if route == "admin_pickup_spots_list":
        _require_owner(connection, claims)
        return {"pickup_spots": _pickup_spots(connection, include_inactive=True)}, 200
    if route == "admin_pickup_spot_create":
        _require_owner(connection, claims)
        return {"pickup_spot": _create_pickup_spot(connection, _body(request))}, 201
    if route.startswith("admin_pickup_spot_update:"):
        _require_owner(connection, claims)
        _, spot_id = _route_id(route)
        return {
            "pickup_spot": _update_pickup_spot(connection, spot_id, _body(request))
        }, 200
    if route.startswith("admin_pickup_spot_delete:"):
        _require_owner(connection, claims)
        _, spot_id = _route_id(route)
        return _delete_pickup_spot(connection, claims, spot_id), 200

    raise ApiError(404, "not_found", "Rota não encontrada.")
