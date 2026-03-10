"""
Standalone app for developing the Select Datasets page in isolation.

Run with:
    shiny run tfbpshiny/modules/select_datasets/page_test.py

"""

from __future__ import annotations

from typing import Any

from shiny import App, reactive, ui

from tfbpshiny.modules.select_datasets.server import (
    selection_matrix_server,
    selection_sidebar_server,
)
from tfbpshiny.modules.select_datasets.ui import (
    selection_matrix_ui,
    selection_sidebar_ui,
)

# #MOCK datasets
_DATASETS: list[dict[str, Any]] = [
    {
        "id": "mock::harbison",
        "db_name": "harbison",
        "name": "2004 Harbison ChIP-chip",
        "type": "Binding",
        "group": "binding",
        "type_badge": "BD",
        "sample_count": 203,
        "sample_count_known": True,
        "column_count": 5,
        "tf_count": 203,
        "tf_count_known": True,
        "selected": True,
        "selectable": True,
        "metadata_configs": [],
    },
    {
        "id": "mock::kemmeren",
        "db_name": "kemmeren",
        "name": "2014 Kemmeren TFKO",
        "type": "Perturbation",
        "group": "perturbation",
        "type_badge": "PR",
        "sample_count": 1484,
        "sample_count_known": True,
        "column_count": 6,
        "tf_count": 1484,
        "tf_count_known": True,
        "selected": True,
        "selectable": True,
        "metadata_configs": [],
    },
    {
        "id": "mock::hackett",
        "db_name": "hackett",
        "name": "2020 Hackett OE",
        "type": "Perturbation",
        "group": "perturbation",
        "type_badge": "PR",
        "sample_count": 93,
        "sample_count_known": True,
        "column_count": 4,
        "tf_count": 93,
        "tf_count_known": True,
        "selected": False,
        "selectable": True,
        "metadata_configs": [],
    },
]

app_ui = ui.page_fillable(
    ui.div(
        {"class": "app-body", "style": "display:flex; height:100vh;"},
        selection_sidebar_ui("sel_sidebar"),
        selection_matrix_ui("sel_matrix"),
    ),
    padding=0,
    gap=0,
)


def server(input: Any, output: Any, session: Any) -> None:
    datasets: reactive.Value[list[dict[str, Any]]] = reactive.value(list(_DATASETS))
    intersection_cells: reactive.Value[list[dict[str, Any]]] = reactive.value([])
    has_loaded_intersection: reactive.Value[bool] = reactive.value(False)

    selection_sidebar_server(
        "sel_sidebar",
        datasets=datasets,
        logic_mode=reactive.value("intersect"),
        datasets_loading=reactive.value(False),
        intersection_loading=reactive.value(False),
        intersection_cells=intersection_cells,
        has_loaded_intersection=has_loaded_intersection,
        on_configure=lambda ds_id: None,
        on_clear_all_filters=lambda: None,
    )

    selection_matrix_server(
        "sel_matrix",
        datasets=datasets,
        logic_mode=reactive.value("intersect"),
        intersection_cells=intersection_cells,
        has_loaded_intersection=has_loaded_intersection,
        intersection_loading=reactive.value(False),
        intersection_error=reactive.value(None),
    )


app = App(ui=app_ui, server=server)
