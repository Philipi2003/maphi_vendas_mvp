from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from features.pickup_spots.pickup_spots_logic import (
    LOCAL_TIMEZONE,
)
from maphi_api import MaphiApiClient

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
        self.api_client = MaphiApiClient()
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
        rows = await self.api_client.list_reservations(
            id_token=id_token,
            is_owner=is_owner,
            pickup_spot_id=pickup_spot_id if is_owner else None,
        )
        reservations = [self._decode_reservation(row) for row in rows]
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
        id_token: str,
    ) -> Reservation:
        if not id_token:
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

        payload = {
            "pickup_spot_id": pickup_spot_id,
            "items": [
                {"item_type_id": item_type_id, "quantity": quantity}
                for item_type_id, quantity in selected.items()
            ],
        }
        row = await self.api_client.create_reservation(payload, id_token)
        reservation = self._decode_reservation(row)
        self.reservations.insert(0, reservation)
        return reservation

    async def cancel_reservation(
        self,
        reservation_id: str,
        *,
        id_token: str,
    ) -> None:
        row = await self.api_client.cancel_reservation(reservation_id, id_token)
        updated = self._decode_reservation(row)
        self._replace_reservation(updated)

    async def complete_reservation(
        self,
        reservation_id: str,
        *,
        id_token: str,
        is_owner: bool,
    ) -> None:
        if not is_owner:
            raise ReservationError("Apenas o dono pode confirmar a venda.")
        row = await self.api_client.complete_reservation(
            reservation_id, id_token
        )
        self._replace_reservation(self._decode_reservation(row))

    async def delete_reservation(
        self, reservation_id: str, *, id_token: str, is_owner: bool
    ) -> None:
        if not is_owner:
            raise ReservationError("Apenas o dono pode apagar reservas.")

        await self.api_client.delete_reservation(reservation_id, id_token)
        self.reservations = [
            item for item in self.reservations if item.id != reservation_id
        ]

    async def cancel_active_for_pickup(
        self, pickup_spot_id: str, *, id_token: str
    ) -> int:
        if not id_token:
            raise ReservationError("Entre na conta de dono para cancelar reservas.")
        rows = await self.api_client.list_reservations(
            id_token=id_token,
            pickup_spot_id=pickup_spot_id,
            is_owner=True,
        )
        active_ids = [
            str(row["id"])
            for row in rows
            if row.get("status") == RESERVATION_ACTIVE
        ]
        for reservation_id in active_ids:
            await self.api_client.cancel_reservation(reservation_id, id_token)
        return len(active_ids)

    def _replace_reservation(self, updated: Reservation) -> None:
        for index, reservation in enumerate(self.reservations):
            if reservation.id == updated.id:
                self.reservations[index] = updated
                return

    @staticmethod
    def _decode_reservation(document: dict) -> Reservation:
        items = document.get("items")
        if not isinstance(items, list):
            raise ReservationError("A API retornou uma reserva inválida.")
        item_ids = []
        item_type_names = []
        unit_prices = []
        for item in items:
            if not isinstance(item, dict):
                raise ReservationError("A API retornou uma reserva inválida.")
            item_ids.append(str(item.get("item_id") or ""))
            item_type_names.append(str(item.get("item_type_name") or ""))
            unit_prices.append(
                Decimal(str(item.get("unit_price") or 0)).quantize(
                    Decimal("0.01")
                )
            )
        return Reservation(
            id=str(document.get("id") or ""),
            user_id=str(document.get("user_id") or ""),
            user_name=str(document.get("user_name") or ""),
            pickup_spot_id=str(document.get("pickup_spot_id") or ""),
            pickup_spot_name=str(document.get("pickup_spot_name") or ""),
            pickup_spot_address=str(
                document.get("pickup_spot_address") or ""
            ),
            pickup_arrival_at=ReservationController._timestamp(
                document.get("window_start")
            ),
            pickup_departure_at=ReservationController._timestamp(
                document.get("window_end")
            ),
            item_ids=tuple(item_ids),
            item_type_names=tuple(item_type_names),
            unit_prices=tuple(unit_prices),
            total_amount=Decimal(
                str(document.get("total_amount") or 0)
            ).quantize(Decimal("0.01")),
            sale_type=str(document.get("sale_type") or ""),
            status=str(document.get("status") or ""),
            created_at=ReservationController._timestamp(
                document.get("created_at")
            ),
            cancelled_by=document.get("cancelled_by"),
            cancelled_at=ReservationController._timestamp(
                document.get("cancelled_at")
            ),
            completed_at=ReservationController._timestamp(
                document.get("completed_at")
            ),
        )

    @staticmethod
    def _timestamp(value: str | datetime | None) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            timestamp = value
        else:
            try:
                timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        if timestamp.tzinfo is None:
            return None
        return timestamp.astimezone(LOCAL_TIMEZONE)
