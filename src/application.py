import flet as ft

from app_config import INK, MUTED, configure_page
from features.auth.auth_logic import AuthController
from features.auth.auth_view import AuthView
from features.catalog.catalog_logic import CatalogController
from features.catalog.catalog_view import CatalogView
from features.pickup_spots.pickup_spots_logic import (
    PickupSpot,
    PickupSpotController,
)
from features.pickup_spots.pickup_spots_view import PickupSpotFormView
from firebase_rest import FirebaseRestError


class MaphiApplication:
    def __init__(self, page: ft.Page):
        self.page = page
        configure_page(page)
        self.auth_controller = AuthController()
        self.catalog_controller = CatalogController()
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
        self.catalog_view = CatalogView(
            page=page,
            controller=self.catalog_controller,
            pickup_spot_controller=self.pickup_spot_controller,
            account_button=self.auth_view.account_button,
            on_reserve=self.start_reservation,
            on_create_pickup_spot=self.open_pickup_spot_form,
            on_edit_pickup_spot=self.edit_pickup_spot,
            on_delete_pickup_spot=self.delete_pickup_spot,
            on_create_item_type=self.create_item_type,
            on_update_item_type=self.update_item_type,
            on_delete_item_type=self.delete_item_type,
            on_check_item_type_inventory=self.check_item_type_inventory,
            on_notice=self.show_notice,
            on_message=self.show_message,
        )
        self.root = ft.Stack(
            controls=[self.catalog_view.root, self.auth_view.root],
            expand=True,
        )
        page.add(self.root)
        page.run_task(self.load_database_item_types)
        page.run_task(self.load_database_pickup_spots)
        if page.pyodide:
            page.run_task(self.prepare_google_auth)

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
            self.catalog_view.set_owner(is_owner)
            self.page.run_task(self.load_database_item_types)

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
            await self.pickup_spot_controller.load_active_pickup_spots()
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
        ):
            raise ValueError(
                "Apenas uma conta de dono autenticada pode excluir locais de retirada."
            )
        await self.pickup_spot_controller.delete_pickup_spot(
            pickup_spot_id, self.auth_controller.id_token
        )
        self.catalog_view.refresh_pickup_spot_options()
        self.page.update()

    def hide_catalog(self) -> None:
        self.catalog_view.root.visible = False

    def show_catalog(self) -> None:
        self.auth_view.root.visible = False
        self.catalog_view.root.visible = True
        self.catalog_view.refresh()
        self.page.update()

    def open_auth(self) -> None:
        self.auth_controller.show_login()
        self.auth_view.open()

    def set_authenticated_user(self, name: str | None) -> None:
        self.auth_controller.set_user(name)
        self.auth_view.refresh_account_button()

    def start_reservation(self) -> None:
        self.show_message("Entre na sua conta para continuar com a reserva.")


def create_application(page: ft.Page) -> MaphiApplication:
    return MaphiApplication(page)
