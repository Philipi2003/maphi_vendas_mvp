from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo

from maphi_api import MaphiApiClient

LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")
MINIMUM_PICKUP_WINDOW = timedelta(minutes=15)


@dataclass(frozen=True)
class PickupSpot:
    id: str
    name: str
    address: str
    arrival_at: datetime | None
    departure_at: datetime | None
    is_active: bool = True


class PickupSpotController:
    def __init__(self):
        self.api_client = MaphiApiClient()
        self.pickup_spots: list[PickupSpot] = []
        self.selected_pickup_spot_id: str | None = None

    @property
    def selected_pickup_spot(self) -> PickupSpot | None:
        return next(
            (
                pickup_spot
                for pickup_spot in self.pickup_spots
                if pickup_spot.id == self.selected_pickup_spot_id
            ),
            None,
        )

    @property
    def available_pickup_spots(self) -> list[PickupSpot]:
        now = datetime.now(LOCAL_TIMEZONE)
        return [
            pickup_spot
            for pickup_spot in self.pickup_spots
            if self.is_pickup_spot_available(pickup_spot, now=now)
        ]

    @staticmethod
    def is_pickup_spot_available(
        pickup_spot: PickupSpot, *, now: datetime | None = None
    ) -> bool:
        current_time = now or datetime.now(LOCAL_TIMEZONE)
        return (
            PickupSpotController._has_valid_window(pickup_spot)
            and pickup_spot.departure_at is not None
            and pickup_spot.departure_at
            > current_time + MINIMUM_PICKUP_WINDOW
        )

    async def load_active_pickup_spots(
        self, id_token: str | None = None
    ) -> None:
        rows = await self.api_client.list_pickup_spots(
            include_inactive=bool(id_token),
            id_token=id_token,
        )
        pickup_spots = []
        for row in rows:
            pickup_spot_id = str(row.get("id") or "")
            if not pickup_spot_id:
                continue
            name = row.get("name")
            if not name:
                continue
            pickup_spots.append(
                PickupSpot(
                    id=pickup_spot_id,
                    name=name,
                    address=str(row.get("address") or ""),
                    arrival_at=self._decode_timestamp(
                        row.get("window_start")
                    ),
                    departure_at=self._decode_timestamp(
                        row.get("window_end")
                    ),
                    is_active=bool(row.get("is_active", True)),
                )
            )
        seen_ids = {spot.id for spot in pickup_spots}
        self.pickup_spots = pickup_spots
        if self.selected_pickup_spot_id not in seen_ids:
            self.selected_pickup_spot_id = None

    def select_pickup_spot(
        self,
        pickup_spot_id: str | None,
        *,
        allow_unavailable: bool = False,
    ) -> None:
        if pickup_spot_id is None:
            self.selected_pickup_spot_id = None
            return
        eligible_spots = (
            self.pickup_spots
            if allow_unavailable
            else self.available_pickup_spots
        )
        if not any(spot.id == pickup_spot_id for spot in eligible_spots):
            raise ValueError("Selecione um local de retirada ativo.")
        self.selected_pickup_spot_id = pickup_spot_id

    async def create_pickup_spot(
        self,
        *,
        name: str,
        address: str,
        arrival_at: str,
        departure_at: str,
        id_token: str,
    ) -> PickupSpot:
        pickup_spot = self._build_pickup_spot(
            id="",
            name=name,
            address=address,
            arrival_at=arrival_at,
            departure_at=departure_at,
        )
        if not id_token:
            raise ValueError("Entre com uma conta de dono para criar o local.")
        row = await self.api_client.create_pickup_spot(
            self._api_fields(pickup_spot),
            id_token,
        )
        created = self._decode_row(row)
        self.pickup_spots.append(created)
        return created

    async def update_pickup_spot(
        self,
        *,
        pickup_spot_id: str,
        name: str,
        address: str,
        arrival_at: str,
        departure_at: str,
        id_token: str,
    ) -> PickupSpot:
        existing = next(
            (
                spot
                for spot in self.pickup_spots
                if spot.id == pickup_spot_id
            ),
            None,
        )
        if existing is None:
            raise ValueError("O local de retirada não foi encontrado.")
        updated = replace(
            self._build_pickup_spot(
                id=pickup_spot_id,
                name=name,
                address=address,
                arrival_at=arrival_at,
                departure_at=departure_at,
            ),
            is_active=existing.is_active,
        )
        if not id_token:
            raise ValueError("Entre com uma conta de dono para editar o local.")
        row = await self.api_client.update_pickup_spot(
            pickup_spot_id,
            self._api_fields(updated),
            id_token,
        )
        updated = self._decode_row(row)
        self.pickup_spots[self.pickup_spots.index(existing)] = updated
        return updated

    async def delete_pickup_spot(
        self, pickup_spot_id: str, id_token: str
    ) -> None:
        if not id_token:
            raise ValueError("Entre com uma conta de dono para excluir o local.")
        existing = next(
            (spot for spot in self.pickup_spots if spot.id == pickup_spot_id),
            None,
        )
        if existing is None:
            raise ValueError("O local de retirada não foi encontrado.")
        await self.api_client.delete_pickup_spot(pickup_spot_id, id_token)
        self.pickup_spots.remove(existing)
        if self.selected_pickup_spot_id == pickup_spot_id:
            self.selected_pickup_spot_id = None

    async def deactivate_pickup_spot(
        self, pickup_spot_id: str, id_token: str
    ) -> None:
        if not id_token:
            raise ValueError("Entre com uma conta de dono para remover o local.")
        existing = next(
            (spot for spot in self.pickup_spots if spot.id == pickup_spot_id),
            None,
        )
        if existing is None:
            raise ValueError("O local de retirada não foi encontrado.")
        if not existing.is_active:
            return
        await self.api_client.update_pickup_spot(
            pickup_spot_id,
            {"is_active": False},
            id_token,
        )
        self.pickup_spots[self.pickup_spots.index(existing)] = replace(
            existing, is_active=False
        )

    @staticmethod
    def _build_pickup_spot(
        *,
        id: str,
        name: str,
        address: str,
        arrival_at: str,
        departure_at: str,
    ) -> PickupSpot:
        normalized_name = name.strip()
        normalized_address = address.strip()
        if not normalized_name:
            raise ValueError("Informe o nome do local de retirada.")
        if not normalized_address:
            raise ValueError("Informe o endereço do local de retirada.")
        normalized_arrival = PickupSpotController._parse_local_datetime(
            arrival_at,
            "Informe a chegada no formato DD/MM/AAAA HH:MM.",
        )
        normalized_departure = PickupSpotController._parse_local_datetime(
            departure_at,
            "Informe a saída no formato DD/MM/AAAA HH:MM.",
        )
        if normalized_departure <= normalized_arrival:
            raise ValueError(
                "A saída deve ser posterior à chegada."
            )
        if normalized_departure - normalized_arrival < MINIMUM_PICKUP_WINDOW:
            raise ValueError(
                "A janela de retirada deve ter pelo menos 15 minutos."
            )
        return PickupSpot(
            id=id,
            name=normalized_name,
            address=normalized_address,
            arrival_at=normalized_arrival,
            departure_at=normalized_departure,
        )

    @staticmethod
    def _parse_local_datetime(value: str, error_message: str) -> datetime:
        normalized_value = value.strip()
        if re.fullmatch(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}", normalized_value) is None:
            raise ValueError(error_message)
        try:
            return datetime.strptime(
                normalized_value, "%d/%m/%Y %H:%M"
            ).replace(tzinfo=LOCAL_TIMEZONE)
        except ValueError as exc:
            raise ValueError(error_message) from exc

    @staticmethod
    def _decode_timestamp(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if timestamp.tzinfo is None:
            return None
        return timestamp.astimezone(LOCAL_TIMEZONE)

    @staticmethod
    def _api_fields(pickup_spot: PickupSpot) -> dict[str, object]:
        if pickup_spot.arrival_at is None or pickup_spot.departure_at is None:
            raise ValueError("O local precisa ter datas e horários completos.")
        return {
            "name": pickup_spot.name,
            "address": pickup_spot.address,
            "window_start": pickup_spot.arrival_at.astimezone(
                timezone.utc
            ).isoformat().replace("+00:00", "Z"),
            "window_end": pickup_spot.departure_at.astimezone(
                timezone.utc
            ).isoformat().replace("+00:00", "Z"),
            "is_active": pickup_spot.is_active,
        }

    @classmethod
    def _decode_row(cls, row: dict) -> PickupSpot:
        return PickupSpot(
            id=str(row["id"]),
            name=str(row.get("name") or ""),
            address=str(row.get("address") or ""),
            arrival_at=cls._decode_timestamp(row.get("window_start")),
            departure_at=cls._decode_timestamp(row.get("window_end")),
            is_active=bool(row.get("is_active", True)),
        )

    @staticmethod
    def _has_valid_window(pickup_spot: PickupSpot) -> bool:
        return (
            pickup_spot.is_active
            and pickup_spot.arrival_at is not None
            and pickup_spot.departure_at is not None
            and pickup_spot.departure_at > pickup_spot.arrival_at
            and pickup_spot.departure_at - pickup_spot.arrival_at
            >= MINIMUM_PICKUP_WINDOW
        )
