import flet as ft

from app_config import ACCENT, BACKGROUND, BORDER, INK, MUTED, SURFACE
from features.auth.account_button_view import AccountButtonView
from features.auth.auth_logic import AuthController, FirebaseAuthError


INVALID_CREDENTIAL_CODES = {
    "EMAIL_NOT_FOUND",
    "INVALID_EMAIL",
    "INVALID_LOGIN_CREDENTIALS",
    "INVALID_PASSWORD",
}


class AuthView:
    def __init__(
        self,
        page: ft.Page,
        controller: AuthController,
        on_message,
        on_notice,
        on_auth_changed,
        on_mobile_open,
        on_mobile_close,
    ):
        self.page = page
        self.controller = controller
        self.on_message = on_message
        self.on_notice = on_notice
        self.on_auth_changed = on_auth_changed
        self.on_mobile_open = on_mobile_open
        self.on_mobile_close = on_mobile_close
        self.dialog: ft.AlertDialog | None = None
        self.root = ft.Container(visible=False, expand=True, bgcolor=BACKGROUND)
        self.account_button_view = AccountButtonView(
            controller, self.open, self._logout
        )
        self.account_button = self.account_button_view.button
        self._name_field: ft.TextField | None = None
        self._email_field: ft.TextField | None = None
        self._password_field: ft.TextField | None = None
        self._submit_button: ft.FilledButton | None = None
        self._google_button: ft.OutlinedButton | None = None
        self._form_error: ft.Text | None = None

    def refresh_account_button(self) -> None:
        self.account_button_view.refresh()
        self.page.update()

    async def _logout(self, _=None) -> None:
        logout_errors = []
        try:
            await self.controller.sign_out_provider()
        except FirebaseAuthError as exc:
            logout_errors.append(str(exc))
        try:
            await self.controller.clear_persisted_session()
        except FirebaseAuthError as exc:
            logout_errors.append(str(exc))
        finally:
            self.controller.logout()
            self.on_auth_changed()
            self.refresh_account_button()

        if logout_errors:
            self.on_message("\n".join(logout_errors))
        else:
            self.on_notice("Você saiu da sua conta.")

    def open(self) -> None:
        self.controller.show_login()
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

    def _build_fields(self) -> list[ft.Control]:
        registration = self.controller.is_registration
        fields: list[ft.Control] = []
        if registration:
            self._name_field = ft.TextField(label="Nome", border_radius=12)
            fields.append(self._name_field)
        self._email_field = ft.TextField(
            label="E-mail",
            keyboard_type=ft.KeyboardType.EMAIL,
            border_radius=12,
            on_change=self._clear_form_error,
        )
        self._password_field = ft.TextField(
            label="Senha",
            password=True,
            can_reveal_password=True,
            border_radius=12,
            on_change=self._clear_form_error,
        )
        fields.extend([self._email_field, self._password_field])
        return fields

    def _clear_form_error(self, _=None) -> None:
        if self._form_error is not None and self._form_error.visible:
            self._form_error.visible = False
            self.page.update()

    async def _submit_form(self) -> None:
        if self._form_error is not None:
            self._form_error.visible = False
        if self._submit_button is not None:
            self._submit_button.disabled = True
            self.page.update()

        try:
            await self.controller.submit(
                name=(self._name_field.value if self._name_field else None),
                email=(self._email_field.value if self._email_field else None),
                password=(self._password_field.value if self._password_field else None),
            )
            self._finish_sign_in()
        except FirebaseAuthError as exc:
            if exc.code in INVALID_CREDENTIAL_CODES and self._form_error is not None:
                self._form_error.value = (
                    "Informe um e-mail válido."
                    if exc.code == "INVALID_EMAIL"
                    else "E-mail ou senha incorretos. Confira seus dados e tente novamente."
                )
                self._form_error.visible = True
                self.page.update()
            else:
                self.on_message(str(exc))
        except Exception as exc:  # pragma: no cover - safety net for runtime errors
            self.on_message(f"Não foi possível completar a autenticação: {exc}")
        finally:
            if self._submit_button is not None and (
                self.dialog is not None or self.root.visible
            ):
                self._submit_button.disabled = False
                self.page.update()

    async def _submit_google(self, _=None) -> None:
        if self._google_button is not None:
            self._google_button.disabled = True
            self.page.update()

        try:
            await self.controller.submit_google()
            self._finish_sign_in()
        except FirebaseAuthError as exc:
            self.on_message(str(exc))
        except Exception as exc:  # pragma: no cover - runtime/browser failures
            self.on_message(f"Não foi possível entrar com Google: {exc}")
        finally:
            if self._google_button is not None and (
                self.dialog is not None or self.root.visible
            ):
                self._google_button.disabled = False
                self.page.update()

    def _finish_sign_in(self) -> None:
        self.account_button_view.refresh()
        self.on_auth_changed()
        self.close()
        self.page.update()
        self.on_notice("Login realizado com sucesso.")

    def _form(self) -> ft.Control:
        registration = self.controller.is_registration
        title = "Crie sua conta" if registration else "Que bom ter você por aqui"
        description = (
            "Cadastre-se para reservar seus bolos favoritos."
            if registration
            else "Entre na sua conta para acompanhar suas reservas."
        )
        fields = self._build_fields()
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
        self._submit_button = ft.FilledButton(
            "Criar conta" if registration else "Entrar",
            icon=(
                ft.Icons.PERSON_ADD_ALT_1
                if registration
                else ft.Icons.LOGIN
            ),
            on_click=self._submit_form,
        )
        self._google_button = ft.OutlinedButton(
            "Continuar com Google",
            icon=ft.Icons.ACCOUNT_CIRCLE_OUTLINED,
            on_click=self._submit_google,
        )
        self._form_error = ft.Text(
            color="#B3261E",
            size=13,
            visible=False,
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
                self._form_error,
                self._submit_button,
                ft.Row(
                    controls=[
                        ft.Container(expand=True, height=1, bgcolor=BORDER),
                        ft.Text("ou", size=12, color=MUTED),
                        ft.Container(expand=True, height=1, bgcolor=BORDER),
                    ],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self._google_button,
                mode_action,
            ],
            spacing=16,
            tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
