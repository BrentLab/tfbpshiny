"""Workspace server for the Select Datasets page."""

from __future__ import annotations

import hashlib
from logging import Logger
from typing import Any

from shiny import module, reactive, render, ui
from tfbpapi import VirtualDB

from tfbpshiny.modal import resolve_analysis_module
from tfbpshiny.modules.select_datasets.server.sidebar import selection_sidebar_server

# #MOCK — inline dataset catalog (temporary; will come from VirtualDB)
_MOCK_DATASETS: list[dict[str, Any]] = [
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


def _cell_key(row_db: str, col_db: str) -> str:
    return f"{row_db}::{col_db}"


def _cell_button_id(row_id: str, col_id: str) -> str:
    raw = f"{row_id}::{col_id}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    return f"matrix_cell_{digest}"


@module.server
def selection_matrix_server(
    input: Any,
    output: Any,
    session: Any,
    datasets: reactive.Value[list[dict[str, Any]]],
    logic_mode: reactive.Value[str],
    intersection_cells: reactive.Value[list[dict[str, Any]]],
    has_loaded_intersection: reactive.Value[bool],
    intersection_loading: reactive.Value[bool],
    intersection_error: reactive.Value[str | None],
) -> tuple[reactive.Value[dict[str, Any] | None], reactive.Value[str | None]]:
    """Render matrix; return (intersection_detail, navigate_to) reactives."""

    intersection_detail: reactive.Value[dict[str, Any] | None] = reactive.value(None)
    navigate_to: reactive.Value[str | None] = reactive.value(None)
    cell_click_counts: reactive.Value[dict[str, int]] = reactive.value({})

    @reactive.calc
    def _active_datasets() -> list[dict[str, Any]]:
        return [entry for entry in datasets() if entry.get("selected")]

    @reactive.calc
    def _cell_map() -> dict[str, int | None]:
        cells = intersection_cells()
        mapping: dict[str, int | None] = {}

        for cell in cells:
            row = str(cell.get("row"))
            col = str(cell.get("col"))
            count = cell.get("count")
            normalized_count = int(count) if isinstance(count, (int, float)) else None
            mapping[_cell_key(row, col)] = normalized_count
            mapping[_cell_key(col, row)] = normalized_count

        return mapping

    @reactive.calc
    def _diagonal_tf_map() -> dict[str, int]:
        diagonal: dict[str, int] = {}
        for cell in intersection_cells():
            row = str(cell.get("row"))
            col = str(cell.get("col"))
            count = cell.get("count")
            if row == col and isinstance(count, (int, float)):
                diagonal[row] = int(count)
        return diagonal

    @reactive.calc
    def _max_off_diagonal() -> int:
        active = _active_datasets()
        cell_map = _cell_map()

        values: list[int] = []
        for i, row_dataset in enumerate(active):
            row_db = str(row_dataset.get("db_name"))
            for j, col_dataset in enumerate(active):
                if j <= i:
                    continue
                col_db = str(col_dataset.get("db_name"))
                value = cell_map.get(_cell_key(row_db, col_db))
                if isinstance(value, int):
                    values.append(value)

        return max(values) if values else 1

    @reactive.effect
    def _watch_cell_clicks() -> None:
        active = _active_datasets()
        cell_map = _cell_map()
        current_counts = dict(cell_click_counts())

        for row_index, row_dataset in enumerate(active):
            row_id = str(row_dataset.get("id"))
            row_db = str(row_dataset.get("db_name"))

            for col_index, col_dataset in enumerate(active):
                if col_index <= row_index:
                    continue

                col_id = str(col_dataset.get("id"))
                col_db = str(col_dataset.get("db_name"))
                value = cell_map.get(_cell_key(row_db, col_db))
                if value is None:
                    continue

                button_id = _cell_button_id(row_id, col_id)
                try:
                    clicks = int(input[button_id]())
                except Exception:
                    continue

                prev_clicks = int(current_counts.get(button_id, 0))
                if clicks > prev_clicks:
                    current_counts[button_id] = clicks
                    cell_click_counts.set(current_counts)

                    row_type = row_dataset.get("type", "Expression")
                    col_type = col_dataset.get("type", "Expression")
                    intersection_detail.set(
                        {
                            "rowDataset": {
                                "id": row_id,
                                "db_name": row_db,
                                "type": row_type,
                                "name": row_dataset.get("name", row_db),
                                "tf_count": int(row_dataset.get("tf_count") or 0),
                            },
                            "colDataset": {
                                "id": col_id,
                                "db_name": col_db,
                                "type": col_type,
                                "name": col_dataset.get("name", col_db),
                                "tf_count": int(col_dataset.get("tf_count") or 0),
                            },
                            "intersectionCount": int(value),
                        }
                    )
                    navigate_to.set(
                        resolve_analysis_module(str(row_type), str(col_type))
                    )
                    return

    @render.ui
    def matrix_content() -> ui.Tag:
        active = _active_datasets()

        if intersection_loading() and not has_loaded_intersection():
            return ui.div(
                {"class": "empty-state"},
                ui.h3("Downloading selected datasets..."),
            )

        if not active:
            return ui.div(
                {"class": "empty-state"},
                ui.h3("No datasets selected"),
                ui.p("Select datasets from the sidebar to view intersections."),
            )

        if intersection_error():
            return ui.div(
                {"class": "empty-state"},
                ui.h3("Failed to load selection data"),
                ui.p(str(intersection_error())),
            )

        if not has_loaded_intersection():
            return ui.div(
                {"class": "empty-state"},
                ui.h3("Dataset metadata is ready"),
                ui.p(
                    "Click Refresh Matrix to preload files and compute intersections."
                ),
            )

        cell_map = _cell_map()
        diagonal_tf_map = _diagonal_tf_map()
        max_value = _max_off_diagonal()

        def _bucket(value: int | None) -> int:
            if value is None:
                return 0
            if max_value <= 0:
                return 1
            scaled = int((value / max_value) * 5)
            return max(1, min(5, scaled))

        header_cells = [
            ui.tags.th(
                {"class": "matrix-row-header"},
                "Dataset Pair",
            )
        ]

        for dataset in active:
            db_name = str(dataset.get("db_name"))
            tf_count = int(diagonal_tf_map.get(db_name, 0))
            header_cells.append(
                ui.tags.th(
                    {"class": "matrix-col-header"},
                    ui.div(
                        {"class": "matrix-header-name"},
                        str(dataset.get("name", db_name)),
                    ),
                    ui.div({"class": "matrix-header-meta"}, f"{tf_count:,} TFs"),
                )
            )

        body_rows: list[ui.Tag] = []
        for row_index, row_dataset in enumerate(active):
            row_name = str(row_dataset.get("name", "Dataset"))
            row_db = str(row_dataset.get("db_name"))
            row_id = str(row_dataset.get("id"))

            cells: list[ui.Tag] = [
                ui.tags.td(
                    {"class": "matrix-row-label"},
                    row_name,
                )
            ]

            for col_index, col_dataset in enumerate(active):
                col_db = str(col_dataset.get("db_name"))
                col_id = str(col_dataset.get("id"))

                if col_index < row_index:
                    cells.append(ui.tags.td({"class": "matrix-cell-empty"}, ""))
                    continue

                value = cell_map.get(_cell_key(row_db, col_db))
                is_diagonal = row_index == col_index

                if is_diagonal:
                    cells.append(
                        ui.tags.td(
                            {"class": "matrix-cell-diagonal"},
                            ("N/A" if value is None else f"{value:,}"),
                        )
                    )
                    continue

                if value is None:
                    cells.append(
                        ui.tags.td(
                            {"class": "matrix-cell-na"},
                            "N/A",
                        )
                    )
                    continue

                button_id = _cell_button_id(row_id, col_id)
                cells.append(
                    ui.tags.td(
                        {"class": "matrix-cell-interactive"},
                        ui.input_action_button(
                            button_id,
                            f"{value:,}",
                            class_=(
                                "matrix-cell-button"
                                f" matrix-intensity-{_bucket(value)}"
                            ),
                        ),
                    )
                )

            body_rows.append(ui.tags.tr(*cells))

        refresh_badge = (
            ui.div({"class": "matrix-refreshing-badge"}, "Refreshing...")
            if intersection_loading() and has_loaded_intersection()
            else ui.span()
        )

        return ui.div(
            {"class": "card intersection-summary-card"},
            ui.div(
                {"class": "intersection-summary-header"},
                ui.div(
                    ui.h2("Intersection Summary"),
                    ui.div(
                        {"class": "intersection-summary-subtitle"},
                        f"{len(active)} datasets · "
                        f"{'AND' if logic_mode() == 'intersect' else 'OR'} mode",
                    ),
                ),
                refresh_badge,
            ),
            ui.div(
                {"class": "matrix-table-wrap"},
                ui.tags.table(
                    {"class": "matrix-table matrix-summary-table"},
                    ui.tags.thead(ui.tags.tr(*header_cells)),
                    ui.tags.tbody(*body_rows),
                ),
            ),
        )

    return intersection_detail, navigate_to


def select_datasets_server(
    vdb: VirtualDB,
    logger: Logger,
) -> tuple[
    reactive.Value[str | None],
    reactive.Value[dict[str, Any] | None],
    reactive.Value[str | None],
]:
    """Wire both select_datasets module servers; return (active_config_dataset_id,
    intersection_detail, navigate_to)."""
    datasets: reactive.Value[list[dict[str, Any]]] = reactive.value(
        list(_MOCK_DATASETS)
    )
    intersection_cells: reactive.Value[list[dict[str, Any]]] = reactive.value([])
    has_loaded_intersection: reactive.Value[bool] = reactive.value(False)

    filter_modal_open_for, active_binding_datasets, active_perturbation_datasets = (
        selection_sidebar_server("sel_sidebar", vdb=vdb, logger=logger)
    )
    intersection_detail, navigate_to = selection_matrix_server(
        "sel_matrix",
        datasets=datasets,
        logic_mode=reactive.value("intersect"),
        intersection_cells=intersection_cells,
        has_loaded_intersection=has_loaded_intersection,
        intersection_loading=reactive.value(False),
        intersection_error=reactive.value(None),
    )
    return filter_modal_open_for, intersection_detail, navigate_to


__all__ = ["select_datasets_server", "selection_matrix_server"]
