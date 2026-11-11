import flet as ft

from app_config import INK, MUTED, configure_page
from features.auth.auth_logic import AuthController
from features.auth.auth_view import AuthView
from features.catalog.catalog_logic import CatalogController
from features.catalog.catalog_view import CatalogView


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
            on_mobile_open=self.hide_catalog,
            on_mobile_close=self.show_catalog,
        )
        self.catalog_view = CatalogView(
            page=page,
            controller=self.catalog_controller,
            account_button=self.auth_view.account_button,
            on_reserve=self.start_reservation,
        )
        self.root = ft.Stack(
            controls=[self.catalog_view.root, self.auth_view.root],
            expand=True,
        )
        page.add(self.root)

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
