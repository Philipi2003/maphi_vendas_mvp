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
from features.catalog.catalog_logic import (
    Cake,
    CatalogController,
    ItemTypeImageCleanupError,
)
from features.catalog.catalog_card_view import CatalogCardView
from firebase_rest import FirebaseRestError
from features.pickup_spots.pickup_spots_logic import (
    PickupSpot,
    PickupSpotController,
)


class CatalogView:
    def __init__(
        self,
        page: ft.Page,
        controller: CatalogController,
        pickup_spot_controller: PickupSpotController,
        account_button: ft.Control,
        on_reserve,
        on_create_pickup_spot,
        on_edit_pickup_spot,
        on_delete_pickup_spot,
        on_create_item_type,
        on_update_item_type,
        on_delete_item_type,
        on_check_item_type_inventory,
        on_notice,
        on_message,
    ):
        self.page = page
        self.controller = controller
        self.pickup_spot_controller = pickup_spot_controller
        self.on_reserve = on_reserve
        self.on_create_pickup_spot = on_create_pickup_spot
        self.on_edit_pickup_spot = on_edit_pickup_spot
        self.on_delete_pickup_spot = on_delete_pickup_spot
        self.on_create_item_type = on_create_item_type
        self.on_update_item_type = on_update_item_type
        self.on_delete_item_type = on_delete_item_type
        self.on_check_item_type_inventory = on_check_item_type_inventory
        self.on_notice = on_notice
        self.on_message = on_message
        self.is_owner = False
        self.filter_controls: dict[str, ft.Container] = {}
        self.item_type_dialog: ft.AlertDialog | None = None
        self.editing_item_type: Cake | None = None
        self.item_type_name: ft.TextField | None = None
        self.item_type_description: ft.TextField | None = None
        self.item_type_regular_price: ft.TextField | None = None
        self.item_type_promotional_price: ft.TextField | None = None
        self.item_type_image_label: ft.Text | None = None
        self.item_type_custom_order: ft.Checkbox | None = None
        self.item_type_is_active: ft.Checkbox | None = None
        self.item_type_delete_button: ft.TextButton | None = None
        self.item_type_submit_button: ft.FilledButton | None = None
        self.selected_image_data: bytes | None = None
        self.selected_image_name: str | None = None
        self.selected_image_content_type: str | None = None
        self.image_picker = ft.FilePicker()
        self.page.services.append(self.image_picker)
        self.owner_add_button = ft.FilledButton(
            "Adicionar sabor",
            icon=ft.Icons.ADD,
            visible=False,
            on_click=self._open_item_type_form,
        )
        self.owner_add_pickup_spot_button = ft.OutlinedButton(
            "Adicionar local de retirada",
            icon=ft.Icons.ADD_LOCATION_ALT_OUTLINED,
            visible=False,
            on_click=self._open_pickup_spot_form,
        )
        self.pickup_spot_dropdown = ft.Dropdown(
            label="Local de retirada",
            hint_text="Carregando locais...",
            options=[],
            disabled=True,
            on_select=self._pickup_spot_changed,
        )
        self.pickup_spot_edit_button = ft.OutlinedButton(
            "Editar local",
            icon=ft.Icons.EDIT_OUTLINED,
            visible=False,
            disabled=True,
            on_click=self._edit_selected_pickup_spot,
        )
        self.pickup_spot_delete_button = ft.OutlinedButton(
            "Excluir local",
            icon=ft.Icons.DELETE_OUTLINE,
            style=ft.ButtonStyle(color=ACCENT),
            visible=False,
            disabled=True,
            on_click=self._ask_delete_selected_pickup_spot,
        )
        self.pickup_spot_details = ft.Text(
            "Carregando locais de retirada...",
            size=11,
            color=MUTED,
        )
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
                            content=ft.Column(
                                controls=[
                                    ft.Row(
                                        controls=[
                                            ft.Icon(
                                                ft.Icons.LOCAL_DINING_OUTLINED,
                                                color=GREEN,
                                                size=20,
                                            ),
                                            ft.Text(
                                                "Escolha o local de retirada",
                                                size=13,
                                                color=INK,
                                                weight=ft.FontWeight.W_600,
                                            ),
                                        ],
                                        spacing=12,
                                    ),
                                    ft.Row(
                                        controls=[
                                            self.pickup_spot_dropdown,
                                        ],
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                        spacing=0,
                                    ),
                                    ft.Row(
                                        controls=[
                                            self.pickup_spot_edit_button,
                                            self.pickup_spot_delete_button,
                                        ],
                                        spacing=8,
                                        wrap=True,
                                    ),
                                    self.pickup_spot_details,
                                ],
                                spacing=8,
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
                    content=ft.Column(
                        controls=[
                            self.selection_label,
                            self.owner_add_button,
                            self.owner_add_pickup_spot_button,
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.END,
                        spacing=8,
                    ),
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

    def set_owner(self, is_owner: bool) -> None:
        self.is_owner = is_owner
        self.owner_add_button.visible = is_owner
        self.owner_add_pickup_spot_button.visible = is_owner
        if (
            not is_owner
            and self.pickup_spot_controller.selected_pickup_spot_id
            not in {
                spot.id
                for spot in self.pickup_spot_controller.available_pickup_spots
            }
        ):
            self.pickup_spot_controller.select_pickup_spot(None)
        self.refresh_pickup_spot_options()
        self.refresh()
        self.page.update()

    async def _open_pickup_spot_form(self, _=None) -> None:
        await self.on_create_pickup_spot()

    def refresh_pickup_spot_options(self) -> None:
        pickup_spots = (
            self.pickup_spot_controller.pickup_spots
            if self.is_owner
            else self.pickup_spot_controller.available_pickup_spots
        )
        visible_ids = {spot.id for spot in pickup_spots}
        if (
            not self.is_owner
            and self.pickup_spot_controller.selected_pickup_spot_id
            not in visible_ids
        ):
            self.pickup_spot_controller.select_pickup_spot(None)
        self.pickup_spot_dropdown.options = [
            ft.DropdownOption(
                key=pickup_spot.id,
                text=self._pickup_spot_option_text(pickup_spot),
            )
            for pickup_spot in pickup_spots
        ]
        self.pickup_spot_dropdown.value = (
            self.pickup_spot_controller.selected_pickup_spot_id
        )
        self.pickup_spot_dropdown.disabled = not pickup_spots
        self.pickup_spot_dropdown.hint_text = (
            "Selecione um local de retirada"
            if pickup_spots
            else "Nenhum local de retirada disponível"
        )
        has_selected_spot = (
            self.pickup_spot_controller.selected_pickup_spot is not None
        )
        self.pickup_spot_edit_button.visible = self.is_owner
        self.pickup_spot_edit_button.disabled = not has_selected_spot
        self.pickup_spot_delete_button.visible = self.is_owner
        self.pickup_spot_delete_button.disabled = not has_selected_spot
        self._refresh_pickup_spot_details()

    def _pickup_spot_changed(self, event: ft.Event[ft.Dropdown]) -> None:
        try:
            self.pickup_spot_controller.select_pickup_spot(
                event.control.value,
                allow_unavailable=self.is_owner,
            )
        except ValueError as exc:
            self.on_message(str(exc))
        self.refresh_pickup_spot_options()
        self.page.update()

    def _refresh_pickup_spot_details(self) -> None:
        pickup_spot = self.pickup_spot_controller.selected_pickup_spot
        if pickup_spot is None:
            self.pickup_spot_details.value = (
                "Selecione um local de retirada."
                if self.pickup_spot_dropdown.options
                else "Nenhum local de retirada disponível."
            )
            return
        schedule = self._pickup_spot_schedule(pickup_spot)
        if not self.pickup_spot_controller.is_pickup_spot_available(pickup_spot):
            schedule += " · fora da janela para reserva"
        self.pickup_spot_details.value = (
            f"{pickup_spot.address}\nRetirada: {schedule}"
        )

    @staticmethod
    def _pickup_spot_schedule(pickup_spot: PickupSpot) -> str:
        if pickup_spot.arrival_at is None or pickup_spot.departure_at is None:
            return "Data e horário não definidos"
        return (
            f"{pickup_spot.arrival_at:%d/%m/%Y %H:%M} às "
            f"{pickup_spot.departure_at:%d/%m/%Y %H:%M}"
        )

    def _pickup_spot_option_text(self, pickup_spot: PickupSpot) -> str:
        schedule = self._pickup_spot_schedule(pickup_spot)
        if (
            self.is_owner
            and not self.pickup_spot_controller.is_pickup_spot_available(
                pickup_spot
            )
        ):
            return f"{pickup_spot.name} · indisponível"
        return f"{pickup_spot.name} · {schedule}"

    async def _edit_selected_pickup_spot(self, _=None) -> None:
        pickup_spot = self.pickup_spot_controller.selected_pickup_spot
        if pickup_spot is not None:
            await self.on_edit_pickup_spot(pickup_spot)

    def _ask_delete_selected_pickup_spot(self, _=None) -> None:
        pickup_spot = self.pickup_spot_controller.selected_pickup_spot
        if pickup_spot is None:
            return
        self.page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("Excluir local de retirada?"),
                content=ft.Text(
                    f'O local "{pickup_spot.name}" será removido permanentemente.'
                ),
                actions=[
                    ft.TextButton(
                        "Cancelar",
                        on_click=lambda _: self.page.pop_dialog(),
                    ),
                    ft.TextButton(
                        "Excluir",
                        on_click=self._delete_selected_pickup_spot,
                    ),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    async def _delete_selected_pickup_spot(self, _=None) -> None:
        pickup_spot = self.pickup_spot_controller.selected_pickup_spot
        if pickup_spot is None:
            return
        try:
            await self.on_delete_pickup_spot(pickup_spot.id)
            self.page.pop_dialog()
            self.refresh_pickup_spot_options()
            self.page.update()
            self.on_notice("Local de retirada excluído.")
        except FirebaseRestError as exc:
            self.on_message(
                f"Não foi possível excluir o local de retirada: {exc}"
            )
        except ValueError as exc:
            self.on_message(str(exc))

    async def _open_item_type_form(
        self, _=None, *, item_type: Cake | None = None
    ) -> None:
        can_delete = False
        if item_type is not None:
            try:
                can_delete = await self.on_check_item_type_inventory(item_type.id)
            except (FirebaseRestError, ValueError) as exc:
                self.on_message(f"Não foi possível verificar o estoque do sabor: {exc}")
                return

        self.editing_item_type = item_type
        self.item_type_name = ft.TextField(
            label="Nome do sabor",
            value=item_type.name if item_type else "",
            border_radius=12,
            autofocus=True,
        )
        self.item_type_description = ft.TextField(
            label="Descrição",
            value=item_type.description if item_type else "",
            multiline=True,
            min_lines=2,
            max_lines=4,
            border_radius=12,
        )
        self.item_type_regular_price = ft.TextField(
            label="Preço normal (R$)",
            hint_text="Ex.: 45,00",
            value=self._price_field_value(
                item_type.regular_price if item_type else None
            ),
            keyboard_type=ft.KeyboardType.NUMBER,
            border_radius=12,
        )
        self.item_type_promotional_price = ft.TextField(
            label="Preço promocional (opcional)",
            hint_text="Ex.: 39,90",
            value=self._price_field_value(
                item_type.promotional_price if item_type else None
            ),
            keyboard_type=ft.KeyboardType.NUMBER,
            border_radius=12,
        )
        self.selected_image_data = None
        self.selected_image_name = None
        self.selected_image_content_type = None
        self.item_type_image_label = ft.Text(
            (
                "Foto atual (selecione para substituir)"
                if item_type and item_type.image_url
                else "Nenhuma foto selecionada"
            ),
            color=MUTED,
            size=12,
        )
        self.item_type_custom_order = ft.Checkbox(
            label="Somente sob encomenda",
            value=item_type.is_custom_order_only if item_type else False,
        )
        self.item_type_is_active = ft.Checkbox(
            label="Ativo no catálogo",
            value=item_type.is_active if item_type else True,
        )
        self.item_type_submit_button = ft.FilledButton(
            "Salvar alterações" if item_type else "Salvar sabor",
            icon=ft.Icons.SAVE_OUTLINED,
            on_click=self._submit_item_type,
        )
        self.item_type_delete_button = ft.TextButton(
            "Excluir sabor",
            visible=bool(item_type and can_delete),
            on_click=self._ask_delete_item_type,
        )
        self.item_type_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Editar sabor" if item_type else "Novo sabor"),
            content=ft.Container(
                width=440,
                content=ft.Column(
                    controls=[
                        self.item_type_name,
                        self.item_type_description,
                        self.item_type_regular_price,
                        self.item_type_promotional_price,
                        ft.Row(
                            controls=[
                                ft.OutlinedButton(
                                    "Adicionar foto",
                                    icon=ft.Icons.IMAGE_OUTLINED,
                                    on_click=self._pick_item_type_image,
                                ),
                                self.item_type_image_label,
                            ],
                            spacing=10,
                        ),
                        self.item_type_custom_order,
                        self.item_type_is_active,
                    ],
                    tight=True,
                    spacing=12,
                ),
            ),
            actions=[
                ft.TextButton(
                    "Cancelar",
                    on_click=lambda _: self._close_item_type_form(),
                ),
                self.item_type_delete_button,
                self.item_type_submit_button,
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.show_dialog(self.item_type_dialog)

    @staticmethod
    def _price_field_value(value: float | None) -> str:
        return f"{value:.2f}".replace(".", ",") if value is not None else ""

    async def _pick_item_type_image(self, _=None) -> None:
        selected_files = await self.image_picker.pick_files(
            dialog_title="Selecione uma foto do sabor",
            file_type=ft.FilePickerFileType.IMAGE,
            allow_multiple=False,
            with_data=True,
        )
        if not selected_files:
            return

        selected_file = selected_files[0]
        extension = selected_file.name.rsplit(".", 1)[-1].lower()
        content_types = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "webp": "image/webp",
        }
        content_type = content_types.get(extension)
        if content_type is None:
            self.on_message("Use uma foto JPG, PNG ou WEBP.")
            return
        if selected_file.size > 5 * 1024 * 1024:
            self.on_message("A foto deve ter no máximo 5 MB.")
            return
        if selected_file.bytes is None:
            self.on_message("Não foi possível ler a foto selecionada.")
            return

        self.selected_image_data = selected_file.bytes
        self.selected_image_name = selected_file.name
        self.selected_image_content_type = content_type
        if self.item_type_image_label is not None:
            self.item_type_image_label.value = selected_file.name
            self.page.update()

    def _close_item_type_form(self) -> None:
        if self.item_type_dialog is not None:
            self.page.pop_dialog()
            self.item_type_dialog = None
        self.editing_item_type = None

    async def _submit_item_type(self, _=None) -> None:
        if (
            self.item_type_name is None
            or self.item_type_description is None
            or self.item_type_regular_price is None
            or self.item_type_promotional_price is None
            or self.item_type_custom_order is None
            or self.item_type_is_active is None
        ):
            raise RuntimeError("O formulário de sabor não foi inicializado.")

        name = (self.item_type_name.value or "").strip()
        if not name:
            self.on_message("Informe o nome do sabor.")
            return

        if self.item_type_submit_button is not None:
            self.item_type_submit_button.disabled = True
            self.page.update()

        try:
            values = {
                "name": name,
                "description": self.item_type_description.value or "",
                "regular_price": self.item_type_regular_price.value or "",
                "promotional_price": self.item_type_promotional_price.value or "",
                "is_custom_order_only": bool(self.item_type_custom_order.value),
                "is_active": bool(self.item_type_is_active.value),
                "image_data": self.selected_image_data,
                "image_filename": self.selected_image_name,
                "image_content_type": self.selected_image_content_type,
            }
            if self.editing_item_type is None:
                await self.on_create_item_type(**values)
                success_message = "Sabor adicionado ao catálogo."
            else:
                await self.on_update_item_type(
                    item_type_id=self.editing_item_type.id,
                    **values,
                )
                success_message = "Sabor atualizado."

            self.refresh()
            self._close_item_type_form()
            self.page.update()
            self.on_notice(success_message)
        except ItemTypeImageCleanupError as exc:
            self.refresh()
            self._close_item_type_form()
            self.page.update()
            self.on_message(str(exc))
        except FirebaseRestError as exc:
            self.on_message(f"Não foi possível salvar o sabor: {exc}")
        except ValueError as exc:
            self.on_message(str(exc))
        finally:
            if self.item_type_dialog is not None:
                if self.item_type_submit_button is not None:
                    self.item_type_submit_button.disabled = False
                self.page.update()

    def _ask_delete_item_type(self, _=None) -> None:
        if self.editing_item_type is None:
            return
        self.page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("Excluir sabor?"),
                content=ft.Text(
                    f'O sabor "{self.editing_item_type.name}" será removido '
                    "permanentemente do catálogo."
                ),
                actions=[
                    ft.TextButton(
                        "Cancelar",
                        on_click=lambda _: self.page.pop_dialog(),
                    ),
                    ft.TextButton(
                        "Excluir",
                        on_click=self._confirm_delete_item_type,
                    ),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    async def _confirm_delete_item_type(self, _=None) -> None:
        if self.editing_item_type is None:
            return
        item_type = self.editing_item_type
        try:
            await self.on_delete_item_type(item_type.id)
            self.page.pop_dialog()
            self.refresh()
            self._close_item_type_form()
            self.page.update()
            self.on_notice("Sabor excluído do catálogo.")
        except FirebaseRestError as exc:
            self.on_message(f"Não foi possível excluir o sabor: {exc}")
        except ValueError as exc:
            self.on_message(str(exc))

    def _choose_filter(self, value: str) -> None:
        self.controller.set_filter(value)
        self.refresh()
        self.page.update()

    def _search_changed(self, event: ft.Event[ft.TextField]) -> None:
        self.controller.set_search_query(event.control.value or "")
        self.refresh()
        self.page.update()

    def _cake_card(self, cake: Cake) -> ft.Control:
        async def edit_item_type() -> None:
            await self._open_item_type_form(item_type=cake)

        return CatalogCardView(
            cake,
            quantity=self.controller.quantities[cake.id],
            is_owner=self.is_owner,
            on_quantity_change=lambda amount: self._change_cake_quantity(
                cake.id, amount
            ),
            on_edit=edit_item_type if self.is_owner else None,
        ).build()

    def _change_cake_quantity(self, cake_id: str, amount: int) -> None:
        self.controller.change_quantity(cake_id, amount)
        self.refresh()
        self.page.update()

    def refresh(self) -> None:
        cakes = self.controller.filtered_cakes
        self.catalog_grid.controls = [
            self._cake_card(cake) for cake in cakes
        ]
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
