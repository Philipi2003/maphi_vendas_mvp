from dataclasses import dataclass


@dataclass(frozen=True)
class Cake:
    id: str
    name: str
    description: str
    stock: int
    color: str


SAMPLE_CAKES = [
    Cake(
        "brigadeiro",
        "Brigadeiro",
        "Massa fofinha de chocolate com cobertura cremosa.",
        6,
        "#F0E2D6",
    ),
    Cake(
        "cenoura",
        "Cenoura com chocolate",
        "Bolo de cenoura caseiro com uma generosa camada de chocolate.",
        3,
        "#F4E9D5",
    ),
    Cake(
        "ninho",
        "Ninho com morango",
        "Creme suave de leite em pó com morangos fresquinhos.",
        0,
        "#F3E4E6",
    ),
    Cake(
        "limao",
        "Limão",
        "Leve, cítrico e coberto com um delicado merengue.",
        0,
        "#E9EEDC",
    ),
    Cake(
        "churros",
        "Churros",
        "Canela e doce de leite em uma combinação irresistível.",
        4,
        "#F2E6D5",
    ),
    Cake(
        "red-velvet",
        "Red velvet",
        "Massa aveludada com recheio cremoso de cream cheese.",
        2,
        "#F1E1DD",
    ),
]


class CatalogController:
    def __init__(self, cakes: list[Cake] | None = None):
        self.cakes = list(cakes if cakes is not None else SAMPLE_CAKES)
        self.quantities = {cake.id: 0 for cake in self.cakes}
        self.active_filter = "Todos"
        self.search_query = ""

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
