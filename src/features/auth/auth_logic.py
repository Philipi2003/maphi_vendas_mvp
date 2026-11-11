from app_config import BREAKPOINT_TABLET


class AuthController:
    def __init__(self) -> None:
        self.mode = "login"
        self.user_name: str | None = None

    @property
    def is_registration(self) -> bool:
        return self.mode == "register"

    @property
    def is_authenticated(self) -> bool:
        return self.user_name is not None

    def show_login(self) -> None:
        self.mode = "login"

    def show_registration(self) -> None:
        self.mode = "register"

    def set_user(self, name: str | None) -> None:
        self.user_name = name

    @staticmethod
    def uses_full_screen(width: float | None) -> bool:
        return (width or 0) < BREAKPOINT_TABLET

    def submit_message(self) -> str:
        return (
            "A autenticação ainda não está conectada ao Firebase. "
            "Nenhuma conta ou sessão foi alterada."
        )

    @staticmethod
    def google_message() -> str:
        return "O acesso com Google será conectado ao Firebase na próxima etapa."
