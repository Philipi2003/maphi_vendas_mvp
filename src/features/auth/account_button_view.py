import flet as ft

from app_config import ACCENT, SURFACE
from features.auth.auth_logic import AuthController


class AccountButtonView:
    def __init__(self, controller: AuthController, on_login, on_logout):
        self.controller = controller
        self.on_login = on_login
        self.on_logout = on_logout
        self.button = ft.Container()
        self.refresh()

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
            button = ft.PopupMenuButton(
                content=content,
                items=[
                    ft.PopupMenuItem(
                        content="Sair",
                        icon=ft.Icons.LOGOUT,
                        on_click=self.on_logout,
                    )
                ],
                style=ft.ButtonStyle(
                    color=ACCENT,
                    bgcolor=SURFACE,
                    padding=ft.Padding.symmetric(horizontal=16, vertical=11),
                    shape=ft.RoundedRectangleBorder(radius=24),
                ),
            )
        else:
            button = ft.TextButton(
                content=ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.LOGIN, size=17),
                        ft.Text("Entrar", weight=ft.FontWeight.W_600),
                    ],
                    spacing=8,
                    tight=True,
                ),
                style=ft.ButtonStyle(
                    color=ACCENT,
                    bgcolor=SURFACE,
                    padding=ft.Padding.symmetric(horizontal=16, vertical=11),
                    shape=ft.RoundedRectangleBorder(radius=24),
                ),
                on_click=lambda _: self.on_login(),
            )
        self.button.content = button
