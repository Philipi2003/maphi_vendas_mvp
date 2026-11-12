from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import math
from pathlib import PurePath
import uuid

from firebase_rest import (
    FirebaseFirestoreClient,
    FirebaseRestError,
    FirebaseStorageClient,
    MAX_FIRESTORE_BATCH_WRITES,
)

MAX_STOCK_BATCH_UNITS = MAX_FIRESTORE_BATCH_WRITES


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


class CatalogController:
    def __init__(self, cakes: list[Cake] | None = None):
        self.cakes = list(cakes or [])
        self.quantities = {cake.id: 0 for cake in self.cakes}
        self.active_filter = "Todos"
        self.search_query = ""
        self.firestore_client = FirebaseFirestoreClient()
        self.storage_client = FirebaseStorageClient()

    async def load_item_types(
        self,
        *,
        id_token: str | None = None,
        include_inactive: bool = False,
    ) -> None:
        rows = (
            await self.firestore_client.list_item_types(id_token)
            if include_inactive and id_token
            else await self.firestore_client.list_active_item_types()
        )
        available_items = await self.firestore_client.list_available_items()
        stock_counts: dict[str, int] = {}
        for row in available_items:
            document = row.get("document")
            if not document:
                continue
            fields = document.get("fields", {})
            if fields.get("status", {}).get("stringValue") != "DISPONIVEL":
                continue
            item_type_id = fields.get("itemTypeId", {}).get("stringValue", "")
            if item_type_id:
                stock_counts[item_type_id] = (
                    stock_counts.get(item_type_id, 0) + 1
                )

        colors = ("#F0E2D6", "#F4E9D5", "#F3E4E6", "#E9EEDC", "#F2E6D5")
        cakes = []
        seen_ids = set()

        for row in rows:
            document = row.get("document")
            if not document:
                continue
            item_type_id = document.get("name", "").rsplit("/", 1)[-1]
            if not item_type_id or item_type_id in seen_ids:
                continue

            fields = document.get("fields", {})
            cake = Cake(
                id=item_type_id,
                name=fields.get("name", {}).get("stringValue", ""),
                description=fields.get("description", {}).get(
                    "stringValue", ""
                ),
                stock=stock_counts.get(item_type_id, 0),
                color=colors[len(cakes) % len(colors)],
                image_url=fields.get("imageUrl", {}).get("stringValue", ""),
                is_custom_order_only=fields.get(
                    "isCustomOrderOnly", {}
                ).get("booleanValue", False),
                regular_price=self._firestore_number(fields.get("regularPrice")),
                promotional_price=self._firestore_number(
                    fields.get("promotionalPrice")
                ),
                is_active=fields.get("isActive", {}).get("booleanValue", False),
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

        created_at = (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )
        documents = []
        stock_by_type: dict[str, int] = {}
        for item_type_id, quantity in quantities.items():
            cake = cakes_by_id[item_type_id]
            stock_by_type[item_type_id] = quantity
            fields = {
                "itemTypeId": {"stringValue": cake.id},
                "itemTypeName": {"stringValue": cake.name},
                "status": {"stringValue": "DISPONIVEL"},
                "createdAt": {"timestampValue": created_at},
            }
            documents.extend(
                (uuid.uuid4().hex, fields.copy()) for _ in range(quantity)
            )

        await self.firestore_client.create_documents_atomically(
            "items", documents, id_token
        )
        self.cakes = [
            replace(cake, stock=cake.stock + stock_by_type.get(cake.id, 0))
            for cake in self.cakes
        ]
        return total_units

    async def remove_available_unit(
        self, item_type_id: str, id_token: str
    ) -> None:
        if not id_token:
            raise ValueError("Entre com uma conta de dono para remover estoque.")
        cake = next(
            (cake for cake in self.cakes if cake.id == item_type_id), None
        )
        if cake is None:
            raise ValueError("O sabor não foi encontrado no catálogo.")

        transaction = await self.firestore_client.begin_transaction(id_token)
        try:
            rows = await self.firestore_client.run_query_in_transaction(
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
                                        "field": {"fieldPath": "status"},
                                        "op": "EQUAL",
                                        "value": {
                                            "stringValue": "DISPONIVEL"
                                        },
                                    }
                                },
                            ],
                        }
                    },
                    "limit": 1,
                },
                transaction,
                id_token,
            )
            available = next(
                (
                    row["document"]
                    for row in rows
                    if row.get("document", {})
                    .get("fields", {})
                    .get("status", {})
                    .get("stringValue")
                    == "DISPONIVEL"
                ),
                None,
            )
            if available is None:
                await self.firestore_client.rollback_transaction(
                    transaction, id_token
                )
                raise ValueError(
                    "Não há unidades não reservadas deste sabor para remover."
                )

            await self.firestore_client.commit_transaction(
                [{"delete": available["name"]}],
                transaction,
                id_token,
            )
        except FirebaseRestError as exc:
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

        self.cakes = [
            replace(cake, stock=max(0, cake.stock - 1))
            if cake.id == item_type_id
            else cake
            for cake in self.cakes
        ]
        self.quantities[item_type_id] = min(
            self.quantities.get(item_type_id, 0), max(0, cake.stock - 1)
        )

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

        item_type_id = uuid.uuid4().hex
        fields = self._item_type_fields(
            normalized_name=normalized_name,
            description=description,
            image_url=image_url,
            regular_amount=regular_amount,
            promotional_amount=promotional_amount,
            is_custom_order_only=is_custom_order_only,
            is_active=is_active,
        )
        fields["createdAt"] = {
            "timestampValue": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        }
        await self.firestore_client.create_document(
            "itemTypes", item_type_id, fields, id_token
        )

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
        fields = self._item_type_fields(
            normalized_name=normalized_name,
            description=description,
            image_url=image_url,
            regular_amount=regular_amount,
            promotional_amount=promotional_amount,
            is_custom_order_only=is_custom_order_only,
            is_active=is_active,
        )
        await self.firestore_client.update_document(
            "itemTypes",
            item_type_id,
            fields,
            [
                "name",
                "description",
                "imageUrl",
                "regularPrice",
                "promotionalPrice",
                "isCustomOrderOnly",
                "isActive",
            ],
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
        )
        index = self.cakes.index(existing)
        self.cakes[index] = updated
        name_sync_error = None
        try:
            await self._synchronize_item_type_names(
                item_type_id, normalized_name, id_token
            )
        except FirebaseRestError as exc:
            name_sync_error = exc

        image_cleanup_error = None
        if image_url != existing.image_url and existing.image_url:
            try:
                await self.storage_client.delete_image(
                    existing.image_url, id_token
                )
            except FirebaseRestError as exc:
                image_cleanup_error = exc

        if name_sync_error is not None:
            message = (
                "O sabor foi atualizado, mas não foi possível sincronizar o "
                f"nome nas unidades existentes: {name_sync_error}"
            )
            if image_cleanup_error is not None:
                message += (
                    " A foto anterior também não pôde ser excluída: "
                    f"{image_cleanup_error}"
                )
            raise ItemTypeNameSyncError(message) from name_sync_error
        if image_cleanup_error is not None:
            raise ItemTypeImageCleanupError(
                "O sabor foi atualizado com a nova foto, mas não foi "
                f"possível excluir a foto anterior: {image_cleanup_error}"
            ) from image_cleanup_error
        return updated

    async def _synchronize_item_type_names(
        self, item_type_id: str, item_type_name: str, id_token: str
    ) -> None:
        rows = await self.firestore_client.list_items_for_item_type(
            item_type_id, id_token
        )
        documents = []
        for row in rows:
            document = row.get("document")
            if not document:
                continue
            document_id = document.get("name", "").rsplit("/", 1)[-1]
            if not document_id:
                continue
            current_name = (
                document.get("fields", {})
                .get("itemTypeName", {})
                .get("stringValue")
            )
            if current_name != item_type_name:
                documents.append(
                    (
                        document_id,
                        {"itemTypeName": {"stringValue": item_type_name}},
                    )
                )

        for offset in range(0, len(documents), MAX_FIRESTORE_BATCH_WRITES):
            batch = documents[offset : offset + MAX_FIRESTORE_BATCH_WRITES]
            await self.firestore_client.update_documents_atomically(
                "items",
                batch,
                ["itemTypeName"],
                id_token,
            )

    async def can_delete_item_type(self, item_type_id: str, id_token: str) -> bool:
        return not await self.firestore_client.has_items_for_item_type(
            item_type_id, id_token
        )

    async def delete_item_type(
        self, item_type_id: str, id_token: str
    ) -> None:
        if await self.firestore_client.has_items_for_item_type(
            item_type_id, id_token
        ):
            raise ValueError(
                "Não é possível excluir este sabor porque há bolos associados no estoque. "
                "Inative o sabor para ocultá-lo do catálogo."
            )
        cake = next(
            (cake for cake in self.cakes if cake.id == item_type_id), None
        )
        if cake and cake.image_url:
            await self.storage_client.delete_image(cake.image_url, id_token)
        await self.firestore_client.delete_document(
            "itemTypes", item_type_id, id_token
        )
        self.cakes = [cake for cake in self.cakes if cake.id != item_type_id]
        self.quantities.pop(item_type_id, None)

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
    def _item_type_fields(
        *,
        normalized_name: str,
        description: str,
        image_url: str,
        regular_amount: Decimal,
        promotional_amount: Decimal | None,
        is_custom_order_only: bool,
        is_active: bool,
    ) -> dict:
        fields = {
            "name": {"stringValue": normalized_name},
            "description": {"stringValue": description.strip()},
            "imageUrl": {"stringValue": image_url},
            "regularPrice": {"doubleValue": float(regular_amount)},
            "isCustomOrderOnly": {"booleanValue": is_custom_order_only},
            "isActive": {"booleanValue": is_active},
        }
        if promotional_amount is not None:
            fields["promotionalPrice"] = {
                "doubleValue": float(promotional_amount)
            }
        return fields

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

    @staticmethod
    def _firestore_number(field: dict | None) -> float | None:
        if not field:
            return None
        value = field.get("doubleValue", field.get("integerValue"))
        return float(value) if value is not None else None
