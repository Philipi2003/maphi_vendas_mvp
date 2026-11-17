from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import re
import uuid
from zoneinfo import ZoneInfo

from firebase_rest import FirebaseFirestoreClient

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
        self.firestore_client = FirebaseFirestoreClient()
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
        rows = await self.firestore_client.list_pickup_spots(
            include_inactive=bool(id_token),
            id_token=id_token,
        )
        pickup_spots = []
        seen_ids = set()
        for row in rows:
            document = row.get("document")
            if not document:
                continue
            pickup_spot_id = document.get("name", "").rsplit("/", 1)[-1]
            if not pickup_spot_id or pickup_spot_id in seen_ids:
                continue
            fields = document.get("fields", {})
            name = fields.get("name", {}).get("stringValue", "")
            if not name:
                continue
            pickup_spots.append(
                PickupSpot(
                    id=pickup_spot_id,
                    name=name,
                    address=fields.get("address", {}).get("stringValue", ""),
                    arrival_at=self._decode_timestamp(
                        fields.get("arrivalAt", {}).get("timestampValue")
                    ),
                    departure_at=self._decode_timestamp(
                        fields.get("departureAt", {}).get("timestampValue")
                    ),
                    is_active=fields.get("isActive", {}).get(
                        "booleanValue", True
                    ),
                )
            )
            seen_ids.add(pickup_spot_id)
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
            id=uuid.uuid4().hex,
            name=name,
            address=address,
            arrival_at=arrival_at,
            departure_at=departure_at,
        )
        if not id_token:
            raise ValueError("Entre com uma conta de dono para criar o local.")
        fields = self._firestore_fields(pickup_spot)
        fields["createdAt"] = {
            "timestampValue": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        }
        await self.firestore_client.create_pickup_spot(
            pickup_spot.id, fields, id_token
        )
        self.pickup_spots.append(pickup_spot)
        return pickup_spot

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
        fields = self._firestore_fields(updated)
        fields["isActive"] = {"booleanValue": existing.is_active}
        await self.firestore_client.update_document(
            "pickupSpots",
            pickup_spot_id,
            fields,
            [
                "name",
                "address",
                "arrivalAt",
                "departureAt",
                "arrivalTime",
                "departureTime",
                "timeWindow",
                "isActive",
            ],
            id_token,
        )
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
        await self.firestore_client.delete_document(
            "pickupSpots", pickup_spot_id, id_token
        )
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
        await self.firestore_client.update_document(
            "pickupSpots",
            pickup_spot_id,
            {"isActive": {"booleanValue": False}},
            ["isActive"],
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
    def _firestore_fields(pickup_spot: PickupSpot) -> dict:
        if pickup_spot.arrival_at is None or pickup_spot.departure_at is None:
            raise ValueError("O local precisa ter datas e horários completos.")
        return {
            "name": {"stringValue": pickup_spot.name},
            "address": {"stringValue": pickup_spot.address},
            "arrivalAt": {
                "timestampValue": pickup_spot.arrival_at.astimezone(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
            },
            "departureAt": {
                "timestampValue": pickup_spot.departure_at.astimezone(
                    timezone.utc
                )
                .isoformat()
                .replace("+00:00", "Z")
            },
            "isActive": {"booleanValue": pickup_spot.is_active},
        }

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
