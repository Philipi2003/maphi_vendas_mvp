import os
from pathlib import Path

import flet as ft


BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATHS = (BASE_DIR / ".env", Path(__file__).resolve().parent / ".env")


def _load_env_file() -> None:
    for env_path in ENV_PATHS:
        if not env_path.exists():
            continue

        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip().rstrip(",")
            if not line or line.startswith("#"):
                continue

            separator = "=" if "=" in line else ":" if ":" in line else None
            if separator is None:
                continue

            key, value = line.split(separator, 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)


_load_env_file()

APP_TITLE = "Maphi Doces | Bolos feitos com carinho"
BREAKPOINT_TABLET = 768

BACKGROUND = "#FAF7F2"
SURFACE = "#FFFFFF"
INK = "#302720"
MUTED = "#82796F"
ACCENT = "#8B4F46"
ACCENT_LIGHT = "#F5E9E5"
GREEN = "#3D7657"
BORDER = "#EEE8E0"

FIREBASE_API_KEY = (
    os.getenv("FIREBASE_API_KEY")
    or os.getenv("MAPHI_FIREBASE_API_KEY")
    or ""
)
AUTH_DOMAIN = os.getenv("AUTH_DOMAIN") or ""
PROJECT_ID = os.getenv("PROJECT_ID") or ""
STORAGE_BUCKET = os.getenv("STORAGE_BUCKET") or ""
MESSAGING_SENDER_ID = os.getenv("MESSAGING_SENDER_ID") or ""
APP_ID = os.getenv("APP_ID") or ""
MEASUREMENT_ID = os.getenv("MEASUREMENT_ID") or ""


def configure_page(page: ft.Page) -> None:
    page.title = APP_TITLE
    page.theme = ft.Theme(color_scheme_seed=ACCENT)
    page.bgcolor = BACKGROUND
    page.padding = 0
    page.spacing = 0
    page.theme_mode = ft.ThemeMode.LIGHT
