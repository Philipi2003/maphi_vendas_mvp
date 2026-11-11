import flet as ft

from application import create_application


def main(page: ft.Page) -> None:
    create_application(page)


if __name__ == "__main__":
    ft.run(main)
