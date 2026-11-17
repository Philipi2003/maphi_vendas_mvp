from collections.abc import Callable
from datetime import date, datetime, time

import flet as ft

from app_config import INK
from features.pickup_spots.pickup_spots_logic import PickupSpot
from firebase_rest import FirebaseRestError


class PickupSpotFormView:
    def __init__(
        self, page: ft.Page, *, on_create, on_update, on_notice, on_message
    ):
        self.page = page
        self.on_create = on_create
        self.on_update = on_update
        self.on_notice = on_notice
        self.on_message = on_message
        self.dialog: ft.AlertDialog | None = None
        self.editing_pickup_spot: PickupSpot | None = None
        self.name_field: ft.TextField | None = None
        self.address_field: ft.TextField | None = None
        self.arrival_date: date | None = None
        self.arrival_time: time | None = None
        self.departure_date: date | None = None
        self.departure_time: time | None = None
        self.arrival_date_label: ft.Text | None = None
        self.arrival_time_label: ft.Text | None = None
        self.departure_date_label: ft.Text | None = None
        self.departure_time_label: ft.Text | None = None
        self.arrival_date_picker: ft.DatePicker | None = None
        self.arrival_time_picker: ft.TimePicker | None = None
        self.departure_date_picker: ft.DatePicker | None = None
        self.departure_time_picker: ft.TimePicker | None = None
        self.form_error: ft.Text | None = None
        self.submit_button: ft.FilledButton | None = None

    def open_form(self, pickup_spot: PickupSpot | None = None) -> None:
        self.editing_pickup_spot = pickup_spot
        self.arrival_date = (
            pickup_spot.arrival_at.date()
            if pickup_spot and pickup_spot.arrival_at
            else None
        )
        self.arrival_time = (
            pickup_spot.arrival_at.time().replace(tzinfo=None)
            if pickup_spot and pickup_spot.arrival_at
            else None
        )
        self.departure_date = (
            pickup_spot.departure_at.date()
            if pickup_spot and pickup_spot.departure_at
            else None
        )
        self.departure_time = (
            pickup_spot.departure_at.time().replace(tzinfo=None)
            if pickup_spot and pickup_spot.departure_at
            else None
        )
        self.name_field = ft.TextField(
            label="Nome do local",
            hint_text="Ex.: Loja do Centro",
            value=pickup_spot.name if pickup_spot else "",
            border_radius=12,
            autofocus=True,
            on_change=self._clear_form_error,
        )
        self.address_field = ft.TextField(
            label="Endereço",
            hint_text="Rua, número, bairro e cidade",
            value=pickup_spot.address if pickup_spot else "",
            multiline=True,
            min_lines=2,
            max_lines=3,
            border_radius=12,
            on_change=self._clear_form_error,
        )
        self.arrival_date_label = ft.Text(self._format_date(self.arrival_date))
        self.arrival_time_label = ft.Text(self._format_time(self.arrival_time))
        self.departure_date_label = ft.Text(
            self._format_date(self.departure_date)
        )
        self.departure_time_label = ft.Text(
            self._format_time(self.departure_time)
        )
        self.arrival_date_picker = ft.DatePicker(
            value=self.arrival_date,
            modal=True,
            locale=ft.Locale("pt", "BR"),
            help_text="Data de chegada",
            cancel_text="Cancelar",
            confirm_text="Selecionar",
            on_change=self._arrival_date_changed,
        )
        self.arrival_time_picker = ft.TimePicker(
            value=self.arrival_time,
            modal=True,
            entry_mode=ft.TimePickerEntryMode.INPUT_ONLY,
            hour_format=ft.TimePickerHourFormat.H24,
            help_text="Horário de chegada",
            cancel_text="Cancelar",
            confirm_text="Selecionar",
            on_change=self._arrival_time_changed,
        )
        self.departure_date_picker = ft.DatePicker(
            value=self.departure_date,
            modal=True,
            locale=ft.Locale("pt", "BR"),
            help_text="Data de saída",
            cancel_text="Cancelar",
            confirm_text="Selecionar",
            on_change=self._departure_date_changed,
        )
        self.departure_time_picker = ft.TimePicker(
            value=self.departure_time,
            modal=True,
            entry_mode=ft.TimePickerEntryMode.INPUT_ONLY,
            hour_format=ft.TimePickerHourFormat.H24,
            help_text="Horário de saída",
            cancel_text="Cancelar",
            confirm_text="Selecionar",
            on_change=self._departure_time_changed,
        )
        self.form_error = ft.Text(
            color="#B3261E",
            size=13,
            visible=False,
        )
        self.submit_button = ft.FilledButton(
            "Salvar alterações" if pickup_spot else "Salvar local",
            icon=ft.Icons.SAVE_OUTLINED,
            on_click=self._submit,
        )
        self.dialog = ft.AlertDialog(
            modal=False,
            title=ft.Text(
                "Editar local de retirada" if pickup_spot else "Novo local de retirada",
                color=INK,
            ),
            content=ft.Container(
                width=440,
                content=ft.Column(
                    controls=[
                        self.name_field,
                        self.address_field,
                        self._date_time_picker_row(
                            "Chegada",
                            self.arrival_date_label,
                            self.arrival_time_label,
                            self._open_arrival_date_picker,
                            self._open_arrival_time_picker,
                        ),
                        self._date_time_picker_row(
                            "Saída",
                            self.departure_date_label,
                            self.departure_time_label,
                            self._open_departure_date_picker,
                            self._open_departure_time_picker,
                        ),
                        self.form_error,
                    ],
                    tight=True,
                    spacing=12,
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

    @staticmethod
    def _format_date(value: date | None) -> str:
        return value.strftime("%d/%m/%Y") if value is not None else "Selecionar data"

    @staticmethod
    def _format_time(value: time | None) -> str:
        return value.strftime("%H:%M") if value is not None else "Selecionar horário"

    @staticmethod
    def _date_time_picker_row(
        title: str,
        date_label: ft.Text,
        time_label: ft.Text,
        on_select_date: Callable[[], None],
        on_select_time: Callable[[], None],
    ) -> ft.Control:
        return ft.Column(
            controls=[
                ft.Text(title, weight=ft.FontWeight.W_600),
                ft.Row(
                    controls=[
                        ft.OutlinedButton(
                            content=ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.CALENDAR_MONTH_OUTLINED),
                                    date_label,
                                ],
                                tight=True,
                                spacing=8,
                            ),
                            on_click=on_select_date,
                        ),
                        ft.OutlinedButton(
                            content=ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.SCHEDULE_OUTLINED),
                                    time_label,
                                ],
                                tight=True,
                                spacing=8,
                            ),
                            on_click=on_select_time,
                        ),
                    ],
                    spacing=8,
                    wrap=True,
                ),
            ],
            spacing=6,
        )

    def _open_arrival_date_picker(self, _=None) -> None:
        if self.arrival_date_picker is not None:
            self.page.show_dialog(self.arrival_date_picker)

    def _open_arrival_time_picker(self, _=None) -> None:
        if self.arrival_time_picker is not None:
            self.page.show_dialog(self.arrival_time_picker)

    def _open_departure_date_picker(self, _=None) -> None:
        if self.departure_date_picker is not None:
            self.page.show_dialog(self.departure_date_picker)

    def _open_departure_time_picker(self, _=None) -> None:
        if self.departure_time_picker is not None:
            self.page.show_dialog(self.departure_time_picker)

    def _arrival_date_changed(self, event) -> None:
        value = event.control.value
        self.arrival_date = value.date() if isinstance(value, datetime) else value
        if self.arrival_date_label is not None:
            self.arrival_date_label.value = self._format_date(self.arrival_date)
        self._clear_form_error()
        self.page.update()

    def _arrival_time_changed(self, event) -> None:
        self.arrival_time = event.control.value
        if self.arrival_time_label is not None:
            self.arrival_time_label.value = self._format_time(self.arrival_time)
        self._clear_form_error()
        self.page.update()

    def _departure_date_changed(self, event) -> None:
        value = event.control.value
        self.departure_date = value.date() if isinstance(value, datetime) else value
        if self.departure_date_label is not None:
            self.departure_date_label.value = self._format_date(
                self.departure_date
            )
        self._clear_form_error()
        self.page.update()

    def _departure_time_changed(self, event) -> None:
        self.departure_time = event.control.value
        if self.departure_time_label is not None:
            self.departure_time_label.value = self._format_time(
                self.departure_time
            )
        self._clear_form_error()
        self.page.update()

    @staticmethod
    def _format_datetime(day: date, clock: time) -> str:
        return f"{day:%d/%m/%Y} {clock:%H:%M}"

    def _on_dismiss(self, _=None) -> None:
        self.dialog = None

    def _close(self) -> None:
        if self.dialog is not None:
            self.page.pop_dialog()
            self.dialog = None

    def _clear_form_error(self, _=None) -> None:
        if self.form_error is not None and self.form_error.visible:
            self.form_error.visible = False
            self.page.update()

    async def _submit(self, _=None) -> None:
        if (
            self.name_field is None
            or self.address_field is None
            or self.form_error is None
            or self.submit_button is None
        ):
            raise RuntimeError("O formulário do local não foi inicializado.")

        self.form_error.visible = False
        self.submit_button.disabled = True
        self.page.update()
        try:
            if self.arrival_date is None or self.arrival_time is None:
                raise ValueError("Selecione a data e o horário de chegada.")
            if self.departure_date is None or self.departure_time is None:
                raise ValueError("Selecione a data e o horário de saída.")
            values = {
                "name": self.name_field.value or "",
                "address": self.address_field.value or "",
                "arrival_at": self._format_datetime(
                    self.arrival_date, self.arrival_time
                ),
                "departure_at": self._format_datetime(
                    self.departure_date, self.departure_time
                ),
            }
            if self.editing_pickup_spot is None:
                await self.on_create(**values)
                success_message = "Local de retirada criado."
            else:
                await self.on_update(
                    pickup_spot_id=self.editing_pickup_spot.id,
                    **values,
                )
                success_message = "Local de retirada atualizado."
            self._close()
            self.page.update()
            self.on_notice(success_message)
        except FirebaseRestError as exc:
            self.on_message(
                f"Não foi possível salvar o local de retirada: {exc}"
            )
        except ValueError as exc:
            self.form_error.value = str(exc)
            self.form_error.visible = True
            self.page.update()
        finally:
            if self.dialog is not None and self.submit_button is not None:
                self.submit_button.disabled = False
                self.page.update()
