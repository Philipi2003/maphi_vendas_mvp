from decimal import Decimal

import flet as ft

from app_config import INK, MUTED, configure_page
from features.auth.auth_logic import AuthController, FirebaseAuthError
from features.auth.auth_view import AuthView
from features.catalog.catalog_logic import CatalogController
from features.catalog.catalog_view import CatalogView
from features.inventory.production_view import ProductionFormView
from features.pickup_spots.pickup_spots_logic import (
    PickupSpot,
    PickupSpotController,
)
from features.pickup_spots.pickup_spots_view import PickupSpotFormView
from features.reservations.reservation_logic import (
    MAX_UNITS_PER_RESERVATION,
    ReservationController,
    ReservationError,
)
from features.reservations.reservation_view import ReservationView
from firebase_rest import FirebaseRestError


class MaphiApplication:
    def __init__(self, page: ft.Page):
        self.page = page
        configure_page(page)
        self.auth_session_storage = ft.SharedPreferences()
        self.auth_controller = AuthController(
            session_storage=self.auth_session_storage
        )
        self.catalog_controller = CatalogController()
        self.reservation_controller = ReservationController()
        self.reservation_filter_spot_id: str | None = None
        self.is_creating_reservation = False
        self.pickup_spot_controller = PickupSpotController()
        self.auth_view = AuthView(
            page=page,
            controller=self.auth_controller,
            on_message=self.show_message,
            on_notice=self.show_notice,
            on_auth_changed=self.refresh_owner_access,
            on_mobile_open=self.hide_catalog,
            on_mobile_close=self.show_catalog,
        )
        self.pickup_spot_form_view = PickupSpotFormView(
            page=page,
            on_create=self.create_pickup_spot,
            on_update=self.update_pickup_spot,
            on_notice=self.show_notice,
            on_message=self.show_message,
        )
        self.production_form_view = ProductionFormView(
            page=page,
            on_submit=self.add_stock,
            on_notice=self.show_notice,
            on_message=self.show_message,
        )
        self.reservation_view = ReservationView(
            page=page,
            on_back=self.show_catalog,
            on_cancel=self.cancel_reservation,
            on_complete=self.complete_reservation,
            on_delete=self.delete_reservation,
            on_filter=self.filter_reservations,
            on_refresh=self.load_reservations,
            on_message=self.show_message,
        )
        self.catalog_view = CatalogView(
            page=page,
            controller=self.catalog_controller,
            pickup_spot_controller=self.pickup_spot_controller,
            account_button=self.auth_view.account_button,
            on_reserve=self.start_reservation,
            on_add_stock=self.open_production_form,
            on_create_pickup_spot=self.open_pickup_spot_form,
            on_edit_pickup_spot=self.edit_pickup_spot,
            on_delete_pickup_spot=self.delete_pickup_spot,
            on_create_item_type=self.create_item_type,
            on_update_item_type=self.update_item_type,
            on_delete_item_type=self.delete_item_type,
            on_check_item_type_inventory=self.check_item_type_inventory,
            on_notice=self.show_notice,
            on_message=self.show_message,
            on_reservations=self.open_reservations,
            on_remove_stock=self.remove_available_stock,
        )
        self.root = ft.Stack(
            controls=[
                self.catalog_view.root,
                self.auth_view.root,
                self.reservation_view.root,
            ],
            expand=True,
        )
        page.add(self.root)
        page.run_task(self.initialize)
        if page.pyodide:
            page.run_task(self.prepare_google_auth)

    async def initialize(self) -> None:
        restored_session = False
        try:
            restored_session = await self.auth_controller.restore_session()
        except FirebaseAuthError as exc:
            self.show_notice(str(exc))

        is_owner = self.auth_controller.is_owner
        self.catalog_view.set_account_state(
            is_authenticated=self.auth_controller.is_authenticated,
            is_owner=is_owner,
        )
        if restored_session:
            self.auth_view.refresh_account_button()

        await self.load_database_item_types()
        await self.load_database_pickup_spots()

    def show_message(self, message: str) -> None:
        self.page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("Maphi Doces", color=INK),
                content=ft.Text(message, color=MUTED),
                actions=[
                    ft.TextButton(
                        "Entendi",
                        on_click=lambda _: self.page.pop_dialog(),
                    )
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    def show_notice(self, message: str) -> None:
        self.page.show_dialog(
            ft.SnackBar(
                content=message,
                behavior=ft.SnackBarBehavior.FLOATING,
                duration=3000,
            )
        )

    def refresh_owner_access(self) -> None:
        if hasattr(self, "catalog_view"):
            is_owner = self.auth_controller.is_owner
            if not is_owner:
                self.catalog_controller.hide_inactive_item_types()
            self.catalog_view.set_account_state(
                is_authenticated=self.auth_controller.is_authenticated,
                is_owner=is_owner,
            )
            self.page.run_task(self.load_database_item_types)
            self.page.run_task(self.load_database_pickup_spots)

    async def load_database_item_types(self) -> None:
        try:
            is_owner = self.auth_controller.is_owner
            await self.catalog_controller.load_item_types(
                id_token=self.auth_controller.id_token if is_owner else None,
                include_inactive=is_owner,
            )
            self.catalog_view.refresh()
            self.page.update()
        except FirebaseRestError as exc:
            self.show_message(f"Não foi possível carregar os sabores do Firestore: {exc}")

    async def load_database_pickup_spots(self) -> None:
        try:
            await self.pickup_spot_controller.load_active_pickup_spots(
                self.auth_controller.id_token
                if self.auth_controller.is_owner
                else None
            )
            self.catalog_view.refresh_pickup_spot_options()
            self.page.update()
        except FirebaseRestError as exc:
            self.show_message(
                f"Não foi possível carregar os locais de retirada: {exc}"
            )

    async def prepare_google_auth(self) -> None:
        try:
            await self.auth_controller.google_auth_client.prepare()
        except Exception as exc:
            self.show_message(f"Não foi possível preparar o login com Google: {exc}")

    async def create_item_type(
        self,
        *,
        name: str,
        description: str,
        regular_price: str,
        promotional_price: str,
        is_custom_order_only: bool,
        is_active: bool,
        image_data: bytes | None,
        image_filename: str | None,
        image_content_type: str | None,
    ):
        if (
            not self.auth_controller.is_owner
            or not self.auth_controller.id_token
            or not self.auth_controller.user_id
        ):
            raise ValueError("Apenas uma conta de dono autenticada pode adicionar sabores.")

        return await self.catalog_controller.create_item_type(
            name=name,
            description=description,
            regular_price=regular_price,
            promotional_price=promotional_price,
            is_custom_order_only=is_custom_order_only,
            is_active=is_active,
            id_token=self.auth_controller.id_token,
            user_id=self.auth_controller.user_id,
            image_data=image_data,
            image_filename=image_filename,
            image_content_type=image_content_type,
        )

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
        image_data: bytes | None,
        image_filename: str | None,
        image_content_type: str | None,
    ):
        if (
            not self.auth_controller.is_owner
            or not self.auth_controller.id_token
            or not self.auth_controller.user_id
        ):
            raise ValueError("Apenas uma conta de dono autenticada pode editar sabores.")

        return await self.catalog_controller.update_item_type(
            item_type_id=item_type_id,
            name=name,
            description=description,
            regular_price=regular_price,
            promotional_price=promotional_price,
            is_custom_order_only=is_custom_order_only,
            is_active=is_active,
            id_token=self.auth_controller.id_token,
            user_id=self.auth_controller.user_id,
            image_data=image_data,
            image_filename=image_filename,
            image_content_type=image_content_type,
        )

    async def check_item_type_inventory(self, item_type_id: str) -> bool:
        if (
            not self.auth_controller.is_owner
            or not self.auth_controller.id_token
        ):
            raise ValueError("Apenas o dono pode consultar o estoque do sabor.")
        return await self.catalog_controller.can_delete_item_type(
            item_type_id, self.auth_controller.id_token
        )

    async def delete_item_type(self, item_type_id: str) -> None:
        if (
            not self.auth_controller.is_owner
            or not self.auth_controller.id_token
        ):
            raise ValueError("Apenas uma conta de dono autenticada pode excluir sabores.")
        await self.catalog_controller.delete_item_type(
            item_type_id, self.auth_controller.id_token
        )

    async def open_pickup_spot_form(self) -> None:
        if not self.auth_controller.is_owner:
            self.show_message("Apenas uma conta de dono pode criar locais de retirada.")
            return
        self.pickup_spot_form_view.open_form()

    async def edit_pickup_spot(self, pickup_spot: PickupSpot) -> None:
        if (
            not self.auth_controller.is_owner
            or not self.auth_controller.id_token
        ):
            self.show_message("Apenas o dono pode editar locais de retirada.")
            return
        self.pickup_spot_form_view.open_form(pickup_spot)

    async def create_pickup_spot(
        self,
        *,
        name: str,
        address: str,
        arrival_at: str,
        departure_at: str,
    ):
        if (
            not self.auth_controller.is_owner
            or not self.auth_controller.id_token
        ):
            raise ValueError(
                "Apenas uma conta de dono autenticada pode criar locais de retirada."
            )
        pickup_spot = await self.pickup_spot_controller.create_pickup_spot(
            name=name,
            address=address,
            arrival_at=arrival_at,
            departure_at=departure_at,
            id_token=self.auth_controller.id_token,
        )
        self.catalog_view.refresh_pickup_spot_options()
        self.page.update()
        return pickup_spot

    async def update_pickup_spot(
        self,
        *,
        pickup_spot_id: str,
        name: str,
        address: str,
        arrival_at: str,
        departure_at: str,
    ):
        if (
            not self.auth_controller.is_owner
            or not self.auth_controller.id_token
        ):
            raise ValueError(
                "Apenas uma conta de dono autenticada pode editar locais de retirada."
            )
        pickup_spot = await self.pickup_spot_controller.update_pickup_spot(
            pickup_spot_id=pickup_spot_id,
            name=name,
            address=address,
            arrival_at=arrival_at,
            departure_at=departure_at,
            id_token=self.auth_controller.id_token,
        )
        self.catalog_view.refresh_pickup_spot_options()
        self.page.update()
        return pickup_spot

    async def delete_pickup_spot(self, pickup_spot_id: str) -> None:
        if (
            not self.auth_controller.is_owner
            or not self.auth_controller.id_token
            or not self.auth_controller.user_id
        ):
            raise ValueError(
                "Apenas uma conta de dono autenticada pode excluir locais de retirada."
            )
        await self.pickup_spot_controller.deactivate_pickup_spot(
            pickup_spot_id, self.auth_controller.id_token
        )
        self.catalog_view.refresh_pickup_spot_options()
        self.page.update()
        await self.reservation_controller.cancel_active_for_pickup(
            pickup_spot_id,
            owner_id=self.auth_controller.user_id,
            id_token=self.auth_controller.id_token,
        )
        await self.pickup_spot_controller.delete_pickup_spot(
            pickup_spot_id, self.auth_controller.id_token
        )
        self.catalog_view.refresh_pickup_spot_options()
        self.page.update()
        await self.load_database_item_types()

    async def open_reservations(self) -> None:
        if (
            not self.auth_controller.is_authenticated
            or not self.auth_controller.id_token
            or not self.auth_controller.user_id
        ):
            self.show_message("Entre na sua conta para ver as reservas.")
            self.open_auth()
            return
        self.catalog_view.root.visible = False
        self.page.floating_action_button = None
        self.reservation_view.open()
        self.reservation_filter_spot_id = None
        await self.load_reservations()

    async def load_reservations(self) -> None:
        try:
            is_owner = self.auth_controller.is_owner
            reservations = await self.reservation_controller.load_reservations(
                user_id=self.auth_controller.user_id or "",
                id_token=self.auth_controller.id_token or "",
                is_owner=is_owner,
                pickup_spot_id=(
                    self.reservation_filter_spot_id if is_owner else None
                ),
            )
            self.reservation_view.set_reservations(
                reservations,
                is_owner=is_owner,
                pickup_spots=(
                    self.pickup_spot_controller.pickup_spots
                    if is_owner
                    else []
                ),
                selected_pickup_spot_id=self.reservation_filter_spot_id,
            )
        except (FirebaseRestError, ReservationError) as exc:
            self.show_message(f"Não foi possível carregar as reservas: {exc}")

    async def filter_reservations(
        self, pickup_spot_id: str | None
    ) -> None:
        if not self.auth_controller.is_owner:
            raise ValueError("Apenas o dono pode filtrar as reservas por local.")
        self.reservation_filter_spot_id = pickup_spot_id
        await self.load_reservations()

    async def cancel_reservation(self, reservation_id: str) -> None:
        if not self.auth_controller.user_id or not self.auth_controller.id_token:
            raise ValueError("Entre na sua conta para cancelar uma reserva.")
        await self.reservation_controller.cancel_reservation(
            reservation_id,
            user_id=self.auth_controller.user_id,
            id_token=self.auth_controller.id_token,
            is_owner=self.auth_controller.is_owner,
        )
        await self.load_database_item_types()
        await self.load_reservations()
        self.show_notice(
            "Reserva cancelada pelo dono."
            if self.auth_controller.is_owner
            else "Sua reserva foi cancelada."
        )

    async def complete_reservation(self, reservation_id: str) -> None:
        if not self.auth_controller.id_token:
            raise ValueError("Entre na conta de dono para finalizar a venda.")
        await self.reservation_controller.complete_reservation(
            reservation_id,
            id_token=self.auth_controller.id_token,
            is_owner=self.auth_controller.is_owner,
        )
        await self.load_database_item_types()
        await self.load_reservations()
        self.show_notice("Venda finalizada.")

    async def delete_reservation(self, reservation_id: str) -> None:
        if not self.auth_controller.id_token:
            raise ValueError("Entre na conta de dono para apagar a reserva.")
        await self.reservation_controller.delete_reservation(
            reservation_id,
            id_token=self.auth_controller.id_token,
            is_owner=self.auth_controller.is_owner,
        )
        await self.load_reservations()
        self.show_notice("Reserva apagada do sistema.")

    def hide_catalog(self) -> None:
        self.catalog_view.root.visible = False

    def show_catalog(self) -> None:
        self.auth_view.root.visible = False
        self.reservation_view.root.visible = False
        self.catalog_view.root.visible = True
        self.page.floating_action_button = (
            self.catalog_view.production_button
            if self.auth_controller.is_owner
            else self.catalog_view.reserve_button
        )
        self.catalog_view.refresh()
        self.page.update()

    def open_auth(self) -> None:
        self.auth_controller.show_login()
        self.auth_view.open()

    def set_authenticated_user(self, name: str | None) -> None:
        self.auth_controller.set_user(name)
        self.auth_view.refresh_account_button()

    async def start_reservation(self) -> None:
        if (
            not self.auth_controller.is_authenticated
            or not self.auth_controller.id_token
            or not self.auth_controller.user_id
        ):
            self.show_message("Entre na sua conta para continuar com a reserva.")
            self.open_auth()
            return
        pickup_spot = self.pickup_spot_controller.selected_pickup_spot
        if pickup_spot is None:
            self.show_message("Selecione um local de retirada para reservar.")
            return
        quantities = {
            item_type_id: quantity
            for item_type_id, quantity in self.catalog_controller.quantities.items()
            if quantity > 0
        }
        if not quantities:
            self.show_message("Selecione ao menos um bolo para reservar.")
            return
        if self.is_creating_reservation:
            return

        self.is_creating_reservation = True
        self.catalog_view.reserve_button.disabled = True
        self.catalog_view.owner_reserve_button.disabled = True
        self.page.update()
        try:
            await self._create_selected_reservations(
                pickup_spot.id, quantities
            )
        finally:
            self.is_creating_reservation = False
            self.catalog_view.refresh()
            self.page.update()

    async def _create_selected_reservations(
        self, pickup_spot_id: str, quantities: dict[str, int]
    ) -> None:
        reservation_groups: list[dict[str, int]] = []
        current_group: dict[str, int] = {}
        current_group_size = 0
        for item_type_id, quantity in quantities.items():
            for _ in range(quantity):
                current_group[item_type_id] = (
                    current_group.get(item_type_id, 0) + 1
                )
                current_group_size += 1
                if current_group_size == MAX_UNITS_PER_RESERVATION:
                    reservation_groups.append(current_group)
                    current_group = {}
                    current_group_size = 0
        if current_group:
            reservation_groups.append(current_group)

        created_reservations = []
        remaining_quantities = quantities.copy()
        for group in reservation_groups:
            try:
                reservation = (
                    await self.reservation_controller.create_reservation(
                        quantities=group,
                        pickup_spot_id=pickup_spot_id,
                        user_id=self.auth_controller.user_id,
                        user_name=self.auth_controller.user_name or "Usuário",
                        is_owner=self.auth_controller.is_owner,
                        id_token=self.auth_controller.id_token,
                    )
                )
            except (FirebaseRestError, ReservationError, ValueError) as exc:
                self.catalog_controller.quantities = remaining_quantities
                await self.load_database_item_types()
                if created_reservations:
                    created_count = len(created_reservations)
                    created_label = (
                        f"{created_count} reserva foi criada"
                        if created_count == 1
                        else f"{created_count} reservas foram criadas"
                    )
                    self.show_message(
                        f"{created_label}, mas as demais falharam: {exc}"
                    )
                    await self.open_reservations()
                else:
                    self.show_message(f"Não foi possível criar a reserva: {exc}")
                return
            created_reservations.append(reservation)
            for item_type_id, quantity in group.items():
                remaining_quantities[item_type_id] -= quantity

        self.catalog_controller.quantities = remaining_quantities
        await self.load_database_item_types()
        total_amount = sum(
            (reservation.total_amount for reservation in created_reservations),
            start=Decimal("0.00"),
        )
        formatted_total = f"{total_amount:.2f}".replace(".", ",")
        created_label = (
            "1 reserva criada"
            if len(created_reservations) == 1
            else f"{len(created_reservations)} reservas criadas"
        )
        self.show_notice(
            f"{created_label}. Valor a pagar: R$ {formatted_total}"
        )
        await self.open_reservations()

    async def open_production_form(self, _=None) -> None:
        if not self.auth_controller.is_owner:
            self.show_message("Apenas o dono pode registrar a produção.")
            return
        self.production_form_view.open_form(self.catalog_controller.cakes)

    async def add_stock(self, quantities: dict[str, int]) -> int:
        if (
            not self.auth_controller.is_owner
            or not self.auth_controller.id_token
        ):
            raise ValueError(
                "Apenas uma conta de dono autenticada pode registrar a produção."
            )
        total_units = await self.catalog_controller.add_stock(
            quantities, self.auth_controller.id_token
        )
        self.catalog_view.refresh()
        self.page.update()
        return total_units

    async def remove_available_stock(self, item_type_id: str) -> None:
        if not self.auth_controller.is_owner or not self.auth_controller.id_token:
            raise ValueError("Apenas o dono pode remover unidades do estoque.")
        await self.catalog_controller.remove_available_unit(
            item_type_id, self.auth_controller.id_token
        )
        self.catalog_view.refresh()
        self.page.update()


def create_application(page: ft.Page) -> MaphiApplication:
    return MaphiApplication(page)
