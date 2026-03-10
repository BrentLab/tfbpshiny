"""Server functions for the Select Datasets page."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from typing import Any

import faicons as fa
from shiny import module, reactive, render, ui

from tfbpshiny.modal import resolve_analysis_module


@module.server
def selection_sidebar_server(
    input: Any,
    output: Any,
    session: Any,
    datasets: reactive.Value[list[dict[str, Any]]],
    logic_mode: reactive.Value[str],
    datasets_loading: reactive.Value[bool],
    intersection_loading: reactive.Value[bool],
    intersection_cells: reactive.Value[list[dict[str, Any]]],
    has_loaded_intersection: reactive.Value[bool],
    on_clear_all_filters: Callable[[], None] | None = None,
) -> reactive.Value[str | None]:
    """Wire sidebar controls; return active_config_dataset_id for modal rendering."""

    collapsed: reactive.Value[bool] = reactive.value(False)
    configure_clicks: reactive.Value[dict[str, int]] = reactive.value({})
    active_config_dataset_id: reactive.Value[str | None] = reactive.value(None)

    def _dataset_input_id(prefix: str, ds_id: Any) -> str:
        raw = str(ds_id)
        safe = re.sub(r"[^0-9A-Za-z_]", "_", raw).strip("_") or "dataset"
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
        return f"{prefix}_{safe}_{digest}"

    def _selected_summary() -> dict[str, int]:
        selected = [dataset for dataset in datasets() if dataset.get("selected")]
        return {"selected_count": len(selected)}

    @reactive.effect
    @reactive.event(input.toggle_sidebar)
    def _toggle_sidebar() -> None:
        collapsed.set(not collapsed())

    @reactive.effect
    def _sync_dataset_toggles() -> None:
        current = datasets()
        changed = False

        for dataset in current:
            toggle_id = _dataset_input_id("ds_toggle", dataset["id"])
            try:
                value = bool(input[toggle_id]())
            except Exception:
                continue
            if bool(dataset.get("selected")) != value:
                dataset["selected"] = value
                changed = True

        if changed:
            datasets.set(list(current))

    @reactive.effect
    def _watch_configure_buttons() -> None:
        current_counts = dict(configure_clicks())

        for dataset in datasets():
            configure_id = _dataset_input_id("configure", dataset["id"])
            try:
                clicks = int(input[configure_id]())
            except Exception:
                continue

            previous = int(current_counts.get(str(dataset["id"]), 0))
            if clicks > previous:
                current_counts[str(dataset["id"])] = clicks
                configure_clicks.set(current_counts)
                active_config_dataset_id.set(str(dataset["id"]))
                break

    @reactive.effect
    @reactive.event(input.refresh)
    def _refresh_matrix() -> None:
        selected = [e for e in datasets() if e.get("selected")]
        if not selected or datasets_loading() or intersection_loading():
            return
        # #MOCK — diagonal + pairwise counts derived from tf_count
        cells: list[dict[str, Any]] = [
            {
                "row": a["db_name"],
                "col": b["db_name"],
                "count": (
                    a["tf_count"]
                    if a["db_name"] == b["db_name"]
                    else min(a["tf_count"], b["tf_count"]) // 2
                ),
            }
            for a in selected
            for b in selected
        ]
        intersection_cells.set(cells)
        has_loaded_intersection.set(True)

    @render.ui
    def sidebar_panel() -> ui.Tag:
        is_collapsed = collapsed()
        search_raw = ""
        if not is_collapsed:
            # `search` is dynamically mounted; guard against transient missing input.
            try:
                search_raw = input.search() or ""
            except Exception:
                search_raw = ""
        search_term = search_raw.strip().lower()

        all_datasets = datasets()
        summary = _selected_summary()

        visible = (
            [
                dataset
                for dataset in all_datasets
                if search_term in str(dataset.get("name", "")).lower()
            ]
            if search_term
            else list(all_datasets)
        )

        binding = [dataset for dataset in visible if dataset.get("group") == "binding"]
        perturbation_or_other = [
            dataset for dataset in visible if dataset.get("group") != "binding"
        ]

        def _dataset_row(dataset: dict[str, Any]) -> ui.Tag:
            dataset_id = str(dataset["id"])
            toggle_id = _dataset_input_id("ds_toggle", dataset_id)
            configure_id = _dataset_input_id("configure", dataset_id)
            badge = str(dataset.get("type_badge") or "EX")
            badge_cls = f"badge badge-{badge.lower()}"

            sample_count = int(dataset.get("sample_count") or 0)
            column_count = int(dataset.get("column_count") or 0)
            sample_known = bool(dataset.get("sample_count_known"))
            summary_text = (
                f"{sample_count:,} rows · {column_count:,} cols"
                if sample_known
                else f"rows pending · {column_count:,} cols"
            )

            return ui.div(
                {
                    "class": "dataset-item" + (" compact" if is_collapsed else ""),
                    "title": str(dataset.get("name", "Dataset")),
                },
                ui.input_switch(
                    toggle_id,
                    label=None,
                    value=bool(dataset.get("selected")),
                ),
                ui.span({"class": badge_cls}, badge),
                (
                    ui.div(
                        {"class": "dataset-text"},
                        ui.span(
                            {"class": "dataset-name"},
                            str(dataset.get("name", "Dataset")),
                        ),
                        ui.span({"class": "dataset-meta"}, summary_text),
                    )
                    if not is_collapsed
                    else ui.span()
                ),
                (
                    ui.input_action_button(
                        configure_id,
                        "Filter",
                        class_="btn-configure",
                    )
                    if not is_collapsed
                    else ui.span()
                ),
            )

        section_tags: list[ui.Tag] = []
        if binding:
            if not is_collapsed:
                section_tags.append(ui.div({"class": "group-header"}, "Binding"))
                section_tags.append(
                    ui.div(
                        {"class": "group-description"},
                        "Datasets measuring TF-DNA interactions",
                    )
                )
            section_tags.extend(_dataset_row(dataset) for dataset in binding)
        if perturbation_or_other:
            if not is_collapsed:
                section_tags.append(
                    ui.div({"class": "group-header"}, "Perturbation / Other")
                )
                section_tags.append(
                    ui.div(
                        {"class": "group-description"},
                        "Datasets measuring gene expression changes"
                        " after TF perturbation",
                    )
                )
            section_tags.extend(
                _dataset_row(dataset) for dataset in perturbation_or_other
            )

        if not section_tags:
            section_tags.append(
                ui.div(
                    {"class": "empty-state compact"},
                    ui.p("No datasets match your search."),
                )
            )

        refresh_loading = bool(datasets_loading() or intersection_loading())
        refresh_label = "Refreshing..." if refresh_loading else "Refresh Matrix"

        return ui.div(
            {
                "class": "context-sidebar selection-sidebar"
                + (" collapsed" if is_collapsed else ""),
                "id": "selection-sidebar",
            },
            ui.div(
                {"class": "sidebar-header"},
                ui.div(
                    {"class": "sidebar-header-row"},
                    (
                        ui.div(
                            ui.h2("Select Datasets"),
                            ui.div({"class": "subtitle"}, "Select datasets to compare"),
                        )
                        if not is_collapsed
                        else ui.div(ui.h2("SD"))
                    ),
                    ui.input_action_button(
                        "toggle_sidebar",
                        (
                            fa.icon_svg("angles-left", width="14px", height="14px")
                            if not is_collapsed
                            else fa.icon_svg(
                                "angles-right", width="14px", height="14px"
                            )
                        ),
                        class_="btn-collapse-sidebar",
                    ),
                ),
                (
                    ui.input_text(
                        "search",
                        label=None,
                        placeholder="Search datasets...",
                        width="100%",
                    )
                    if not is_collapsed
                    else ui.span()
                ),
            ),
            ui.div(
                {"class": "sidebar-body"},
                ui.div({"class": "dataset-list"}, *section_tags),
            ),
            ui.div(
                {"class": "sidebar-footer"},
                ui.input_action_button(
                    "refresh",
                    ui.span(
                        fa.icon_svg("arrows-rotate", width="14px", height="14px"),
                        ("" if is_collapsed else f" {refresh_label}"),
                    ),
                    class_=(
                        "btn btn-sm btn-primary w-100 refresh-btn"
                        + (" is-loading" if refresh_loading else "")
                        + (
                            " is-disabled"
                            if summary["selected_count"] <= 0 or refresh_loading
                            else ""
                        )
                    ),
                ),
            ),
        )

    return active_config_dataset_id


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

    def _cell_key(row_db: str, col_db: str) -> str:
        return f"{row_db}::{col_db}"

    def _cell_button_id(row_id: str, col_id: str) -> str:
        raw = f"{row_id}::{col_id}"
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
        return f"matrix_cell_{digest}"

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
    datasets: reactive.Value[list[dict[str, Any]]],
) -> tuple[
    reactive.Value[str | None],
    reactive.Value[dict[str, Any] | None],
    reactive.Value[str | None],
]:
    """Wire both select_datasets module servers; return (active_config_dataset_id,
    intersection_detail, navigate_to)."""
    intersection_cells: reactive.Value[list[dict[str, Any]]] = reactive.value([])
    has_loaded_intersection: reactive.Value[bool] = reactive.value(False)

    active_config_dataset_id = selection_sidebar_server(
        "sel_sidebar",
        datasets=datasets,
        logic_mode=reactive.value("intersect"),
        datasets_loading=reactive.value(False),
        intersection_loading=reactive.value(False),
        intersection_cells=intersection_cells,
        has_loaded_intersection=has_loaded_intersection,
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
    return active_config_dataset_id, intersection_detail, navigate_to


__all__ = [
    "select_datasets_server",
    "selection_sidebar_server",
    "selection_matrix_server",
]
