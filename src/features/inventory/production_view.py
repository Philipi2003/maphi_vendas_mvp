from dataclasses import dataclass

import flet as ft

from app_config import ACCENT, INK
from features.catalog.catalog_logic import Cake
from firebase_rest import FirebaseRestError


@dataclass
class ProductionEntry:
    item_type: ft.Dropdown
    quantity: ft.TextField
    control: ft.Row | None = None


class ProductionFormView:
    def __init__(
        self, page: ft.Page, *, on_submit, on_notice, on_message
    ):
        self.page = page
        self.on_submit = on_submit
        self.on_notice = on_notice
        self.on_message = on_message
        self.item_types: list[Cake] = []
        self.entries: list[ProductionEntry] = []
        self.entries_column: ft.Column | None = None
        self.form_error: ft.Text | None = None
        self.submit_button: ft.FilledButton | None = None
        self.dialog: ft.AlertDialog | None = None

    def open_form(self, item_types: list[Cake]) -> None:
        if not item_types:
            self.on_message("Cadastre um sabor antes de registrar a produção.")
            return

        self.item_types = item_types
        self.entries = []
        self.entries_column = ft.Column(spacing=8)
        self.form_error = ft.Text(color="#B3261E", size=13, visible=False)
        self.submit_button = ft.FilledButton(
            "Adicionar ao estoque",
            icon=ft.Icons.ADD,
            on_click=self._submit,
        )
        self._add_entry(refresh=False)
        self.dialog = ft.AlertDialog(
            modal=False,
            title=ft.Text("Registrar produção", color=INK),
            content=ft.Container(
                width=520,
                height=400,
                content=ft.Column(
                    controls=[
                        ft.Text(
                            "Informe os sabores e a quantidade produzida "
                            "de cada um. O limite é 500 unidades por inserção."
                        ),
                        self.entries_column,
                        ft.OutlinedButton(
                            "Adicionar outro sabor",
                            icon=ft.Icons.ADD,
                            on_click=self._add_entry,
                        ),
                        self.form_error,
                    ],
                    spacing=12,
                    scroll=ft.ScrollMode.AUTO,
                ),
            ),
            actions=[
                ft.TextButton(
                    "Cancelar",
                    on_click=lambda _: self._close(),
                ),
                self.submit_button,
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            on_dismiss=self._on_dismiss,
        )
        self.page.show_dialog(self.dialog)

    def _add_entry(self, _=None, *, refresh: bool = True) -> None:
        if self.entries_column is None:
            return
        entry = ProductionEntry(
            item_type=ft.Dropdown(
                label="Sabor",
                options=[
                    ft.DropdownOption(
                        key=cake.id,
                        text=self._item_type_label(cake),
                    )
                    for cake in self.item_types
                ],
                expand=True,
                on_select=self._clear_error,
            ),
            quantity=ft.TextField(
                label="Unidades",
                value="1",
                width=110,
                keyboard_type=ft.KeyboardType.NUMBER,
                on_change=self._clear_error,
            ),
        )
        entry.control = ft.Row(
            controls=[
                entry.item_type,
                entry.quantity,
                ft.IconButton(
                    icon=ft.Icons.DELETE_OUTLINE,
                    icon_color=ACCENT,
                    tooltip="Remover sabor",
                    on_click=lambda _, current=entry: self._remove_entry(current),
                ),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.entries.append(entry)
        self.entries_column.controls.append(entry.control)
        if refresh:
            self.page.update()

    def _remove_entry(self, entry: ProductionEntry) -> None:
        if self.entries_column is None or entry.control is None:
            return
        self.entries.remove(entry)
        self.entries_column.controls.remove(entry.control)
        self.page.update()

    def _clear_error(self, _=None) -> None:
        if self.form_error is not None and self.form_error.visible:
            self.form_error.visible = False
            self.page.update()

    @staticmethod
    def _item_type_label(cake: Cake) -> str:
        label = cake.name
        if not cake.is_active:
            label += " (inativo)"
        elif cake.is_custom_order_only:
            label += " (sob encomenda)"
        return label

    def _collect_additions(self) -> dict[str, int]:
        if not self.entries:
            raise ValueError("Adicione ao menos um sabor à produção.")

        quantities: dict[str, int] = {}
        for index, entry in enumerate(self.entries, start=1):
            item_type_id = entry.item_type.value
            if not item_type_id:
                raise ValueError(f"Selecione o sabor da linha {index}.")
            raw_quantity = (entry.quantity.value or "").strip()
            try:
                quantity = int(raw_quantity)
            except ValueError as exc:
                raise ValueError(
                    f"Informe um número inteiro de unidades na linha {index}."
                ) from exc
            if quantity <= 0:
                raise ValueError(
                    f"A quantidade da linha {index} deve ser maior que zero."
                )
            quantities[item_type_id] = (
                quantities.get(item_type_id, 0) + quantity
            )
        return quantities

    def _show_error(self, message: str) -> None:
        if self.form_error is not None:
            self.form_error.value = message
            self.form_error.visible = True
            self.page.update()

    async def _submit(self, _=None) -> None:
        if self.form_error is None or self.submit_button is None:
            raise RuntimeError("O formulário de produção não foi inicializado.")

        self.form_error.visible = False
        self.submit_button.disabled = True
        self.page.update()
        try:
            quantities = self._collect_additions()
            total_units = await self.on_submit(quantities)
            self._close()
            self.page.update()
            if total_units == 1:
                message = "1 bolo adicionado ao estoque."
            else:
                message = f"{total_units} bolos adicionados ao estoque."
            self.on_notice(message)
        except FirebaseRestError as exc:
            self._show_error(f"Não foi possível registrar a produção: {exc}")
        except ValueError as exc:
            self._show_error(str(exc))
        finally:
            if self.dialog is not None and self.submit_button is not None:
                self.submit_button.disabled = False
                self.page.update()

    def _on_dismiss(self, _=None) -> None:
        self.dialog = None

    def _close(self) -> None:
        if self.dialog is not None:
            self.page.pop_dialog()
            self.dialog = None
