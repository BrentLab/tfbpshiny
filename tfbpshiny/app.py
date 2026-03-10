"""TF Binding and Perturbation – Shiny app shell and module orchestration."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Literal, cast

from dotenv import load_dotenv
from shiny import App, reactive, render, ui

from configure_logger import configure_logger
from tfbpshiny.modals import (
    render_dataset_config_modal,
    render_intersection_detail_modal,
    resolve_analysis_module,
)
from tfbpshiny.modules.binding.server import (
    analysis_sidebar_server,
    analysis_workspace_server,
)
from tfbpshiny.modules.binding.ui import (
    analysis_sidebar_ui,
    analysis_workspace_ui,
)
from tfbpshiny.modules.select_datasets.server import (
    selection_matrix_server,
    selection_sidebar_server,
)
from tfbpshiny.modules.select_datasets.ui import (
    selection_matrix_ui,
    selection_sidebar_ui,
)
from tfbpshiny.splash import splash_ui

# ---------------------------------------------------------------------------
# Environment / logging
# ---------------------------------------------------------------------------

if not os.getenv("DOCKER_ENV"):
    load_dotenv(dotenv_path=Path(".env"))

logger = logging.getLogger("shiny")

log_file = f"tfbpshiny_{time.strftime('%Y%m%d-%H%M%S')}.log"
log_level = int(os.getenv("TFBPSHINY_LOG_LEVEL", "10"))
handler_type = cast(
    Literal["console", "file"], os.getenv("TFBPSHINY_LOG_HANDLER", "console")
)
configure_logger(
    "shiny",
    level=log_level,
    handler_type=handler_type,
    log_file=log_file,
)

# ---------------------------------------------------------------------------
# #MOCK — inline dataset catalog
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

app_ui = ui.page_fillable(
    ui.include_css((Path(__file__).parent / "app.css").resolve()),
    ui.div(
        {"class": "app-container"},
        ui.div(
            {"class": "nav-bar"},
            ui.div({"class": "nav-logo"}, "TF\nBinding & Perturbation\nExplorer"),
            ui.output_ui("nav_buttons"),
        ),
        ui.div(
            {"class": "app-body"},
            ui.output_ui("sidebar_region"),
            ui.output_ui("workspace_region"),
        ),
    ),
    ui.output_ui("modal_layer"),
    padding=0,
    gap=0,
)

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


def app_server(input: Any, output: Any, session: Any) -> None:
    """Create shared reactive state and call all module servers."""

    # -- Shared reactive values --
    active_module: reactive.Value[str] = reactive.value("home")
    datasets: reactive.Value[list[dict[str, Any]]] = reactive.value(
        list(_MOCK_DATASETS)
    )

    intersection_cells: reactive.Value[list[dict[str, Any]]] = reactive.value([])
    has_loaded_intersection: reactive.Value[bool] = reactive.value(False)

    active_config_dataset_id: reactive.Value[str | None] = reactive.value(None)
    intersection_detail: reactive.Value[dict[str, Any] | None] = reactive.value(None)

    # -- Helpers --
    def _dataset_by_id(dataset_id: str) -> dict[str, Any] | None:
        return next((e for e in datasets() if str(e["id"]) == dataset_id), None)

    def _set_dataset_selected(dataset_id: str, selected: bool) -> None:
        current = datasets()
        changed = False
        for entry in current:
            if str(entry["id"]) != dataset_id:
                continue
            if bool(entry.get("selected")) != bool(selected):
                entry["selected"] = bool(selected)
                changed = True
        if changed:
            datasets.set(list(current))

    def _handle_open_config(dataset_id: str) -> None:
        active_config_dataset_id.set(dataset_id)

    def _handle_refresh_intersection() -> None:
        selected = [e for e in datasets() if e.get("selected")]
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

    def _handle_matrix_cell_click(payload: dict[str, Any]) -> None:
        intersection_detail.set(payload)

    _ANALYSIS_LABELS: dict[str, str] = {
        "binding": "Binding Analysis",
        "perturbation": "Perturbation Analysis",
        "composite": "Comparison Analysis",
    }

    # -- Region renders --
    @render.ui
    def sidebar_region() -> ui.Tag:
        mod = active_module()
        if mod == "home":
            return ui.span()
        if mod == "selection":
            return selection_sidebar_ui("sel_sidebar")
        return analysis_sidebar_ui(
            "ana_sidebar", label=_ANALYSIS_LABELS.get(mod, "Analysis")
        )

    @render.ui
    def workspace_region() -> ui.Tag:
        mod = active_module()
        if mod == "home":
            return splash_ui()
        if mod == "selection":
            return selection_matrix_ui("sel_matrix")
        return analysis_workspace_ui(
            "ana_workspace", label=_ANALYSIS_LABELS.get(mod, "Analysis")
        )

    @render.ui
    def modal_layer() -> ui.Tag:
        active_dataset_id = active_config_dataset_id()
        if active_dataset_id:
            dataset = _dataset_by_id(active_dataset_id)
            if not dataset:
                return ui.span()
            return render_dataset_config_modal(dataset=dataset)

        details = intersection_detail()
        if details:
            return render_intersection_detail_modal(details)

        return ui.span()

    # -- Config modal effects --
    @reactive.effect
    def _sync_modal_include_toggle() -> None:
        dataset_id = active_config_dataset_id()
        if not dataset_id:
            return
        try:
            _set_dataset_selected(dataset_id, bool(input.modal_include_dataset()))
        except Exception:
            pass

    @reactive.effect
    @reactive.event(input.modal_close_config)
    def _close_config_modal_from_header() -> None:
        active_config_dataset_id.set(None)

    @reactive.effect
    @reactive.event(input.modal_cancel_filters)
    def _close_config_modal_from_cancel() -> None:
        active_config_dataset_id.set(None)

    @reactive.effect
    @reactive.event(input.modal_apply_filters)
    def _close_config_modal_from_apply() -> None:
        active_config_dataset_id.set(None)

    # -- Intersection modal effects --
    @reactive.effect
    @reactive.event(input.modal_close_intersection)
    def _close_intersection_modal_from_header() -> None:
        intersection_detail.set(None)

    @reactive.effect
    @reactive.event(input.modal_close_intersection_secondary)
    def _close_intersection_modal_from_footer() -> None:
        intersection_detail.set(None)

    @reactive.effect
    @reactive.event(input.modal_open_analysis)
    def _navigate_from_modal() -> None:
        details = intersection_detail()
        if not details:
            return
        row_type = str(details.get("rowDataset", {}).get("type", ""))
        col_type = str(details.get("colDataset", {}).get("type", ""))
        target = resolve_analysis_module(row_type, col_type)
        if target:
            active_module.set(target)
        intersection_detail.set(None)

    # -- Nav rail --
    _NAV_ITEMS = [
        {"id": "home", "tag": "Home"},
        {"id": "selection", "tag": "Select Datasets"},
        {"id": "binding", "tag": "Binding"},
        {"id": "perturbation", "tag": "Perturbation"},
        {"id": "composite", "tag": "Comparison"},
    ]

    @render.ui
    def nav_buttons() -> ui.Tag:
        current = active_module()
        return ui.div(
            {"class": "nav-tags"},
            *[
                ui.input_action_button(
                    item["id"],
                    item["tag"],
                    class_=f"nav-btn{' active' if item['id'] == current else ''}",
                )
                for item in _NAV_ITEMS
            ],
        )

    @reactive.effect
    @reactive.event(input.home, ignore_init=True)
    def _nav_home() -> None:
        active_module.set("home")

    @reactive.effect
    @reactive.event(input.selection, ignore_init=True)
    def _nav_selection() -> None:
        active_module.set("selection")

    @reactive.effect
    @reactive.event(input.binding, ignore_init=True)
    def _nav_binding() -> None:
        active_module.set("binding")

    @reactive.effect
    @reactive.event(input.perturbation, ignore_init=True)
    def _nav_perturbation() -> None:
        active_module.set("perturbation")

    @reactive.effect
    @reactive.event(input.composite, ignore_init=True)
    def _nav_composite() -> None:
        active_module.set("composite")

    # -- Module servers --
    selection_sidebar_server(
        "sel_sidebar",
        datasets=datasets,
        logic_mode=reactive.value("intersect"),
        datasets_loading=reactive.value(False),
        intersection_loading=reactive.value(False),
        on_configure=_handle_open_config,
        on_refresh=_handle_refresh_intersection,
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
        on_cell_click=_handle_matrix_cell_click,
    )

    analysis_sidebar_server("ana_sidebar", active_module=active_module)
    analysis_workspace_server("ana_workspace", active_module=active_module)


# ---------------------------------------------------------------------------
# App instance
# ---------------------------------------------------------------------------

app = App(ui=app_ui, server=app_server)
