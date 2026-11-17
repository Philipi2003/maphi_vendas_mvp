import asyncio
import json
import os
import urllib.error
import urllib.request
from typing import Protocol
from urllib.parse import urlencode

from app_config import (
    APP_ID,
    AUTH_DOMAIN,
    BREAKPOINT_TABLET,
    FIREBASE_API_KEY,
    MESSAGING_SENDER_ID,
    MEASUREMENT_ID,
    PROJECT_ID,
    STORAGE_BUCKET,
)
from firebase_rest import FirebaseFirestoreClient, FirebaseRestError


class FirebaseAuthError(ValueError):
    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


class AuthSessionStorage(Protocol):
    async def get(
        self, key: str
    ) -> str | int | float | bool | list[str] | None: ...

    async def set(self, key: str, value: str) -> bool: ...

    async def remove(self, key: str) -> bool: ...


class FirebaseAuthClient:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or FIREBASE_API_KEY or os.getenv("FIREBASE_API_KEY")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    @staticmethod
    def _friendly_error(message: str) -> str:
        cleaned = message.replace("EMAIL_NOT_FOUND", "E-mail não cadastrado.")
        cleaned = cleaned.replace("INVALID_PASSWORD", "Senha inválida.")
        cleaned = cleaned.replace("INVALID_LOGIN_CREDENTIALS", "E-mail ou senha inválidos.")
        cleaned = cleaned.replace("EMAIL_EXISTS", "Este e-mail já está cadastrado.")
        cleaned = cleaned.replace("WEAK_PASSWORD", "Use uma senha com pelo menos 6 caracteres.")
        cleaned = cleaned.replace("INVALID_EMAIL", "E-mail inválido.")
        return cleaned

    async def sign_in(self, email: str, password: str) -> dict:
        return await self._request("signInWithPassword", {"email": email, "password": password, "returnSecureToken": True})

    async def refresh_session(self, refresh_token: str) -> dict:
        if not self.is_configured:
            raise FirebaseAuthError(
                "Configure a variável FIREBASE_API_KEY antes de restaurar a sessão."
            )

        endpoint = (
            "https://securetoken.googleapis.com/v1/token"
            f"?key={self.api_key}"
        )
        payload = urlencode(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )
        try:
            from pyodide.http import pyfetch
        except ModuleNotFoundError:
            details = await asyncio.to_thread(
                self._refresh_session_sync, endpoint, payload
            )
        else:
            response = await pyfetch(
                endpoint,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                body=payload,
            )
            details = await response.json()
            if not response.ok:
                raise self._error_from_details(details)

        return {
            "idToken": details.get("id_token"),
            "refreshToken": details.get("refresh_token"),
            "localId": details.get("user_id"),
        }

    async def lookup_account(self, id_token: str) -> dict:
        result = await self._request("lookup", {"idToken": id_token})
        users = result.get("users", [])
        if not users:
            raise FirebaseAuthError(
                "O Firebase não retornou os dados da conta salva."
            )
        return users[0]

    async def sign_up(self, name: str, email: str, password: str) -> dict:
        return await self._request(
            "signUp",
            {
                "email": email,
                "password": password,
                "returnSecureToken": True,
                "displayName": name,
            },
        )

    async def _request(self, operation: str, payload: dict) -> dict:
        if not self.is_configured:
            raise FirebaseAuthError(
                "Configure a variável FIREBASE_API_KEY antes de entrar com o Firebase "
                "Authentication."
            )

        endpoint = f"https://identitytoolkit.googleapis.com/v1/accounts:{operation}?key={self.api_key}"
        try:
            from pyodide.http import pyfetch
        except ModuleNotFoundError:
            return await asyncio.to_thread(
                self._request_sync, endpoint, payload
            )

        response = await pyfetch(
            endpoint,
            method="POST",
            headers={"Content-Type": "application/json"},
            body=json.dumps(payload),
        )
        details = await response.json()
        if not response.ok:
            raise self._error_from_details(details)
        return details

    @classmethod
    def _error_from_details(cls, details: dict) -> FirebaseAuthError:
        message = details.get("error", {}).get(
            "message", "Falha ao autenticar com o Firebase."
        )
        return FirebaseAuthError(cls._friendly_error(message), code=message)

    def _request_sync(self, endpoint: str, payload: dict) -> dict:
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="ignore")
            try:
                details = json.loads(response_body)
            except json.JSONDecodeError:
                details = {"error": {"message": response_body}}
            raise self._error_from_details(details) from exc

    def _refresh_session_sync(self, endpoint: str, payload: str) -> dict:
        request = urllib.request.Request(
            endpoint,
            data=payload.encode("ascii"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="ignore")
            try:
                details = json.loads(response_body)
            except json.JSONDecodeError:
                details = {"error": {"message": response_body}}
            raise self._error_from_details(details) from exc


class FirebaseGoogleAuthClient:
    def __init__(self) -> None:
        self._module = None

    async def _load_module(self):
        if self._module is not None:
            return self._module

        try:
            from js import Object, window
            from pyodide.code import run_js
            from pyodide.ffi import to_js
        except ImportError as exc:
            raise FirebaseAuthError(
                "O login com Google requer o build WebAssembly. Gere e execute "
                "o build web do Flet para usar esse recurso."
            ) from exc

        module_url = f"{window.location.origin}/firebase_auth_bridge.js"
        self._module = await run_js(f"import({json.dumps(module_url)})")
        self._object_from_entries = Object.fromEntries
        self._to_js = to_js
        return self._module

    async def prepare(self) -> None:
        await self._load_module()

    async def sign_in(self) -> dict:
        module = await self._load_module()
        config = {
            "apiKey": FIREBASE_API_KEY,
            "authDomain": AUTH_DOMAIN,
            "projectId": PROJECT_ID,
            "storageBucket": STORAGE_BUCKET,
            "messagingSenderId": MESSAGING_SENDER_ID,
            "appId": APP_ID,
            "measurementId": MEASUREMENT_ID,
        }
        config = {key: value for key, value in config.items() if value}
        result = await module.signInWithGoogle(
            self._to_js(config, dict_converter=self._object_from_entries)
        )
        result = result.to_py()
        if result.get("errorCode"):
            message = {
                "auth/popup-closed-by-user": "A janela de login do Google foi fechada.",
                "auth/popup-blocked": "O navegador bloqueou a janela do Google. Permita pop-ups e tente novamente.",
                "auth/unauthorized-domain": "Este domínio não está autorizado no Firebase Authentication.",
            }.get(result["errorCode"], result.get("errorMessage"))
            raise FirebaseAuthError(message or "Não foi possível entrar com Google.")
        return result

    async def sign_out(self) -> None:
        module = await self._load_module()
        try:
            await module.signOutFromGoogle()
        except Exception as exc:
            raise FirebaseAuthError(
                f"Não foi possível encerrar a sessão do Google: {exc}"
            ) from exc


class AuthController:
    SESSION_STORAGE_KEY = "maphi.auth.session"
    INVALID_REFRESH_CODES = {
        "INVALID_REFRESH_TOKEN",
        "TOKEN_EXPIRED",
        "USER_DISABLED",
        "USER_NOT_FOUND",
    }

    def __init__(
        self, session_storage: AuthSessionStorage | None = None
    ) -> None:
        self.mode = "login"
        self.user_name: str | None = None
        self.user_email: str | None = None
        self.user_id: str | None = None
        self.id_token: str | None = None
        self.refresh_token: str | None = None
        self.auth_client = FirebaseAuthClient()
        self.session_storage = session_storage
        self.google_auth_client = FirebaseGoogleAuthClient()
        self.firestore_client = FirebaseFirestoreClient()
        self.role = "CLIENTE"
        self.auth_provider: str | None = None

    @property
    def is_registration(self) -> bool:
        return self.mode == "register"

    @property
    def is_authenticated(self) -> bool:
        return self.user_name is not None

    @property
    def is_owner(self) -> bool:
        return self.is_authenticated and self.role == "DONO"

    def show_login(self) -> None:
        self.mode = "login"

    def show_registration(self) -> None:
        self.mode = "register"

    def set_user(
        self,
        name: str | None,
        email: str | None = None,
        user_id: str | None = None,
    ) -> None:
        self.user_name = name
        self.user_email = email
        self.user_id = user_id

    def logout(self) -> None:
        self.user_name = None
        self.user_email = None
        self.user_id = None
        self.id_token = None
        self.refresh_token = None
        self.role = "CLIENTE"
        self.auth_provider = None

    async def clear_persisted_session(self) -> None:
        if self.session_storage is None:
            return
        try:
            await self.session_storage.remove(self.SESSION_STORAGE_KEY)
        except Exception as exc:
            raise FirebaseAuthError(
                "Não foi possível remover a sessão salva neste dispositivo."
            ) from exc

    async def restore_session(self) -> bool:
        if self.session_storage is None:
            return False

        try:
            stored_session = await self.session_storage.get(
                self.SESSION_STORAGE_KEY
            )
        except Exception as exc:
            raise FirebaseAuthError(
                "Não foi possível ler a sessão salva neste dispositivo."
            ) from exc
        if stored_session is None:
            return False

        try:
            session = json.loads(stored_session) if isinstance(stored_session, str) else {}
        except json.JSONDecodeError as exc:
            await self.clear_persisted_session()
            raise FirebaseAuthError(
                "A sessão salva está inválida. Entre novamente."
            ) from exc
        if not isinstance(session, dict):
            await self.clear_persisted_session()
            raise FirebaseAuthError(
                "A sessão salva está inválida. Entre novamente."
            )

        refresh_token = session.get("refreshToken")
        provider = session.get("provider")
        if not isinstance(refresh_token, str) or not refresh_token:
            await self.clear_persisted_session()
            raise FirebaseAuthError(
                "A sessão salva está inválida. Entre novamente."
            )
        if not isinstance(provider, str) or provider not in {
            "password",
            "google",
        }:
            provider = "password"

        try:
            refreshed = await self.auth_client.refresh_session(refresh_token)
        except FirebaseAuthError as exc:
            if exc.code in self.INVALID_REFRESH_CODES:
                await self.clear_persisted_session()
                raise FirebaseAuthError(
                    "A sessão salva expirou ou foi revogada. Entre novamente.",
                    code=exc.code,
                ) from exc
            raise
        except Exception as exc:
            raise FirebaseAuthError(
                "Não foi possível restaurar a sessão salva."
            ) from exc

        id_token = refreshed.get("idToken")
        if not id_token:
            raise FirebaseAuthError(
                "O Firebase não conseguiu renovar a sessão salva."
            )
        try:
            account = await self.auth_client.lookup_account(id_token)
        except FirebaseAuthError:
            raise
        except Exception as exc:
            raise FirebaseAuthError(
                "Não foi possível carregar os dados da conta salva."
            ) from exc

        refreshed.update(
            {
                "localId": account.get("localId") or refreshed.get("localId"),
                "email": account.get("email"),
                "displayName": account.get("displayName"),
            }
        )
        await self._complete_sign_in(
            refreshed,
            email=refreshed.get("email") or "",
            fallback_name=refreshed.get("displayName"),
            provider=provider,
        )
        return True

    async def sign_out_provider(self) -> None:
        if self.auth_provider == "google":
            await self.google_auth_client.sign_out()

    @staticmethod
    def uses_full_screen(width: float | None) -> bool:
        return (width or 0) < BREAKPOINT_TABLET

    async def submit(
        self,
        *,
        name: str | None = None,
        email: str | None = None,
        password: str | None = None,
    ) -> str:
        if not email or not password:
            raise FirebaseAuthError("Preencha o e-mail e a senha para continuar.")

        normalized_email = email.strip()
        password = password.strip()

        if self.mode == "register":
            if not name or not name.strip():
                raise FirebaseAuthError("Informe o nome para criar a conta.")
            result = await self.auth_client.sign_up(name.strip(), normalized_email, password)
        else:
            result = await self.auth_client.sign_in(normalized_email, password)
        return await self._complete_sign_in(
            result,
            email=normalized_email,
            fallback_name=name.strip() if self.mode == "register" and name else None,
            provider="password",
        )

    async def submit_google(self) -> str:
        result = await self.google_auth_client.sign_in()
        return await self._complete_sign_in(
            result,
            email=result.get("email") or "",
            fallback_name=result.get("displayName"),
            provider="google",
        )

    async def _complete_sign_in(
        self,
        result: dict,
        *,
        email: str,
        fallback_name: str | None,
        provider: str,
    ) -> str:
        id_token = result.get("idToken")
        user_id = result.get("localId")
        refresh_token = result.get("refreshToken")
        if not id_token or not user_id or not email or not refresh_token:
            raise FirebaseAuthError("O Firebase não retornou os dados da sessão.")

        try:
            profile = await self.firestore_client.get_document(
                "users", user_id, id_token
            )
        except FirebaseRestError as exc:
            if exc.status_code == 404:
                profile = {}
            else:
                raise FirebaseAuthError(
                    "Login validado, mas não foi possível carregar o perfil e "
                    "verificar as permissões no Firestore."
                ) from exc

        profile_fields = profile.get("fields", {})
        profile_name = profile_fields.get("name", {}).get("stringValue")
        self.role = profile_fields.get("role", {}).get("stringValue", "CLIENTE")
        final_name = (
            fallback_name
            or result.get("displayName")
            or profile_name
            or email.split("@", 1)[0]
        ).strip()

        await self._persist_session(refresh_token, provider)
        self.id_token = id_token
        self.refresh_token = refresh_token
        self.set_user(final_name, email, user_id)
        self.auth_provider = provider
        return f"Bem-vindo(a), {final_name}!"

    async def _persist_session(self, refresh_token: str, provider: str) -> None:
        if self.session_storage is None:
            return
        session = json.dumps(
            {"refreshToken": refresh_token, "provider": provider},
            separators=(",", ":"),
        )
        try:
            stored = await self.session_storage.set(
                self.SESSION_STORAGE_KEY, session
            )
        except Exception as exc:
            raise FirebaseAuthError(
                "Login validado, mas não foi possível salvar a sessão neste dispositivo."
            ) from exc
        if not stored:
            raise FirebaseAuthError(
                "Login validado, mas não foi possível salvar a sessão neste dispositivo."
            )

    @staticmethod
    def google_message() -> str:
        return "O login com Google ainda não foi configurado no MVP. Use e-mail e senha para entrar."
