import flet as ft

from app_config import ACCENT, BACKGROUND, BORDER, INK, MUTED, SURFACE
from features.auth.account_button_view import AccountButtonView
from features.auth.auth_logic import AuthController


class AuthView:
    def __init__(
        self,
        page: ft.Page,
        controller: AuthController,
        on_message,
        on_mobile_open,
        on_mobile_close,
    ):
        self.page = page
        self.controller = controller
        self.on_message = on_message
        self.on_mobile_open = on_mobile_open
        self.on_mobile_close = on_mobile_close
        self.dialog: ft.AlertDialog | None = None
        self.root = ft.Container(visible=False, expand=True, bgcolor=BACKGROUND)
        self.account_button_view = AccountButtonView(controller, self.open)
        self.account_button = self.account_button_view.button

    def refresh_account_button(self) -> None:
        self.account_button_view.refresh()
        self.page.update()

    def open(self) -> None:
        if self.controller.uses_full_screen(self.page.width):
            self.on_mobile_open()
            self.root.visible = True
            self._render_mobile()
            return

        self.dialog = ft.AlertDialog(
            modal=False,
            content=self._desktop_content(),
            shape=ft.RoundedRectangleBorder(radius=22),
            on_dismiss=self._on_dialog_dismiss,
        )
        self.page.show_dialog(self.dialog)

    def close(self) -> None:
        if self.root.visible:
            self.root.visible = False
            self.on_mobile_close()
        elif self.dialog is not None:
            self.page.pop_dialog()

    def _on_dialog_dismiss(self, _=None) -> None:
        self.dialog = None

    def _desktop_content(self) -> ft.Control:
        return ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Container(expand=True),
                        ft.IconButton(
                            icon=ft.Icons.CLOSE,
                            tooltip="Fechar",
                            on_click=lambda _: self.close(),
                        ),
                    ],
                    spacing=0,
                ),
                ft.Container(
                    content=self._form(),
                    width=440,
                    padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                ),
            ],
            tight=True,
            spacing=0,
        )

    def _render_mobile(self) -> None:
        self.root.content = ft.SafeArea(
            expand=True,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.IconButton(
                                icon=ft.Icons.ARROW_BACK,
                                tooltip="Voltar ao catálogo",
                                on_click=lambda _: self.close(),
                            ),
                            ft.Row(
                                controls=[
                                    ft.Icon(
                                        ft.Icons.CAKE_OUTLINED,
                                        color=ACCENT,
                                        size=20,
                                    ),
                                    ft.Text(
                                        "maphi",
                                        size=20,
                                        weight=ft.FontWeight.BOLD,
                                        color=INK,
                                    ),
                                ],
                                spacing=8,
                            ),
                            ft.Container(width=48),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(
                        content=self._form(),
                        bgcolor=SURFACE,
                        border=ft.Border.all(1, BORDER),
                        border_radius=20,
                        padding=22,
                    ),
                ],
                spacing=24,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
            ),
        )
        self.page.update()

    def _switch_mode(self, registration: bool) -> None:
        if registration:
            self.controller.show_registration()
        else:
            self.controller.show_login()
        if self.root.visible:
            self._render_mobile()
        elif self.dialog is not None:
            self.dialog.content = self._desktop_content()
            self.page.update()

    def _form(self) -> ft.Control:
        registration = self.controller.is_registration
        title = "Crie sua conta" if registration else "Que bom ter você por aqui"
        description = (
            "Cadastre-se para reservar seus bolos favoritos."
            if registration
            else "Entre na sua conta para acompanhar suas reservas."
        )
        fields: list[ft.Control] = []
        if registration:
            fields.append(ft.TextField(label="Nome", border_radius=12))
        fields.extend(
            [
                ft.TextField(
                    label="E-mail",
                    keyboard_type=ft.KeyboardType.EMAIL,
                    border_radius=12,
                ),
                ft.TextField(
                    label="Senha",
                    password=True,
                    can_reveal_password=True,
                    border_radius=12,
                ),
            ]
        )
        if registration:
            mode_action = ft.Row(
                controls=[
                    ft.Text("Já tem uma conta?", color=MUTED, size=13),
                    ft.TextButton(
                        "Entrar",
                        on_click=lambda _: self._switch_mode(False),
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=4,
            )
        else:
            mode_action = ft.Row(
                controls=[
                    ft.Text("Ainda não tem uma conta?", color=MUTED, size=13),
                    ft.TextButton(
                        "Cadastre-se",
                        on_click=lambda _: self._switch_mode(True),
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=4,
            )
        return ft.Column(
            controls=[
                ft.Column(
                    controls=[
                        ft.Text(title, size=24, weight=ft.FontWeight.BOLD, color=INK),
                        ft.Text(description, size=14, color=MUTED),
                    ],
                    spacing=6,
                ),
                *fields,
                ft.FilledButton(
                    "Criar conta" if registration else "Entrar",
                    icon=(
                        ft.Icons.PERSON_ADD_ALT_1
                        if registration
                        else ft.Icons.LOGIN
                    ),
                    on_click=lambda _: self.on_message(
                        self.controller.submit_message()
                    ),
                ),
                ft.Row(
                    controls=[
                        ft.Container(expand=True, height=1, bgcolor=BORDER),
                        ft.Text("ou", size=12, color=MUTED),
                        ft.Container(expand=True, height=1, bgcolor=BORDER),
                    ],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.OutlinedButton(
                    "Continuar com Google",
                    icon=ft.Icons.ACCOUNT_CIRCLE_OUTLINED,
                    on_click=lambda _: self.on_message(
                        self.controller.google_message()
                    ),
                ),
                mode_action,
            ],
            spacing=16,
            tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
