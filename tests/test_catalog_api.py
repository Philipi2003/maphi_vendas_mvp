import pytest

from features.catalog.catalog_api import CatalogApiError, parse_catalog_response
from features.catalog.catalog_logic import Cake, CatalogController


def test_parse_catalog_response_maps_database_fields():
    cakes = parse_catalog_response(
        {
            "items": [
                {
                    "id": "cake-1",
                    "name": "  Brigadeiro ",
                    "description": None,
                    "image_url": " https://example.com/cake.jpg ",
                    "stock": 2,
                }
            ]
        }
    )

    assert cakes == [
        Cake(
            id="cake-1",
            name="Brigadeiro",
            description="",
            stock=2,
            color="#F0E2D6",
            image_url="https://example.com/cake.jpg",
        )
    ]


@pytest.mark.parametrize("stock", [True, -1, "2"])
def test_parse_catalog_response_rejects_invalid_stock(stock):
    with pytest.raises(CatalogApiError):
        parse_catalog_response(
            {
                "items": [
                    {
                        "id": "cake-1",
                        "name": "Brigadeiro",
                        "description": "",
                        "image_url": None,
                        "stock": stock,
                    }
                ]
            }
        )


def test_controller_replaces_cakes_and_clamps_existing_selection():
    controller = CatalogController(
        [Cake("cake-1", "Brigadeiro", "", 4, "#F0E2D6")]
    )
    controller.change_quantity("cake-1", 3)

    controller.set_cakes([Cake("cake-1", "Brigadeiro", "", 2, "#F0E2D6")])

    assert controller.quantities == {"cake-1": 2}
    assert controller.selected_count == 2
