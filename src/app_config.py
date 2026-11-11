import flet as ft


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


def configure_page(page: ft.Page) -> None:
    page.title = APP_TITLE
    page.theme = ft.Theme(color_scheme_seed=ACCENT)
    page.bgcolor = BACKGROUND
    page.padding = 0
    page.spacing = 0
    page.theme_mode = ft.ThemeMode.LIGHT
