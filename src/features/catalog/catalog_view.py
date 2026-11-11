import flet as ft

from app_config import (
    ACCENT,
    ACCENT_LIGHT,
    BACKGROUND,
    BORDER,
    GREEN,
    INK,
    MUTED,
    SURFACE,
)
from features.catalog.catalog_logic import Cake, CatalogController


class CatalogView:
    def __init__(
        self,
        page: ft.Page,
        controller: CatalogController,
        account_button: ft.Control,
        on_reserve,
    ):
        self.page = page
        self.controller = controller
        self.on_reserve = on_reserve
        self.filter_controls: dict[str, ft.Container] = {}
        self.results_label = ft.Text(color=MUTED, size=13)
        self.selection_label = ft.Text(
            color=ACCENT, size=13, weight=ft.FontWeight.W_600, visible=False
        )
        self.catalog_grid = ft.ResponsiveRow(columns=12, spacing=18, run_spacing=18)
        self.reserve_button = ft.FloatingActionButton(
            content=ft.Row(spacing=10, tight=True),
            bgcolor=ACCENT,
            foreground_color=ft.Colors.WHITE,
            shape=ft.RoundedRectangleBorder(radius=30),
            width=220,
            height=56,
            on_click=lambda _: self.on_reserve(),
            visible=False,
        )
        self.page.floating_action_button = self.reserve_button
        self.account_button = account_button
        self.search_field = ft.TextField(
            hint_text="Busque seu sabor favorito",
            prefix_icon=ft.Icons.SEARCH,
            border=ft.NoInputBorder(),
            bgcolor=SURFACE,
            border_radius=14,
            content_padding=ft.Padding.symmetric(horizontal=14, vertical=14),
            on_change=self._search_changed,
        )
        self.root = self._build_root()
        self.refresh()

    def _build_root(self) -> ft.Control:
        for label in ("Todos", "Disponíveis", "Esgotados"):
            self.filter_controls[label] = ft.Container(
                content=ft.Text(label, size=13, weight=ft.FontWeight.W_500),
                bgcolor=SURFACE,
                border=ft.Border.all(1, BORDER),
                border_radius=24,
                padding=ft.Padding.symmetric(horizontal=16, vertical=9),
                on_click=lambda _, selected=label: self._choose_filter(selected),
            )

        header = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Icon(
                                    ft.Icons.CAKE_OUTLINED,
                                    color=ft.Colors.WHITE,
                                    size=23,
                                ),
                                bgcolor=ACCENT,
                                border_radius=13,
                                width=42,
                                height=42,
                                alignment=ft.Alignment.CENTER,
                            ),
                            ft.Column(
                                controls=[
                                    ft.Text(
                                        "maphi",
                                        size=23,
                                        weight=ft.FontWeight.BOLD,
                                        color=INK,
                                    ),
                                    ft.Text(
                                        "DOCES FEITOS COM CARINHO",
                                        size=9,
                                        color=MUTED,
                                        weight=ft.FontWeight.W_600,
                                    ),
                                ],
                                spacing=0,
                            ),
                        ],
                        spacing=10,
                    ),
                    self.account_button,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=SURFACE,
            border=ft.Border.only(bottom=ft.BorderSide(1, BORDER)),
            padding=ft.Padding.symmetric(horizontal=24, vertical=14),
        )

        hero = ft.Container(
            content=ft.ResponsiveRow(
                controls=[
                    ft.Container(
                        col={"xs": 12, "md": 8},
                        content=ft.Column(
                            controls=[
                                ft.Container(
                                    content=ft.Row(
                                        controls=[
                                            ft.Icon(
                                                ft.Icons.AUTO_AWESOME,
                                                color=ACCENT,
                                                size=15,
                                            ),
                                            ft.Text(
                                                "FEITO HOJE, COM CARINHO",
                                                color=ACCENT,
                                                size=11,
                                                weight=ft.FontWeight.W_600,
                                            ),
                                        ],
                                        spacing=7,
                                        tight=True,
                                    ),
                                    bgcolor=ACCENT_LIGHT,
                                    border_radius=20,
                                    padding=ft.Padding.symmetric(
                                        horizontal=12, vertical=8
                                    ),
                                ),
                                ft.Text(
                                    "Um pedacinho de felicidade\nem cada fatia.",
                                    size=34,
                                    weight=ft.FontWeight.BOLD,
                                    color=INK,
                                    font_family="Georgia",
                                ),
                                ft.Text(
                                    "Escolha seus favoritos e veja o que está fresquinho por aqui.",
                                    size=15,
                                    color=MUTED,
                                ),
                            ],
                            spacing=15,
                        ),
                    ),
                    ft.Container(
                        col={"xs": 12, "md": 4},
                        alignment=ft.Alignment.CENTER_RIGHT,
                        content=ft.Container(
                            content=ft.Row(
                                controls=[
                                    ft.Icon(
                                        ft.Icons.LOCAL_DINING_OUTLINED,
                                        color=GREEN,
                                        size=20,
                                    ),
                                    ft.Column(
                                        controls=[
                                            ft.Text(
                                                "Retirada combinada",
                                                size=13,
                                                color=INK,
                                                weight=ft.FontWeight.W_600,
                                            ),
                                            ft.Text(
                                                "Escolha o local ao reservar",
                                                size=11,
                                                color=MUTED,
                                            ),
                                        ],
                                        spacing=2,
                                    ),
                                ],
                                spacing=12,
                            ),
                            bgcolor=SURFACE,
                            border=ft.Border.all(1, BORDER),
                            border_radius=16,
                            padding=16,
                        ),
                    ),
                ],
                spacing=16,
                run_spacing=16,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor="#F4EDE5",
            border_radius=24,
            padding=ft.Padding.symmetric(horizontal=28, vertical=26),
        )

        catalog_heading = ft.ResponsiveRow(
            controls=[
                ft.Container(
                    col={"xs": 12, "sm": 6},
                    content=ft.Column(
                        controls=[
                            ft.Text(
                                "Nosso catálogo",
                                size=25,
                                weight=ft.FontWeight.BOLD,
                                color=INK,
                            ),
                            ft.Text(
                                "Encontre o bolo perfeito para hoje.",
                                size=14,
                                color=MUTED,
                            ),
                        ],
                        spacing=5,
                    ),
                ),
                ft.Container(
                    col={"xs": 12, "sm": 6},
                    alignment=ft.Alignment.CENTER_RIGHT,
                    content=self.selection_label,
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=12,
        )

        content = ft.Container(
            content=ft.Column(
                controls=[
                    hero,
                    catalog_heading,
                    self.search_field,
                    ft.Row(
                        controls=list(self.filter_controls.values()),
                        spacing=8,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                    self.results_label,
                    self.catalog_grid,
                    ft.Container(height=48),
                ],
                spacing=20,
                width=1180,
            ),
            alignment=ft.Alignment.TOP_CENTER,
            padding=ft.Padding.symmetric(horizontal=24, vertical=28),
            expand=True,
        )
        return ft.SafeArea(
            expand=True,
            content=ft.Column(
                controls=[header, content],
                spacing=0,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def _choose_filter(self, value: str) -> None:
        self.controller.set_filter(value)
        self.refresh()
        self.page.update()

    def _search_changed(self, event: ft.Event[ft.TextField]) -> None:
        self.controller.set_search_query(event.control.value or "")
        self.refresh()
        self.page.update()

    def _quantity_control(self, cake: Cake) -> ft.Control:
        quantity = self.controller.quantities[cake.id]

        def change(amount: int) -> None:
            self.controller.change_quantity(cake.id, amount)
            self.refresh()
            self.page.update()

        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.IconButton(
                        icon=ft.Icons.REMOVE,
                        icon_size=17,
                        icon_color=ACCENT if quantity else MUTED,
                        disabled=quantity == 0,
                        tooltip="Remover uma unidade",
                        on_click=lambda _: change(-1),
                    ),
                    ft.Text(
                        str(quantity),
                        width=24,
                        text_align=ft.TextAlign.CENTER,
                        weight=ft.FontWeight.W_600,
                        color=INK,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.ADD,
                        icon_size=17,
                        icon_color=ACCENT,
                        disabled=quantity >= cake.stock,
                        tooltip="Adicionar uma unidade",
                        on_click=lambda _: change(1),
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                spacing=0,
            ),
            bgcolor=BACKGROUND,
            border=ft.Border.all(1, BORDER),
            border_radius=14,
            padding=ft.Padding.symmetric(horizontal=4, vertical=1),
        )

    def _cake_card(self, cake: Cake) -> ft.Control:
        available = cake.stock > 0
        status_text = (
            f"{cake.stock} disponíveis" if available else "Esgotado no momento"
        )
        status_color = GREEN if available else MUTED
        footer = (
            self._quantity_control(cake)
            if available
            else ft.Container(
                content=ft.Text(
                    "Avise-me quando voltar",
                    color=MUTED,
                    size=12,
                    weight=ft.FontWeight.W_500,
                ),
                alignment=ft.Alignment.CENTER,
                border=ft.Border.all(1, BORDER),
                border_radius=14,
                padding=ft.Padding.symmetric(vertical=12),
            )
        )
        return ft.Container(
            col={"xs": 12, "sm": 6, "md": 4, "lg": 3},
            content=ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Container(
                            content=ft.Stack(
                                controls=[
                                    ft.Container(
                                        expand=True,
                                        alignment=ft.Alignment.CENTER,
                                        content=ft.Icon(
                                            ft.Icons.CAKE_OUTLINED,
                                            size=58,
                                            color=ACCENT,
                                        ),
                                    ),
                                    ft.Container(
                                        content=ft.Row(
                                            controls=[
                                                ft.Icon(
                                                    ft.Icons.CIRCLE,
                                                    size=8,
                                                    color=status_color,
                                                ),
                                                ft.Text(
                                                    status_text,
                                                    size=11,
                                                    weight=ft.FontWeight.W_600,
                                                    color=status_color,
                                                ),
                                            ],
                                            spacing=6,
                                            tight=True,
                                        ),
                                        bgcolor=SURFACE,
                                        border_radius=20,
                                        padding=ft.Padding.symmetric(
                                            horizontal=10, vertical=7
                                        ),
                                        right=12,
                                        top=12,
                                    ),
                                ],
                            ),
                            height=158,
                            bgcolor=cake.color,
                            border_radius=16,
                            clip_behavior=ft.ClipBehavior.HARD_EDGE,
                        ),
                        ft.Column(
                            controls=[
                                ft.Text(
                                    cake.name,
                                    size=18,
                                    weight=ft.FontWeight.W_600,
                                    color=INK,
                                ),
                                ft.Text(
                                    cake.description,
                                    size=13,
                                    color=MUTED,
                                    max_lines=2,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                            ],
                            spacing=6,
                        ),
                        ft.Container(expand=True),
                        footer,
                    ],
                    spacing=14,
                    expand=True,
                ),
                bgcolor=SURFACE,
                border=ft.Border.all(1, BORDER),
                border_radius=20,
                padding=14,
                height=342,
                shadow=ft.BoxShadow(
                    blur_radius=18,
                    color="#12000000",
                    offset=ft.Offset(0, 5),
                ),
            ),
        )

    def refresh(self) -> None:
        cakes = self.controller.filtered_cakes
        self.catalog_grid.controls = [self._cake_card(cake) for cake in cakes]
        self.results_label.value = (
            f"{len(cakes)} sabores no catálogo"
            if cakes
            else "Nenhum sabor encontrado"
        )
        selected = self.controller.selected_count
        self.selection_label.value = (
            f"{selected} selecionado" if selected == 1 else f"{selected} selecionados"
        )
        self.selection_label.visible = selected > 0
        self.reserve_button.visible = selected > 0
        self.reserve_button.content = ft.Row(
            controls=[
                ft.Icon(ft.Icons.SHOPPING_BAG_OUTLINED, color=ft.Colors.WHITE),
                ft.Text(
                    f"Reservar · {selected} {('bolo' if selected == 1 else 'bolos')}",
                    color=ft.Colors.WHITE,
                    weight=ft.FontWeight.W_600,
                ),
            ],
            spacing=10,
            tight=True,
        )
        for label, control in self.filter_controls.items():
            is_selected = label == self.controller.active_filter
            control.bgcolor = ACCENT if is_selected else SURFACE
            control.content.color = ft.Colors.WHITE if is_selected else MUTED
            control.border = ft.Border.all(1, ACCENT if is_selected else BORDER)
