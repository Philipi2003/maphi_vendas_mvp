from collections.abc import Awaitable, Callable

import flet as ft

from app_config import (
    ACCENT,
    BACKGROUND,
    BORDER,
    GREEN,
    INK,
    MUTED,
    SURFACE,
)
from features.catalog.catalog_logic import Cake


class CatalogCardView:
    def __init__(
        self,
        cake: Cake,
        *,
        quantity: int,
        is_owner: bool,
        on_quantity_change: Callable[[int], None],
        on_edit: Callable[[], Awaitable[None]] | None = None,
        on_remove_stock: Callable[[], Awaitable[None]] | None = None,
    ):
        self.cake = cake
        self.quantity = quantity
        self.is_owner = is_owner
        self.on_quantity_change = on_quantity_change
        self.on_edit = on_edit
        self.on_remove_stock = on_remove_stock

    def build(self) -> ft.Control:
        cake = self.cake
        available = cake.stock > 0
        if not cake.is_active:
            status_text = "Inativo"
        elif available:
            status_text = (
                f"{cake.stock} não reservados"
                if self.is_owner
                else f"{cake.stock} disponíveis"
            )
        elif cake.is_custom_order_only:
            status_text = "Sob encomenda"
        else:
            status_text = "Esgotado no momento"
        status_color = GREEN if cake.is_active and available else MUTED

        if available:
            footer_controls = [self._quantity_control()]
            if self.is_owner and self.on_remove_stock is not None:
                footer_controls.append(
                    ft.TextButton(
                        "Remover 1 não reservado",
                        icon=ft.Icons.DELETE_OUTLINE,
                        on_click=self._remove_stock,
                    )
                )
            footer = ft.Column(controls=footer_controls, spacing=4)
        else:
            footer = ft.Container(
                content=ft.Text(
                    (
                        "Encomendas ainda indisponíveis"
                        if cake.is_custom_order_only
                        else "Avise-me quando voltar"
                    ),
                    color=MUTED,
                    size=12,
                    weight=ft.FontWeight.W_500,
                ),
                alignment=ft.Alignment.CENTER,
                border=ft.Border.all(1, BORDER),
                border_radius=14,
                padding=ft.Padding.symmetric(vertical=12),
            )
        overlays = [
            ft.Container(
                expand=True,
                alignment=ft.Alignment.CENTER,
                content=(
                    ft.Image(
                        src=cake.image_url,
                        fit=ft.BoxFit.COVER,
                        width=280,
                        height=158,
                    )
                    if cake.image_url
                    else ft.Icon(
                        ft.Icons.CAKE_OUTLINED,
                        size=58,
                        color=ACCENT,
                    )
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
                padding=ft.Padding.symmetric(horizontal=10, vertical=7),
                right=12,
                top=12,
            ),
        ]
        if self.on_edit is not None:
            overlays.append(
                ft.Container(
                    content=ft.IconButton(
                        icon=ft.Icons.EDIT_OUTLINED,
                        tooltip="Editar sabor",
                        icon_color=ACCENT,
                        bgcolor=SURFACE,
                        on_click=self._edit_item_type,
                    ),
                    left=8,
                    top=8,
                    visible=self.is_owner,
                )
            )

        return ft.Container(
            col={"xs": 12, "sm": 6, "md": 4, "lg": 3},
            content=ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Container(
                            content=ft.Stack(controls=overlays),
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
                                *(
                                    [self._price()]
                                    if cake.regular_price is not None
                                    else []
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
                height=366,
                shadow=ft.BoxShadow(
                    blur_radius=18,
                    color="#12000000",
                    offset=ft.Offset(0, 5),
                ),
            ),
        )

    def _quantity_control(self) -> ft.Control:
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.IconButton(
                        icon=ft.Icons.REMOVE,
                        icon_size=17,
                        icon_color=ACCENT if self.quantity else MUTED,
                        disabled=self.quantity == 0,
                        tooltip="Remover uma unidade",
                        on_click=lambda _: self.on_quantity_change(-1),
                    ),
                    ft.Text(
                        str(self.quantity),
                        width=24,
                        text_align=ft.TextAlign.CENTER,
                        weight=ft.FontWeight.W_600,
                        color=INK,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.ADD,
                        icon_size=17,
                        icon_color=ACCENT,
                        disabled=self.quantity >= self.cake.stock,
                        tooltip="Adicionar uma unidade",
                        on_click=lambda _: self.on_quantity_change(1),
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

    def _price(self) -> ft.Control:
        regular_price = self.cake.regular_price
        if regular_price is None:
            raise RuntimeError("Não há preço normal para exibir neste card.")

        regular = f"R$ {regular_price:.2f}".replace(".", ",")
        if self.cake.promotional_price is None:
            return ft.Text(
                regular,
                size=14,
                weight=ft.FontWeight.W_600,
                color=INK,
            )

        promotional = f"R$ {self.cake.promotional_price:.2f}".replace(".", ",")
        return ft.Row(
            controls=[
                ft.Text(
                    regular,
                    size=12,
                    color=MUTED,
                    style=ft.TextStyle(decoration=ft.TextDecoration.LINE_THROUGH),
                ),
                ft.Text(
                    promotional,
                    size=14,
                    weight=ft.FontWeight.W_700,
                    color=ACCENT,
                ),
            ],
            spacing=8,
        )

    async def _edit_item_type(self, _=None) -> None:
        if self.on_edit is not None:
            await self.on_edit()

    async def _remove_stock(self, _=None) -> None:
        if self.on_remove_stock is not None:
            await self.on_remove_stock()
