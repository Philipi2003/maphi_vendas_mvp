import flet as ft

from app_config import ACCENT, BACKGROUND, BORDER, GREEN, INK, MUTED, SURFACE
from features.pickup_spots.pickup_spots_logic import LOCAL_TIMEZONE, PickupSpot
from features.reservations.reservation_logic import Reservation
from firebase_rest import FirebaseRestError


class ReservationView:
    def __init__(
        self,
        page: ft.Page,
        *,
        on_back,
        on_cancel,
        on_complete,
        on_delete,
        on_filter,
        on_refresh,
        on_message,
    ):
        self.page = page
        self.on_back = on_back
        self.on_cancel = on_cancel
        self.on_complete = on_complete
        self.on_delete = on_delete
        self.on_filter = on_filter
        self.on_refresh = on_refresh
        self.on_message = on_message
        self.is_owner = False
        self.pickup_spots: list[PickupSpot] = []
        self.reservations: list[Reservation] = []
        self.selected_pickup_spot_id: str | None = None
        self.title = ft.Text(
            "Minhas reservas",
            size=24,
            weight=ft.FontWeight.BOLD,
            color=INK,
        )
        self.filter_dropdown = ft.Dropdown(
            label="Filtrar por local",
            width=360,
            on_select=self._filter_changed,
            options=[],
            visible=False,
        )
        self.list_column = ft.Column(spacing=12, expand=True)
        self.root = ft.Container(
            visible=False,
            expand=True,
            bgcolor=BACKGROUND,
            content=ft.SafeArea(
                expand=True,
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.IconButton(
                                    icon=ft.Icons.ARROW_BACK,
                                    tooltip="Voltar ao catálogo",
                                    on_click=lambda _: self.close(),
                                ),
                                self.title,
                                ft.Container(expand=True),
                                ft.IconButton(
                                    icon=ft.Icons.REFRESH,
                                    tooltip="Atualizar reservas",
                                    on_click=lambda _: self.on_refresh(),
                                ),
                            ],
                            spacing=8,
                        ),
                        self.filter_dropdown,
                        self.list_column,
                    ],
                    spacing=16,
                    scroll=ft.ScrollMode.AUTO,
                    expand=True,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ),
            padding=ft.Padding.symmetric(horizontal=20, vertical=16),
        )

    def open(self) -> None:
        self.root.visible = True
        self.page.update()

    def close(self) -> None:
        self.root.visible = False
        self.page.update()
        self.on_back()

    def set_reservations(
        self,
        reservations: list[Reservation],
        *,
        is_owner: bool,
        pickup_spots: list[PickupSpot],
        selected_pickup_spot_id: str | None,
    ) -> None:
        self.reservations = reservations
        self.is_owner = is_owner
        self.pickup_spots = pickup_spots
        self.selected_pickup_spot_id = selected_pickup_spot_id
        self.title.value = "Todas as reservas" if is_owner else "Minhas reservas"
        self.filter_dropdown.visible = is_owner
        pickup_spot_names = {spot.id: spot.name for spot in pickup_spots}
        for reservation in reservations:
            pickup_spot_names.setdefault(
                reservation.pickup_spot_id, reservation.pickup_spot_name
            )
        if selected_pickup_spot_id:
            pickup_spot_names.setdefault(
                selected_pickup_spot_id, "Local removido"
            )
        self.filter_dropdown.options = [
            ft.DropdownOption(key="", text="Todos os locais"),
            *[
                ft.DropdownOption(key=spot_id, text=spot_name)
                for spot_id, spot_name in pickup_spot_names.items()
            ],
        ]
        self.filter_dropdown.value = selected_pickup_spot_id or ""
        if reservations:
            self.list_column.controls = [
                self._reservation_card(reservation)
                for reservation in reservations
            ]
        else:
            self.list_column.controls = [
                ft.Container(
                    content=ft.Text(
                        "Nenhuma reserva encontrada.",
                        color=MUTED,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    padding=24,
                    alignment=ft.Alignment.CENTER,
                )
            ]
        self.page.update()

    def _reservation_card(self, reservation: Reservation) -> ft.Control:
        status_color = (
            GREEN
            if reservation.is_active
            else ACCENT
            if reservation.status == "CANCELADA"
            else MUTED
        )
        details = [
            ft.Text(
                f"Local: {reservation.pickup_spot_name}",
                weight=ft.FontWeight.W_600,
                color=INK,
            ),
            ft.Text(reservation.pickup_spot_address, color=MUTED, size=13),
            ft.Text(
                self._pickup_time(reservation),
                color=MUTED,
                size=13,
            ),
            ft.Text(
                "Venda presencial"
                if reservation.sale_type == "NORMAL"
                else "Reserva promocional",
                color=MUTED,
                size=13,
            ),
            ft.Divider(height=1, color=BORDER),
        ]
        if self.is_owner:
            details.append(
                ft.Text(
                    f"Cliente: {reservation.user_name}",
                    color=INK,
                    size=14,
                )
            )
        details.extend(
            ft.Text(
                f"{name} · {self._currency(price)}",
                color=INK,
                size=14,
            )
            for name, price in zip(
                reservation.item_type_names, reservation.unit_prices
            )
        )
        details.extend(
            [
                ft.Text(
                    f"Total a pagar: {self._currency(reservation.total_amount)}",
                    weight=ft.FontWeight.BOLD,
                    color=ACCENT,
                    size=16,
                ),
                ft.Text(
                    f"Reserva criada em {self._datetime(reservation.created_at)}",
                    color=MUTED,
                    size=12,
                ),
            ]
        )
        if reservation.status == "CONCLUIDA" and reservation.completed_at:
            details.append(
                ft.Text(
                    f"Venda finalizada em {self._datetime(reservation.completed_at)}",
                    color=GREEN,
                    size=12,
                )
            )
        if reservation.status == "CANCELADA" and reservation.cancelled_at:
            details.append(
                ft.Text(
                    f"Cancelada em {self._datetime(reservation.cancelled_at)}",
                    color=MUTED,
                    size=12,
                )
            )

        actions = []
        if reservation.is_active:
            actions.append(
                ft.TextButton(
                    "Cancelar reserva",
                    icon=ft.Icons.CANCEL_OUTLINED,
                    on_click=lambda _: self._confirm_action(
                        reservation,
                        action="cancel",
                        title="Cancelar esta reserva?",
                    ),
                )
            )
            if self.is_owner:
                actions.append(
                    ft.FilledButton(
                        "Finalizar venda",
                        icon=ft.Icons.POINT_OF_SALE_OUTLINED,
                        on_click=lambda _: self._confirm_action(
                            reservation,
                            action="complete",
                            title="Confirmar que a venda foi finalizada?",
                        ),
                    )
                )
        elif self.is_owner:
            actions.append(
                ft.TextButton(
                    "Apagar reserva",
                    icon=ft.Icons.DELETE_OUTLINE,
                    on_click=lambda _: self._confirm_action(
                        reservation,
                        action="delete",
                        title="Apagar esta reserva do sistema?",
                    ),
                )
            )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(
                                f"Reserva #{reservation.id[:8]}",
                                weight=ft.FontWeight.BOLD,
                                color=INK,
                            ),
                            ft.Container(expand=True),
                            ft.Text(
                                reservation.status_label,
                                color=status_color,
                                weight=ft.FontWeight.W_600,
                            ),
                        ]
                    ),
                    *details,
                    ft.Row(
                        controls=actions,
                        alignment=ft.MainAxisAlignment.END,
                        wrap=True,
                    ),
                ],
                spacing=8,
                tight=True,
            ),
            width=760,
            padding=18,
            bgcolor=SURFACE,
            border=ft.Border.all(1, BORDER),
            border_radius=16,
        )

    def _confirm_action(
        self, reservation: Reservation, *, action: str, title: str
    ) -> None:
        async def execute(_=None) -> None:
            self.page.pop_dialog()
            try:
                if action == "cancel":
                    await self.on_cancel(reservation.id)
                elif action == "complete":
                    await self.on_complete(reservation.id)
                else:
                    await self.on_delete(reservation.id)
            except (FirebaseRestError, ValueError) as exc:
                self.on_message(str(exc))

        self.page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text(title),
                content=ft.Text(
                    "Esta ação não pode ser desfeita."
                    if action != "delete"
                    else "Somente reservas canceladas ou vendidas podem ser apagadas."
                ),
                actions=[
                    ft.TextButton(
                        "Voltar",
                        on_click=lambda _: self.page.pop_dialog(),
                    ),
                    ft.TextButton(
                        "Confirmar",
                        on_click=execute,
                    ),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
        )

    async def _filter_changed(self, event: ft.Event[ft.Dropdown]) -> None:
        value = event.control.value or ""
        await self.on_filter(value or None)

    @staticmethod
    def _currency(value) -> str:
        return f"R$ {value:.2f}".replace(".", ",")

    @staticmethod
    def _datetime(value) -> str:
        if value is None:
            return "—"
        return value.astimezone(LOCAL_TIMEZONE).strftime("%d/%m/%Y %H:%M")

    @staticmethod
    def _pickup_time(reservation: Reservation) -> str:
        arrival = reservation.pickup_arrival_at
        departure = reservation.pickup_departure_at
        if arrival is None or departure is None:
            return "Horário de retirada indisponível"
        return (
            f"Retirada: {arrival.astimezone(LOCAL_TIMEZONE):%d/%m/%Y %H:%M} "
            f"às {departure.astimezone(LOCAL_TIMEZONE):%d/%m/%Y %H:%M}"
        )
