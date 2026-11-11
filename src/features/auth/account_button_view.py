import flet as ft

from app_config import ACCENT, SURFACE
from features.auth.auth_logic import AuthController


class AccountButtonView:
    def __init__(self, controller: AuthController, on_login):
        self.controller = controller
        self.on_login = on_login
        self.button = ft.TextButton(
            style=ft.ButtonStyle(
                color=ACCENT,
                bgcolor=SURFACE,
                padding=ft.Padding.symmetric(horizontal=16, vertical=11),
                shape=ft.RoundedRectangleBorder(radius=24),
            ),
            on_click=self._on_click,
        )
        self.refresh()

    def _on_click(self, _) -> None:
        if not self.controller.is_authenticated:
            self.on_login()

    def refresh(self) -> None:
        if self.controller.is_authenticated:
            content = ft.Row(
                controls=[
                    ft.Icon(ft.Icons.PERSON_OUTLINE, size=18),
                    ft.Text(
                        self.controller.user_name or "",
                        weight=ft.FontWeight.W_600,
                    ),
                ],
                spacing=8,
                tight=True,
            )
        else:
            content = ft.Row(
                controls=[
                    ft.Icon(ft.Icons.LOGIN, size=17),
                    ft.Text("Entrar", weight=ft.FontWeight.W_600),
                ],
                spacing=8,
                tight=True,
            )
        self.button.content = content
