import flet as ft

from app_config import INK, MUTED, configure_page
from features.auth.auth_logic import AuthController
from features.auth.auth_view import AuthView
from features.catalog.catalog_logic import CatalogController
from features.catalog.catalog_view import CatalogView
from firebase_rest import FirebaseRestError


class MaphiApplication:
    def __init__(self, page: ft.Page):
        self.page = page
        configure_page(page)
        self.auth_controller = AuthController()
        self.catalog_controller = CatalogController()
        self.auth_view = AuthView(
            page=page,
            controller=self.auth_controller,
            on_message=self.show_message,
            on_notice=self.show_notice,
            on_auth_changed=self.refresh_owner_access,
            on_mobile_open=self.hide_catalog,
            on_mobile_close=self.show_catalog,
        )
        self.catalog_view = CatalogView(
            page=page,
            controller=self.catalog_controller,
            account_button=self.auth_view.account_button,
            on_reserve=self.start_reservation,
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
