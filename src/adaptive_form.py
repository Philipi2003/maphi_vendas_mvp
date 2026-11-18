import flet as ft

from app_config import BREAKPOINT_TABLET, INK


def build_adaptive_form_surface(
    page: ft.Page,
    *,
    title: str,
    content: ft.Control,
    actions: list[ft.Control],
    on_dismiss,
    desktop_width: int,
    desktop_height: int | None = None,
) -> ft.AlertDialog | ft.BottomSheet:
    page_width = getattr(page, "width", None)
    if page_width is not None and page_width < BREAKPOINT_TABLET:
        content.expand = True
        return ft.BottomSheet(
            content=ft.SafeArea(
                expand=True,
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.IconButton(
                                    icon=ft.Icons.ARROW_BACK,
                                    tooltip="Fechar formulário",
                                    on_click=lambda _: page.pop_dialog(),
                                ),
                                ft.Text(
                                    title,
                                    size=20,
                                    weight=ft.FontWeight.W_600,
                                    color=INK,
                                    expand=True,
                                ),
                            ],
                            spacing=8,
                        ),
                        ft.Container(
                            content=content,
                            expand=True,
                            padding=ft.Padding.symmetric(horizontal=20),
                        ),
                        ft.Container(
                            content=ft.Row(
                                controls=actions,
                                alignment=ft.MainAxisAlignment.END,
                                wrap=True,
                                spacing=8,
                            ),
                            padding=ft.Padding.symmetric(
                                horizontal=20, vertical=12
                            ),
                        ),
                    ],
                    spacing=8,
                    expand=True,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
            ),
            fullscreen=True,
            scrollable=True,
            show_drag_handle=True,
            draggable=True,
            use_safe_area=True,
            maintain_bottom_view_insets_padding=True,
            on_dismiss=on_dismiss,
        )

    return ft.AlertDialog(
        modal=False,
        title=ft.Text(title, color=INK),
        content=ft.Container(
            width=desktop_width,
            height=desktop_height,
            content=content,
        ),
        actions=actions,
        actions_alignment=ft.MainAxisAlignment.END,
        on_dismiss=on_dismiss,
    )
