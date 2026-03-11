"""TF Binding and Perturbation – Shiny app shell and module orchestration."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Literal, cast

from dotenv import load_dotenv
from shiny import App, reactive, render, ui
from tfbpapi import VirtualDB

from configure_logger import configure_logger
from tfbpshiny.modal import render_intersection_detail_modal
from tfbpshiny.modules.binding.server import (
    binding_sidebar_server,
    binding_workspace_server,
)
from tfbpshiny.modules.binding.ui import binding_sidebar_ui, binding_workspace_ui
from tfbpshiny.modules.comparison.server import (
    comparison_sidebar_server,
    comparison_workspace_server,
)
from tfbpshiny.modules.comparison.ui import (
    comparison_sidebar_ui,
    comparison_workspace_ui,
)
from tfbpshiny.modules.perturbation.server import (
    perturbation_sidebar_server,
    perturbation_workspace_server,
)
from tfbpshiny.modules.perturbation.ui import (
    perturbation_sidebar_ui,
    perturbation_workspace_ui,
)
from tfbpshiny.modules.select_datasets.server import select_datasets_server
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
# VirtualDB instantiation
# ---------------------------------------------------------------------------
virtualdb_config = Path(__file__).parent / "brentlab_yeast_collection.yaml"
logger.info(f"Loading VirtualDB with config: {virtualdb_config.resolve()}")
vdb = VirtualDB(virtualdb_config.resolve())

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
            ui.div(
                {"class": "nav-tags"},
                ui.input_action_button("home", "Home", class_="nav-btn"),
                ui.input_action_button(
                    "selection", "Select Datasets", class_="nav-btn"
                ),
                ui.input_action_button("binding", "Binding", class_="nav-btn"),
                ui.input_action_button(
                    "perturbation", "Perturbation", class_="nav-btn"
                ),
                ui.input_action_button("comparison", "Comparison", class_="nav-btn"),
            ),
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

    (active_config_dataset_id, intersection_detail, navigate_to) = (
        select_datasets_server(vdb, logger)
    )

    # -- Region renders --
    @render.ui
    def sidebar_region() -> ui.Tag:
        selected_module = active_module()
        logger.debug(f"Rendering sidebar for active module: {selected_module}")
        if selected_module == "home":
            # no sidebar for home module
            return ui.span()
        if selected_module == "selection":
            return selection_sidebar_ui("sel_sidebar")
        if selected_module == "binding":
            return binding_sidebar_ui("module_sidebar")
        if selected_module == "perturbation":
            return perturbation_sidebar_ui("module_sidebar")
        if selected_module == "comparison":
            return comparison_sidebar_ui("module_sidebar")
        logger.error(f"No sidebar for active module: {selected_module}")
        return ui.span(ui.p("ERROR: No sidebar for: " + selected_module))

    @render.ui
    def workspace_region() -> ui.Tag:
        selected_module = active_module()
        logger.debug(f"Rendering workspace for active module: {selected_module}")
        if selected_module == "home":
            return splash_ui()
        if selected_module == "selection":
            return selection_matrix_ui("sel_matrix")
        if selected_module == "binding":
            return binding_workspace_ui("module_workspace")
        if selected_module == "perturbation":
            return perturbation_workspace_ui("module_workspace")
        if selected_module == "comparison":
            return comparison_workspace_ui("module_workspace")
        logger.error(f"No workspace for active module: {selected_module}")
        return ui.span(ui.p("ERROR: No workspace for: " + selected_module))

    @render.ui
    def modal_layer() -> ui.Tag:
        # #TODO: active_config_dataset_id will trigger
        # when sidebar configure is wired up
        details = intersection_detail()
        if details:
            return render_intersection_detail_modal(details)
        return ui.span()

    # -- Config modal effects --
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
        target = navigate_to()
        if target:
            active_module.set(target)
        intersection_detail.set(None)
        navigate_to.set(None)

    # -- Nav --
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
    @reactive.event(input.comparison, ignore_init=True)
    def _nav_comparison() -> None:
        active_module.set("comparison")

    # -- Module servers --
    binding_sidebar_server("module_sidebar", active_module=active_module)
    binding_workspace_server("module_workspace", active_module=active_module)
    perturbation_sidebar_server("module_sidebar", active_module=active_module)
    perturbation_workspace_server("module_workspace", active_module=active_module)
    comparison_sidebar_server("module_sidebar", active_module=active_module)
    comparison_workspace_server("module_workspace", active_module=active_module)


# ---------------------------------------------------------------------------
# App instance
# ---------------------------------------------------------------------------

app = App(ui=app_ui, server=app_server)
