from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from collections.abc import Awaitable, Callable
import uuid

from features.pickup_spots.pickup_spots_logic import (
    LOCAL_TIMEZONE,
    MINIMUM_PICKUP_WINDOW,
)
from firebase_rest import (
    FirebaseFirestoreClient,
    FirebaseRestError,
)

MAX_UNITS_PER_RESERVATION = 2
RESERVATION_ACTIVE = "ATIVA"
RESERVATION_CANCELLED = "CANCELADA"
RESERVATION_COMPLETED = "CONCLUIDA"


class ReservationError(ValueError):
    pass


@dataclass(frozen=True)
class Reservation:
    id: str
    user_id: str
    user_name: str
    pickup_spot_id: str
    pickup_spot_name: str
    pickup_spot_address: str
    pickup_arrival_at: datetime | None
    pickup_departure_at: datetime | None
    item_ids: tuple[str, ...]
    item_type_names: tuple[str, ...]
    unit_prices: tuple[Decimal, ...]
    total_amount: Decimal
    sale_type: str
    status: str
    created_at: datetime | None
    cancelled_by: str | None = None
    cancelled_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.status == RESERVATION_ACTIVE

    @property
    def status_label(self) -> str:
        if self.is_active:
            return "Aguardando retirada"
        if self.status == RESERVATION_COMPLETED:
            return "Venda finalizada"
        if self.status == RESERVATION_CANCELLED:
            return (
                "Cancelada pelo dono"
                if self.cancelled_by == "DONO"
                else "Cancelada pelo usuário"
            )
        return self.status


class ReservationController:
    def __init__(self) -> None:
        self.firestore_client = FirebaseFirestoreClient()
        self.reservations: list[Reservation] = []

    async def load_reservations(
        self,
        *,
        user_id: str,
        id_token: str,
        is_owner: bool,
        pickup_spot_id: str | None = None,
    ) -> list[Reservation]:
        if not user_id or not id_token:
            raise ReservationError("Entre na sua conta para ver as reservas.")
        if not is_owner and pickup_spot_id is not None:
            raise ReservationError(
                "Clientes só podem visualizar as próprias reservas."
            )
        rows = await self.firestore_client.list_reservations(
            id_token=id_token,
            user_id=None if is_owner else user_id,
            pickup_spot_id=pickup_spot_id if is_owner else None,
        )
        reservations = []
        for row in rows:
            document = row.get("document")
            if document:
                reservations.append(self._decode_reservation(document))
        reservations.sort(
            key=lambda reservation: reservation.created_at
            or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        self.reservations = reservations
        return reservations

    async def create_reservation(
        self,
        *,
        quantities: dict[str, int],
        pickup_spot_id: str,
        user_id: str,
        user_name: str,
        is_owner: bool,
        id_token: str,
    ) -> Reservation:
        if not user_id or not id_token:
            raise ReservationError("Entre na sua conta para reservar bolos.")
        if not pickup_spot_id:
            raise ReservationError("Selecione um local de retirada.")
        selected = {
            item_type_id: quantity
            for item_type_id, quantity in quantities.items()
            if quantity
        }
        if not selected:
            raise ReservationError("Selecione ao menos um bolo para reservar.")
        if any(type(quantity) is not int or quantity < 0 for quantity in selected.values()):
            raise ReservationError("As quantidades selecionadas são inválidas.")
        requested_units = sum(selected.values())
        if requested_units > MAX_UNITS_PER_RESERVATION:
            raise ReservationError(
                f"Uma reserva pode conter no máximo "
                f"{MAX_UNITS_PER_RESERVATION} unidades."
            )

        reservation_id = uuid.uuid4().hex
        created_fields: dict = {}

        async def build_writes(transaction: str) -> list[dict]:
            nonlocal created_fields
            pickup_path = self.firestore_client.document_name(
                "pickupSpots", pickup_spot_id
            )
            pickup_result = await self.firestore_client.batch_get_in_transaction(
                [pickup_path], transaction, id_token
            )
            pickup = self._found_document(pickup_result, pickup_path)
            pickup_fields = pickup.get("fields", {})
            if not pickup_fields.get("isActive", {}).get("booleanValue", False):
                raise ReservationError("O local de retirada não está ativo.")
            pickup_start = self._timestamp(
                pickup_fields.get("arrivalAt", {}).get("timestampValue")
            )
            pickup_end = self._timestamp(
                pickup_fields.get("departureAt", {}).get("timestampValue")
            )
            now = datetime.now(LOCAL_TIMEZONE)
            if (
                pickup_start is None
                or pickup_end is None
                or pickup_end <= pickup_start
                or pickup_end - pickup_start < MINIMUM_PICKUP_WINDOW
            ):
                raise ReservationError(
                    "O local não tem uma janela de retirada válida."
                )
            if not is_owner and pickup_end <= now + MINIMUM_PICKUP_WINDOW:
                raise ReservationError(
                    "Este local não permite reservas a menos de 15 minutos do encerramento."
                )

            allocated = []
            for item_type_id, quantity in selected.items():
                available_rows = (
                    await self.firestore_client.run_query_in_transaction(
                        {
                            "from": [{"collectionId": "items"}],
                            "where": {
                                "compositeFilter": {
                                    "op": "AND",
                                    "filters": [
                                        {
                                            "fieldFilter": {
                                                "field": {
                                                    "fieldPath": "itemTypeId"
                                                },
                                                "op": "EQUAL",
                                                "value": {
                                                    "stringValue": item_type_id
                                                },
                                            }
                                        },
                                        {
                                            "fieldFilter": {
                                                "field": {
                                                    "fieldPath": "status"
                                                },
                                                "op": "EQUAL",
                                                "value": {
                                                    "stringValue": "DISPONIVEL"
                                                },
                                            }
                                        },
                                    ],
                                }
                            },
                            "limit": quantity,
                        },
                        transaction,
                        id_token,
                    )
                )
                units = [
                    row["document"]
                    for row in available_rows
                    if row.get("document")
                ]
                if len(units) != quantity:
                    raise ReservationError(
                        "O estoque mudou. Atualize o catálogo e tente novamente."
                    )
                allocated.extend(units)

            item_type_ids = {
                self._string(item.get("fields", {}), "itemTypeId")
                for item in allocated
            }
            item_type_paths = [
                self.firestore_client.document_name("itemTypes", item_type_id)
                for item_type_id in item_type_ids
            ]
            item_type_rows = await self.firestore_client.batch_get_in_transaction(
                item_type_paths, transaction, id_token
            )
            item_types = {
                document.get("name", "").rsplit("/", 1)[-1]: document
                for row in item_type_rows
                if (document := row.get("found"))
            }

            item_ids = []
            item_names = []
            unit_prices = []
            item_writes = []
            for item in allocated:
                item_id = item.get("name", "").rsplit("/", 1)[-1]
                item_fields = item.get("fields", {})
                item_type_id = self._string(item_fields, "itemTypeId")
                item_type = item_types.get(item_type_id)
                if not item_id or item_type is None:
                    raise ReservationError(
                        "Não foi possível confirmar o sabor de uma unidade."
                    )
                type_fields = item_type.get("fields", {})
                if (
                    not is_owner
                    and not type_fields.get("isActive", {}).get(
                        "booleanValue", False
                    )
                ):
                    raise ReservationError(
                        "Um dos sabores selecionados não está mais ativo."
                    )
                item_type_name = self._string(type_fields, "name")
                unit_price = self._price(
                    type_fields, use_promotional=not is_owner
                )
                item_ids.append(item_id)
                item_names.append(item_type_name)
                unit_prices.append(unit_price)
                item_writes.append(
                    self._update_write(
                        "items",
                        item_id,
                        {
                            "status": {"stringValue": "RESERVADO"},
                            "reservationId": {
                                "stringValue": reservation_id
                            },
                            "reservedPrice": {
                                "doubleValue": float(unit_price)
                            },
                        },
                        ["status", "reservationId", "reservedPrice"],
                    )
                )

            total_amount = sum(unit_prices, Decimal("0.00"))
            reservation_fields = {
                "userId": {"stringValue": user_id},
                "userName": {"stringValue": user_name.strip() or "Usuário"},
                "pickupSpotId": {"stringValue": pickup_spot_id},
                "pickupSpotName": {
                    "stringValue": self._string(pickup_fields, "name")
                },
                "pickupSpotAddress": {
                    "stringValue": self._string(pickup_fields, "address")
                },
                "pickupArrivalAt": {
                    "timestampValue": pickup_start.astimezone(timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z")
                },
                "pickupDepartureAt": {
                    "timestampValue": pickup_end.astimezone(timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z")
                },
                "itemIds": {"arrayValue": {"values": [
                    {"stringValue": item_id} for item_id in item_ids
                ]}},
                "itemTypeNames": {"arrayValue": {"values": [
                    {"stringValue": name} for name in item_names
                ]}},
                "unitPrices": {"arrayValue": {"values": [
                    {"doubleValue": float(price)} for price in unit_prices
                ]}},
                "totalAmount": {"doubleValue": float(total_amount)},
                "saleType": {
                    "stringValue": "NORMAL" if is_owner else "PROMOCAO"
                },
                "status": {"stringValue": RESERVATION_ACTIVE},
                "createdAt": {
                    "timestampValue": datetime.now(timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z")
                },
            }
            item_type_ids_in_order = [
                self._string(item.get("fields", {}), "itemTypeId")
                for item in allocated
            ]
            reservation_fields["itemTypeIds"] = {
                "arrayValue": {
                    "values": [
                        {"stringValue": item_type_id}
                        for item_type_id in item_type_ids_in_order
                    ]
                }
            }
            created_fields = reservation_fields
            item_writes.append(
                self._create_write(
                    "reservations", reservation_id, reservation_fields
                )
            )
            return item_writes

        await self._run_transaction(id_token, build_writes)
        document = {
            "name": self.firestore_client.document_name(
                "reservations", reservation_id
            ),
            "fields": created_fields,
        }
        reservation = self._decode_reservation(document)
        self.reservations.insert(0, reservation)
        return reservation

    async def cancel_reservation(
        self,
        reservation_id: str,
        *,
        user_id: str,
        id_token: str,
        is_owner: bool,
    ) -> None:
        await self._change_reservation_status(
            reservation_id,
            user_id=user_id,
            id_token=id_token,
            is_owner=is_owner,
            new_status=RESERVATION_CANCELLED,
            cancelled_by="DONO" if is_owner else "CLIENTE",
        )

    async def complete_reservation(
        self,
        reservation_id: str,
        *,
        id_token: str,
        is_owner: bool,
    ) -> None:
        if not is_owner:
            raise ReservationError("Apenas o dono pode confirmar a venda.")
        await self._change_reservation_status(
            reservation_id,
            user_id="",
            id_token=id_token,
            is_owner=True,
            new_status=RESERVATION_COMPLETED,
        )

    async def delete_reservation(
        self, reservation_id: str, *, id_token: str, is_owner: bool
    ) -> None:
        if not is_owner:
            raise ReservationError("Apenas o dono pode apagar reservas.")

        async def build_writes(transaction: str) -> list[dict]:
            path = self.firestore_client.document_name(
                "reservations", reservation_id
            )
            result = await self.firestore_client.batch_get_in_transaction(
                [path], transaction, id_token
            )
            reservation = self._found_document(result, path)
            status = self._string(reservation.get("fields", {}), "status")
            if status not in {RESERVATION_CANCELLED, RESERVATION_COMPLETED}:
                raise ReservationError(
                    "Só é possível apagar reservas canceladas ou vendidas."
                )
            return [{"delete": path}]

        await self._run_transaction(id_token, build_writes)
        self.reservations = [
            item for item in self.reservations if item.id != reservation_id
        ]

    async def cancel_active_for_pickup(
        self, pickup_spot_id: str, *, owner_id: str, id_token: str
    ) -> int:
        rows = await self.firestore_client.list_reservations(
            id_token=id_token, pickup_spot_id=pickup_spot_id
        )
        active_ids = [
            row["document"]["name"].rsplit("/", 1)[-1]
            for row in rows
            if row.get("document")
            and self._string(row["document"].get("fields", {}), "status")
            == RESERVATION_ACTIVE
        ]
        for reservation_id in active_ids:
            await self.cancel_reservation(
                reservation_id,
                user_id=owner_id,
                id_token=id_token,
                is_owner=True,
            )
        return len(active_ids)

    async def _change_reservation_status(
        self,
        reservation_id: str,
        *,
        user_id: str,
        id_token: str,
        is_owner: bool,
        new_status: str,
        cancelled_by: str | None = None,
    ) -> None:
        async def build_writes(transaction: str) -> list[dict]:
            reservation_path = self.firestore_client.document_name(
                "reservations", reservation_id
            )
            rows = await self.firestore_client.batch_get_in_transaction(
                [reservation_path], transaction, id_token
            )
            reservation = self._found_document(rows, reservation_path)
            fields = reservation.get("fields", {})
            if self._string(fields, "status") != RESERVATION_ACTIVE:
                raise ReservationError(
                    "Esta reserva não está mais ativa."
                )
            if not is_owner and self._string(fields, "userId") != user_id:
                raise ReservationError(
                    "Você só pode cancelar as próprias reservas."
                )

            item_ids = self._string_list(fields.get("itemIds", {}))
            item_paths = [
                self.firestore_client.document_name("items", item_id)
                for item_id in item_ids
            ]
            item_rows = await self.firestore_client.batch_get_in_transaction(
                item_paths, transaction, id_token
            )
            items = [
                self._found_document(item_rows, path) for path in item_paths
            ]
            item_writes = []
            for item_id, item in zip(item_ids, items):
                item_fields = item.get("fields", {})
                if (
                    self._string(item_fields, "status") != "RESERVADO"
                    or self._string(item_fields, "reservationId")
                    != reservation_id
                ):
                    raise ReservationError(
                        "O estoque desta reserva está inconsistente; "
                        "nenhuma alteração foi feita."
                    )
                item_status = (
                    "DISPONIVEL"
                    if new_status == RESERVATION_CANCELLED
                    else "VENDIDO"
                )
                item_writes.append(
                    self._update_write(
                        "items",
                        item_id,
                        {"status": {"stringValue": item_status}},
                        ["status", "reservationId", "reservedPrice"],
                    )
                )

            if new_status == RESERVATION_CANCELLED:
                reservation_fields = {
                    "status": {"stringValue": new_status},
                    "cancelledBy": {"stringValue": cancelled_by or "DONO"},
                    "cancelledAt": {
                        "timestampValue": datetime.now(timezone.utc)
                        .isoformat()
                        .replace("+00:00", "Z")
                    },
                }
                field_paths = ["status", "cancelledBy", "cancelledAt"]
            else:
                reservation_fields = {
                    "status": {"stringValue": new_status},
                    "completedAt": {
                        "timestampValue": datetime.now(timezone.utc)
                        .isoformat()
                        .replace("+00:00", "Z")
                    },
                }
                field_paths = ["status", "completedAt"]
            reservation_write = self._update_write(
                "reservations",
                reservation_id,
                reservation_fields,
                field_paths,
            )
            return [*item_writes, reservation_write]

        await self._run_transaction(id_token, build_writes)
        for index, reservation in enumerate(self.reservations):
            if reservation.id != reservation_id:
                continue
            if new_status == RESERVATION_CANCELLED:
                self.reservations[index] = Reservation(
                    **{
                        **reservation.__dict__,
                        "status": new_status,
                        "cancelled_by": cancelled_by,
                        "created_at": reservation.created_at,
                    }
                )
            else:
                self.reservations[index] = Reservation(
                    **{**reservation.__dict__, "status": new_status}
                )

    async def _run_transaction(
        self,
        id_token: str,
        build_writes: Callable[[str], Awaitable[list[dict]]],
    ) -> None:
        for attempt in range(3):
            transaction = await self.firestore_client.begin_transaction(id_token)
            try:
                writes = await build_writes(transaction)
            except Exception as exc:
                try:
                    await self.firestore_client.rollback_transaction(
                        transaction, id_token
                    )
                except FirebaseRestError as rollback_error:
                    raise FirebaseRestError(
                        f"{exc}; não foi possível encerrar a transação: "
                        f"{rollback_error}",
                        rollback_error.status_code,
                    ) from rollback_error
                if (
                    isinstance(exc, FirebaseRestError)
                    and exc.status_code == 409
                    and attempt < 2
                ):
                    continue
                raise
            try:
                await self.firestore_client.commit_transaction(
                    writes, transaction, id_token
                )
                return
            except FirebaseRestError as exc:
                if exc.status_code == 409 and attempt < 2:
                    continue
                if exc.status_code != 409:
                    try:
                        await self.firestore_client.rollback_transaction(
                            transaction, id_token
                        )
                    except FirebaseRestError as rollback_error:
                        raise FirebaseRestError(
                            f"{exc}; não foi possível encerrar a transação: "
                            f"{rollback_error}",
                            rollback_error.status_code,
                        ) from rollback_error
                raise

    def _found_document(self, rows: list, document_name: str) -> dict:
        for row in rows:
            document = row.get("found")
            if document and document.get("name") == document_name:
                return document
        raise ReservationError(
            "Um documento necessário para a reserva não foi encontrado."
        )

    def _update_write(
        self,
        collection: str,
        document_id: str,
        fields: dict,
        field_paths: list[str],
    ) -> dict:
        return {
            "update": {
                "name": self.firestore_client.document_name(
                    collection, document_id
                ),
                "fields": fields,
            },
            "updateMask": {"fieldPaths": field_paths},
        }

    def _create_write(
        self, collection: str, document_id: str, fields: dict
    ) -> dict:
        return {
            "update": {
                "name": self.firestore_client.document_name(
                    collection, document_id
                ),
                "fields": fields,
            },
            "currentDocument": {"exists": False},
        }

    @staticmethod
    def _decode_reservation(document: dict) -> Reservation:
        fields = document.get("fields", {})
        return Reservation(
            id=document.get("name", "").rsplit("/", 1)[-1],
            user_id=ReservationController._string(fields, "userId"),
            user_name=ReservationController._string(fields, "userName"),
            pickup_spot_id=ReservationController._string(
                fields, "pickupSpotId"
            ),
            pickup_spot_name=ReservationController._string(
                fields, "pickupSpotName"
            ),
            pickup_spot_address=ReservationController._string(
                fields, "pickupSpotAddress"
            ),
            pickup_arrival_at=ReservationController._timestamp(
                fields.get("pickupArrivalAt", {}).get("timestampValue")
            ),
            pickup_departure_at=ReservationController._timestamp(
                fields.get("pickupDepartureAt", {}).get("timestampValue")
            ),
            item_ids=tuple(
                ReservationController._string_list(fields.get("itemIds", {}))
            ),
            item_type_names=tuple(
                ReservationController._string_list(
                    fields.get("itemTypeNames", {})
                )
            ),
            unit_prices=tuple(
                ReservationController._decimal_value(value)
                for value in ReservationController._array_values(
                    fields.get("unitPrices", {})
                )
            ),
            total_amount=ReservationController._decimal_field(
                fields.get("totalAmount")
            ),
            sale_type=ReservationController._string(fields, "saleType"),
            status=ReservationController._string(fields, "status"),
            created_at=ReservationController._timestamp(
                fields.get("createdAt", {}).get("timestampValue")
            ),
            cancelled_by=ReservationController._string(
                fields, "cancelledBy"
            )
            or None,
            cancelled_at=ReservationController._timestamp(
                fields.get("cancelledAt", {}).get("timestampValue")
            ),
            completed_at=ReservationController._timestamp(
                fields.get("completedAt", {}).get("timestampValue")
            ),
        )

    @staticmethod
    def _string(fields: dict, key: str) -> str:
        return fields.get(key, {}).get("stringValue", "")

    @staticmethod
    def _string_list(field: dict) -> list[str]:
        return [
            value.get("stringValue", "")
            for value in ReservationController._array_values(field)
        ]

    @staticmethod
    def _array_values(field: dict) -> list[dict]:
        return field.get("arrayValue", {}).get("values", [])

    @staticmethod
    def _decimal_field(field: dict | None) -> Decimal:
        if not field:
            return Decimal("0.00")
        value = field.get("doubleValue", field.get("integerValue", 0))
        return Decimal(str(value)).quantize(Decimal("0.01"))

    @staticmethod
    def _decimal_value(value: dict) -> Decimal:
        number = value.get("doubleValue", value.get("integerValue", 0))
        return Decimal(str(number)).quantize(Decimal("0.01"))

    @staticmethod
    def _price(
        item_type_fields: dict, *, use_promotional: bool
    ) -> Decimal:
        promotional_price = item_type_fields.get("promotionalPrice", {})
        regular_price = item_type_fields.get("regularPrice", {})
        value = None
        if use_promotional:
            value = promotional_price.get(
                "doubleValue", promotional_price.get("integerValue")
            )
        if value is None:
            value = regular_price.get(
                "doubleValue", regular_price.get("integerValue")
            )
        if value is None:
            raise ReservationError(
                "O sabor selecionado não tem um preço válido."
            )
        price = Decimal(str(value)).quantize(Decimal("0.01"))
        if not price.is_finite() or price <= 0:
            raise ReservationError(
                "O sabor selecionado não tem um preço válido."
            )
        return price

    @staticmethod
    def _timestamp(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if timestamp.tzinfo is None:
            return None
        return timestamp.astimezone(LOCAL_TIMEZONE)
