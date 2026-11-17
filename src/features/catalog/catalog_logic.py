from dataclasses import dataclass


@dataclass(frozen=True)
class Cake:
    id: str
    name: str
    description: str
    stock: int
    color: str
    image_url: str | None = None


class CatalogController:
    def __init__(self, cakes: list[Cake] | None = None):
        self.cakes = list(cakes if cakes is not None else [])
        self.quantities = {cake.id: 0 for cake in self.cakes}
        self.active_filter = "Todos"
        self.search_query = ""

    def set_cakes(self, cakes: list[Cake]) -> None:
        previous_quantities = self.quantities
        self.cakes = list(cakes)
        self.quantities = {
            cake.id: min(cake.stock, previous_quantities.get(cake.id, 0))
            for cake in self.cakes
        }

    @property
    def selected_count(self) -> int:
        return sum(self.quantities.values())

    @property
    def filtered_cakes(self) -> list[Cake]:
        query = self.search_query.casefold()
        return [
            cake
            for cake in self.cakes
            if (
                self.active_filter == "Todos"
                or (self.active_filter == "Disponíveis" and cake.stock > 0)
                or (self.active_filter == "Esgotados" and cake.stock == 0)
            )
            and query in cake.name.casefold()
        ]

    def set_filter(self, value: str) -> None:
        self.active_filter = value

    def set_search_query(self, value: str) -> None:
        self.search_query = value.strip()

    def change_quantity(self, cake_id: str, amount: int) -> None:
        cake = next(cake for cake in self.cakes if cake.id == cake_id)
        self.quantities[cake_id] = max(
            0, min(cake.stock, self.quantities[cake_id] + amount)
        )
