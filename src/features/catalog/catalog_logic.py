from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
import math
from pathlib import PurePath
import uuid

from firebase_rest import (
    FirebaseRestError,
    FirebaseStorageClient,
)
from maphi_api import MaphiApiClient

MAX_STOCK_BATCH_UNITS = 500


class ItemTypeImageCleanupError(RuntimeError):
    pass


class ItemTypeNameSyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class Cake:
    id: str
    name: str
    description: str
    stock: int
    color: str
    image_url: str = ""
    is_custom_order_only: bool = False
    regular_price: float | None = None
    promotional_price: float | None = None
    is_active: bool = True
    reserved_stock: int = 0


class CatalogController:
    def __init__(self, cakes: list[Cake] | None = None):
        self.cakes = list(cakes or [])
        self.quantities = {cake.id: 0 for cake in self.cakes}
        self.active_filter = "Todos"
        self.search_query = ""
        self.api_client = MaphiApiClient()
        self.storage_client = FirebaseStorageClient()

    async def load_item_types(
        self,
        *,
        id_token: str | None = None,
        include_inactive: bool = False,
    ) -> None:
        rows = await self.api_client.list_item_types(
            include_inactive=include_inactive,
            id_token=id_token,
        )

        colors = ("#F0E2D6", "#F4E9D5", "#F3E4E6", "#E9EEDC", "#F2E6D5")
        cakes = []
        seen_ids = set()

        for row in rows:
            item_type_id = str(row.get("id") or "")
            if not item_type_id or item_type_id in seen_ids:
                continue

            cake = Cake(
                id=item_type_id,
                name=str(row.get("name") or ""),
                description=str(row.get("description") or ""),
                stock=int(row.get("stock") or 0),
                color=colors[len(cakes) % len(colors)],
                image_url=str(row.get("image_url") or ""),
                is_custom_order_only=bool(row.get("is_custom_order_only")),
                regular_price=(
                    float(row["regular_price"])
                    if row.get("regular_price") is not None
                    else None
                ),
                promotional_price=(
                    float(row["promotional_price"])
                    if row.get("promotional_price") is not None
                    else None
                ),
                is_active=bool(row.get("is_active")),
                reserved_stock=int(row.get("reserved_stock") or 0),
            )
            if cake.name:
                cakes.append(cake)
                seen_ids.add(cake.id)

        previous_quantities = self.quantities
        self.cakes = cakes
        self.quantities = {
            cake.id: min(previous_quantities.get(cake.id, 0), cake.stock)
            for cake in cakes
        }

    def hide_inactive_item_types(self) -> None:
        self.cakes = [cake for cake in self.cakes if cake.is_active]
        self.quantities = {
            cake.id: self.quantities.get(cake.id, 0) for cake in self.cakes
        }

    def set_cakes(self, cakes: list[Cake]) -> None:
        previous_quantities = self.quantities
        self.cakes = list(cakes)
        self.quantities = {
            cake.id: min(cake.stock, previous_quantities.get(cake.id, 0))
            for cake in self.cakes
        }

    @property
    def selected_count(self) -> int:
        return sum(self.quantities.values())

    @property
    def filtered_cakes(self) -> list[Cake]:
        query = self.search_query.casefold()
        return [
            cake
            for cake in self.cakes
            if (
                self.active_filter == "Todos"
                or (self.active_filter == "Disponíveis" and cake.stock > 0)
                or (self.active_filter == "Esgotados" and cake.stock == 0)
            )
            and query in cake.name.casefold()
        ]

    def set_filter(self, value: str) -> None:
        self.active_filter = value

    def set_search_query(self, value: str) -> None:
        self.search_query = value.strip()

    def change_quantity(self, cake_id: str, amount: int) -> None:
        cake = next(cake for cake in self.cakes if cake.id == cake_id)
        self.quantities[cake_id] = max(
            0, min(cake.stock, self.quantities[cake_id] + amount)
        )

    async def add_stock(
        self, quantities: dict[str, int], id_token: str
    ) -> int:
        if not id_token:
            raise ValueError("Entre com uma conta de dono para registrar a produção.")
        if not quantities:
            raise ValueError("Adicione ao menos um sabor à produção.")

        cakes_by_id = {cake.id: cake for cake in self.cakes}
        for item_type_id, quantity in quantities.items():
            if item_type_id not in cakes_by_id:
                raise ValueError("Um dos sabores selecionados não existe mais.")
            if type(quantity) is not int or quantity <= 0:
                raise ValueError("A quantidade de cada sabor deve ser um inteiro positivo.")

        total_units = sum(quantities.values())
        if total_units > MAX_STOCK_BATCH_UNITS:
            raise ValueError(
                f"Cada inserção pode conter no máximo {MAX_STOCK_BATCH_UNITS} bolos."
            )

        stock_by_type: dict[str, int] = {}
        entries = []
        for item_type_id, quantity in quantities.items():
            stock_by_type[item_type_id] = quantity
            entries.append(
                {"item_type_id": item_type_id, "quantity": quantity}
            )

        await self.api_client.create_items(
            entries,
            id_token,
        )
        self.cakes = [
            replace(cake, stock=cake.stock + stock_by_type.get(cake.id, 0))
            for cake in self.cakes
        ]
        return total_units

    async def remove_available_units(
        self, item_type_id: str, quantity: int, id_token: str
    ) -> int:
        if not id_token:
            raise ValueError("Entre com uma conta de dono para remover estoque.")
        cake = next(
            (cake for cake in self.cakes if cake.id == item_type_id), None
        )
        if cake is None:
            raise ValueError("O sabor não foi encontrado no catálogo.")
        if type(quantity) is not int or not 1 <= quantity <= cake.stock:
            raise ValueError(
                "A quantidade deve estar entre 1 e o total não reservado."
            )
        removed = await self.api_client.remove_items(
            item_type_id, quantity, id_token
        )

        self.cakes = [
            replace(cake, stock=max(0, cake.stock - removed))
            if cake.id == item_type_id
            else cake
            for cake in self.cakes
        ]
        self.quantities[item_type_id] = min(
            self.quantities.get(item_type_id, 0), max(0, cake.stock - removed)
        )
        return removed

    async def create_item_type(
        self,
        *,
        name: str,
        description: str,
        regular_price: str,
        promotional_price: str,
        is_custom_order_only: bool,
        is_active: bool,
        id_token: str,
        user_id: str,
        image_data: bytes | None = None,
        image_filename: str | None = None,
        image_content_type: str | None = None,
    ) -> Cake:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Informe o nome do sabor.")
        if not id_token:
            raise ValueError("É necessário entrar com uma conta de dono.")
        if not user_id:
            raise ValueError("Não foi possível identificar a conta de dono.")

        regular_amount = self._parse_price(regular_price, "Informe o preço normal.")
        promotional_amount = (
            self._parse_price(promotional_price, "Informe um preço promocional válido.")
            if promotional_price.strip()
            else None
        )
        if promotional_amount is not None and promotional_amount >= regular_amount:
            raise ValueError("O preço promocional deve ser menor que o preço normal.")

        image_url = await self._resolve_image_url(
            image_data=image_data,
            image_filename=image_filename,
            image_content_type=image_content_type,
            existing_image_url="",
            id_token=id_token,
            user_id=user_id,
        )

        row = await self.api_client.create_item_type(
            self._api_item_type_fields(
                normalized_name=normalized_name,
                description=description,
                image_url=image_url,
                regular_amount=regular_amount,
                promotional_amount=promotional_amount,
                is_custom_order_only=is_custom_order_only,
                is_active=is_active,
            ),
            id_token,
        )
        item_type_id = str(row["id"])

        colors = ("#F0E2D6", "#F4E9D5", "#F3E4E6", "#E9EEDC", "#F2E6D5")
        cake = Cake(
            id=item_type_id,
            name=normalized_name,
            description=description.strip(),
            stock=0,
            color=colors[len(self.cakes) % len(colors)],
            image_url=image_url,
            is_custom_order_only=is_custom_order_only,
            regular_price=float(regular_amount),
            promotional_price=(
                float(promotional_amount)
                if promotional_amount is not None
                else None
            ),
            is_active=is_active,
        )
        self.cakes.append(cake)
        self.quantities[cake.id] = 0
        return cake

    async def update_item_type(
        self,
        *,
        item_type_id: str,
        name: str,
        description: str,
        regular_price: str,
        promotional_price: str,
        is_custom_order_only: bool,
        is_active: bool,
        id_token: str,
        user_id: str,
        image_data: bytes | None = None,
        image_filename: str | None = None,
        image_content_type: str | None = None,
    ) -> Cake:
        if not id_token or not user_id:
            raise ValueError("É necessário entrar com uma conta de dono.")
        existing = next(
            (cake for cake in self.cakes if cake.id == item_type_id), None
        )
        if existing is None:
            raise ValueError("O sabor não foi encontrado no catálogo.")

        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Informe o nome do sabor.")
        regular_amount = self._parse_price(regular_price, "Informe o preço normal.")
        promotional_amount = (
            self._parse_price(promotional_price, "Informe um preço promocional válido.")
            if promotional_price.strip()
            else None
        )
        if promotional_amount is not None and promotional_amount >= regular_amount:
            raise ValueError("O preço promocional deve ser menor que o preço normal.")

        image_url = await self._resolve_image_url(
            image_data=image_data,
            image_filename=image_filename,
            image_content_type=image_content_type,
            existing_image_url=existing.image_url,
            id_token=id_token,
            user_id=user_id,
        )
        await self.api_client.update_item_type(
            item_type_id,
            self._api_item_type_fields(
                normalized_name=normalized_name,
                description=description,
                image_url=image_url,
                regular_amount=regular_amount,
                promotional_amount=promotional_amount,
                is_custom_order_only=is_custom_order_only,
                is_active=is_active,
            ),
            id_token,
        )

        updated = Cake(
            id=item_type_id,
            name=normalized_name,
            description=description.strip(),
            stock=existing.stock,
            color=existing.color,
            image_url=image_url,
            is_custom_order_only=is_custom_order_only,
            regular_price=float(regular_amount),
            promotional_price=(
                float(promotional_amount)
                if promotional_amount is not None
                else None
            ),
            is_active=is_active,
            reserved_stock=existing.reserved_stock,
        )
        index = self.cakes.index(existing)
        self.cakes[index] = updated
        image_cleanup_error = None
        if image_url != existing.image_url and existing.image_url:
            try:
                await self.storage_client.delete_image(
                    existing.image_url, id_token
                )
            except FirebaseRestError as exc:
                image_cleanup_error = exc

        if image_cleanup_error is not None:
            raise ItemTypeImageCleanupError(
                "O sabor foi atualizado com a nova foto, mas não foi "
                f"possível excluir a foto anterior: {image_cleanup_error}"
            ) from image_cleanup_error
        return updated

    async def can_delete_item_type(self, item_type_id: str, id_token: str) -> bool:
        rows = await self.api_client.list_items(
            id_token=id_token,
            item_type_id=item_type_id,
            limit=1,
        )
        return not rows

    async def delete_item_type(
        self, item_type_id: str, id_token: str
    ) -> None:
        cake = next(
            (cake for cake in self.cakes if cake.id == item_type_id), None
        )
        await self.api_client.delete_item_type(item_type_id, id_token)
        self.cakes = [cake for cake in self.cakes if cake.id != item_type_id]
        self.quantities.pop(item_type_id, None)
        if cake and cake.image_url:
            await self.storage_client.delete_image(cake.image_url, id_token)

    async def _resolve_image_url(
        self,
        *,
        image_data: bytes | None,
        image_filename: str | None,
        image_content_type: str | None,
        existing_image_url: str,
        id_token: str,
        user_id: str,
    ) -> str:
        if image_data is None:
            return existing_image_url
        if not image_filename or image_content_type not in {
            "image/jpeg",
            "image/png",
            "image/webp",
        }:
            raise ValueError("Selecione uma foto JPG, PNG ou WEBP.")
        if len(image_data) > 5 * 1024 * 1024:
            raise ValueError("A foto deve ter no máximo 5 MB.")
        object_name = (
            f"itemTypes/{user_id}/{uuid.uuid4().hex}"
            f"{PurePath(image_filename).suffix.lower()}"
        )
        return await self.storage_client.upload_image(
            object_name, image_data, image_content_type, id_token
        )

    @staticmethod
    def _api_item_type_fields(
        *,
        normalized_name: str,
        description: str,
        image_url: str,
        regular_amount: Decimal,
        promotional_amount: Decimal | None,
        is_custom_order_only: bool,
        is_active: bool,
    ) -> dict[str, object]:
        return {
            "name": normalized_name,
            "description": description.strip() or None,
            "image_url": image_url or None,
            "regular_price": float(regular_amount),
            "promotional_price": (
                float(promotional_amount)
                if promotional_amount is not None
                else None
            ),
            "is_custom_order_only": is_custom_order_only,
            "is_active": is_active,
        }

    @staticmethod
    def _parse_price(value: str, error_message: str) -> Decimal:
        try:
            amount = Decimal(value.strip().replace(",", "."))
            amount = amount.quantize(Decimal("0.01"))
        except InvalidOperation as exc:
            raise ValueError(error_message) from exc
        if (
            not amount.is_finite()
            or amount <= 0
            or not math.isfinite(float(amount))
        ):
            raise ValueError(error_message)
        return amount
