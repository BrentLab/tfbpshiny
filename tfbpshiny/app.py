from __future__ import annotations

import logging
import os
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Literal, cast

from dotenv import load_dotenv
from shiny import App, reactive, render, ui
from tfbpapi import VirtualDB

from configure_logger import configure_logger
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
from tfbpshiny.modules.home.ui import home_ui
from tfbpshiny.modules.perturbation.server import (
    perturbation_sidebar_server,
    perturbation_workspace_server,
)
from tfbpshiny.modules.perturbation.ui import (
    perturbation_sidebar_ui,
    perturbation_workspace_ui,
)
from tfbpshiny.modules.select_datasets.server import (
    select_datasets_sidebar_server,
    select_datasets_workspace_server,
)
from tfbpshiny.modules.select_datasets.ui import (
    selection_matrix_ui,
    selection_sidebar_ui,
)

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

# instantiate the virtualDB
virtualdb_config = Path(__file__).parent / "brentlab_yeast_collection.yaml"
logger.info(f"Loading VirtualDB with config: {virtualdb_config.resolve()}")
vdb = VirtualDB(virtualdb_config.resolve())

# this is for the github badge in the navbar. it links to the repo and displays
# the current version
try:
    _version = version("tfbpshiny")
except PackageNotFoundError:
    _version = "dev"

_GITHUB_URL = "https://github.com/BrentLab/tfbpshiny"


def github_badge() -> ui.Tag:
    """GitHub repo link with version pill, suitable for the navbar."""
    return ui.a(
        {"class": "github-badge", "href": _GITHUB_URL, "target": "_blank"},
        ui.tags.svg(
            {
                "xmlns": "http://www.w3.org/2000/svg",
                "width": "16",
                "height": "16",
                "viewBox": "0 0 16 16",
                "fill": "currentColor",
                "style": "vertical-align:middle; margin-right:5px;",
            },
            ui.Tag(
                "path",
                # this is the SVG path data for the GitHub logo
                # see https://simpleicons.org/icons/github.svg
                d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 "
                "7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-"
                "2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 "
                "1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-"
                "1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-"
                "1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 "
                "1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56"
                ".82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 "
                "0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 "
                "8c0-4.42-3.58-8-8-8z",
            ),
        ),
        ui.tags.span(
            {"style": "vertical-align:middle; margin-right:6px;"},
            "BrentLab/tfbpshiny",
        ),
        ui.tags.span(
            {"class": "github-badge-version"},
            f"v{_version}",
        ),
    )


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
            github_badge(),
        ),
        ui.div(
            {"class": "app-body"},
            ui.output_ui("sidebar_region"),
            ui.output_ui("workspace_region"),
        ),
    ),
    padding=0,
    gap=0,
)


def app_server(input: Any, output: Any, session: Any) -> None:
    """Create shared reactive state and call all module servers."""

    # this stores the name of the currently active module, ie
    # "home", "selection", "binding", "perturbation", or "comparison"
    active_module: reactive.Value[str] = reactive.value("home")

    # Dataset selection state — shared across all analysis modules
    active_binding_datasets, active_perturbation_datasets, dataset_filters = (
        select_datasets_sidebar_server(
            "select_datasets_sidebar", vdb=vdb, logger=logger
        )
    )
    select_datasets_workspace_server(
        "select_datasets_workspace",
        active_binding_datasets=active_binding_datasets,
        active_perturbation_datasets=active_perturbation_datasets,
        dataset_filters=dataset_filters,
        vdb=vdb,
        logger=logger,
    )

    corr_type, col_preference = binding_sidebar_server(
        "binding_sidebar",
        active_binding_datasets=active_binding_datasets,
        dataset_filters=dataset_filters,
        vdb=vdb,
        logger=logger,
    )
    binding_workspace_server(
        "binding_workspace",
        active_binding_datasets=active_binding_datasets,
        corr_type=corr_type,
        col_preference=col_preference,
        dataset_filters=dataset_filters,
        vdb=vdb,
        logger=logger,
    )

    corr_type_p, col_preference_p = perturbation_sidebar_server(
        "perturbation_sidebar",
        active_perturbation_datasets=active_perturbation_datasets,
        dataset_filters=dataset_filters,
        vdb=vdb,
        logger=logger,
    )
    perturbation_workspace_server(
        "perturbation_workspace",
        active_perturbation_datasets=active_perturbation_datasets,
        corr_type=corr_type_p,
        col_preference=col_preference_p,
        dataset_filters=dataset_filters,
        vdb=vdb,
        logger=logger,
    )

    comparison_sidebar_server("comparison_sidebar", active_module=active_module)
    comparison_workspace_server("comparison_workspace", active_module=active_module)

    # set the active module when a nav button is clicked
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

    # The page is always divided into a sidebar region and workspace region
    # this renders the sidebar region according to the active module
    @render.ui
    def sidebar_region() -> ui.Tag:
        selected_module = active_module()
        logger.debug(f"Rendering sidebar for active module: {selected_module}")
        if selected_module == "home":
            # no sidebar for home module
            return ui.span()
        if selected_module == "selection":
            return selection_sidebar_ui("select_datasets_sidebar")
        if selected_module == "binding":
            return binding_sidebar_ui("binding_sidebar")
        if selected_module == "perturbation":
            return perturbation_sidebar_ui("perturbation_sidebar")
        if selected_module == "comparison":
            return comparison_sidebar_ui("comparison_sidebar")
        logger.error(f"No sidebar for active module: {selected_module}")
        return ui.span(ui.p("ERROR: No sidebar for: " + selected_module))

    # this renders the workspace region according to the active module
    @render.ui
    def workspace_region() -> ui.Tag:
        selected_module = active_module()
        logger.debug(f"Rendering workspace for active module: {selected_module}")
        if selected_module == "home":
            return home_ui()
        if selected_module == "selection":
            return selection_matrix_ui("select_datasets_workspace")
        if selected_module == "binding":
            return binding_workspace_ui("binding_workspace")
        if selected_module == "perturbation":
            return perturbation_workspace_ui("perturbation_workspace")
        if selected_module == "comparison":
            return comparison_workspace_ui("comparison_workspace")
        logger.error(f"No workspace for active module: {selected_module}")
        return ui.span(ui.p("ERROR: No workspace for: " + selected_module))


app = App(ui=app_ui, server=app_server)
