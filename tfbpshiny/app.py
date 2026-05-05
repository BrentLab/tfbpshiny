from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Literal, cast

from dotenv import load_dotenv
from shiny import App, reactive, render, ui

from configure_logger import configure_logger, configure_profile_logger
from tfbpshiny.components import github_badge, nav_button
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
from tfbpshiny.utils.profiler import log_session_event
from tfbpshiny.utils.vdb_init import initialize_data

if not os.getenv("DOCKER_ENV"):
    load_dotenv(dotenv_path=Path(".env"))

# Logger settings are written to _TFBPSHINY_* env vars by __main__.py so that
# Shiny's --reload subprocess picks them up when it re-imports this module.
# These vars are never intended to be set by users directly.
_log_level = int(os.environ.get("_TFBPSHINY_LOG_LEVEL", str(logging.INFO)))
_log_handler = cast(
    Literal["console", "file"], os.environ.get("_TFBPSHINY_LOG_HANDLER", "console")
)
_log_file = (
    os.environ.get("_TFBPSHINY_LOG_FILE")
    or f"tfbpshiny_{time.strftime('%Y%m%d-%H%M%S')}.log"
)
_profile_handler = cast(
    Literal["console", "file"], os.environ.get("_TFBPSHINY_PROFILE_HANDLER", "console")
)
_profile_log_file = os.environ.get(
    "_TFBPSHINY_PROFILE_LOG_FILE", "tfbpshiny_profile.log"
)
_profile_enabled = os.environ.get("_TFBPSHINY_PROFILE_ENABLED", "1") == "1"

logger = configure_logger(
    "shiny",
    level=_log_level,
    handler_type=_log_handler,
    log_file=_log_file,
)
profile_logger = configure_profile_logger(
    handler_type=_profile_handler,
    log_file=_profile_log_file,
    enabled=_profile_enabled,
)

# instantiate the virtualDB and compute app-level dataset metadata

virtualdb_config = os.getenv(
    "VIRTUALDB_CONFIG", str(Path(__file__).parent / "brentlab_yeast_collection.yaml")
)
hf_token: str | None = os.getenv("HF_TOKEN")
logger.info(f"Loading VirtualDB with config: {virtualdb_config}")
vdb, app_datasets = initialize_data(
    virtualdb_config, hf_token, profile_logger=profile_logger
)

app_ui = ui.page_fillable(
    ui.include_css((Path(__file__).parent / "app.css").resolve()),
    ui.head_content(
        ui.tags.script("window.PlotlyConfig = {MathJaxConfig: 'local'};"),
        ui.tags.script(
            src="https://cdn.plot.ly/plotly-3.4.0.min.js",
            integrity="sha256-KEmPoupLpFyGMyGAiOsiNDbKDKAvxXAn/W+oQa0ZAfk=",
            crossorigin="anonymous",
        ),
    ),
    ui.div(
        {"class": "app-container"},
        ui.div(
            {"class": "nav-bar"},
            ui.div({"class": "nav-logo"}, "TF\nBinding & Perturbation\nExplorer"),
            ui.div(
                {"class": "nav-tags"},
                nav_button("home", "Home"),
                nav_button("selection", "Dataset selection"),
                nav_button("binding", "Binding"),
                nav_button("perturbation", "Perturbation"),
                nav_button("comparison", "Comparison"),
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

    sid: str = session.id
    log_session_event(profile_logger, "START", sid)
    session.on_ended(lambda: log_session_event(profile_logger, "END", sid))

    # Shared regulator selection — written by binding and perturbation workspace
    # servers so that navigating between tabs preserves the selected regulator.
    shared_regulator: reactive.Value[str] = reactive.Value("")

    _render_counts: dict[str, int] = {"sidebar_region": 0, "workspace_region": 0}

    # this stores the name of the currently active module, ie
    # "home", "selection", "binding", "perturbation", or "comparison"
    active_module: reactive.Value[str] = reactive.value("home")

    # Dataset selection state — shared across all analysis modules
    active_binding_datasets, active_perturbation_datasets, dataset_filters = (
        select_datasets_sidebar_server(
            "select_datasets_sidebar",
            vdb=vdb,
            app_datasets=app_datasets,
            logger=logger,
            active_module=active_module,
        )
    )
    select_datasets_workspace_server(
        "select_datasets_workspace",
        active_binding_datasets=active_binding_datasets,
        active_perturbation_datasets=active_perturbation_datasets,
        dataset_filters=dataset_filters,
        vdb=vdb,
        logger=logger,
        profile_logger=profile_logger,
        session_id=sid,
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
        app_datasets=app_datasets,
        logger=logger,
        profile_logger=profile_logger,
        session_id=sid,
        shared_regulator=shared_regulator,
        active_module=active_module,
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
        app_datasets=app_datasets,
        logger=logger,
        profile_logger=profile_logger,
        session_id=sid,
        shared_regulator=shared_regulator,
        active_module=active_module,
    )

    top_n, effect_threshold, pvalue_threshold, facet_by = comparison_sidebar_server(
        "comparison_sidebar",
        active_binding_datasets=active_binding_datasets,
        active_perturbation_datasets=active_perturbation_datasets,
        vdb=vdb,
        logger=logger,
    )
    comparison_workspace_server(
        "comparison_workspace",
        active_binding_datasets=active_binding_datasets,
        active_perturbation_datasets=active_perturbation_datasets,
        dataset_filters=dataset_filters,
        top_n=top_n,
        effect_threshold=effect_threshold,
        pvalue_threshold=pvalue_threshold,
        facet_by=facet_by,
        vdb=vdb,
        logger=logger,
        profile_logger=profile_logger,
        session_id=sid,
    )

    # set the active module when a nav button is clicked
    @reactive.effect
    @reactive.event(input.home, ignore_init=True)
    def _nav_home() -> None:
        """
        Switch the active module to the home page.

        :trigger: ``input.home`` — fires when the user clicks the HOME nav button.

        """
        active_module.set("home")

    @reactive.effect
    @reactive.event(input.selection, ignore_init=True)
    def _nav_selection() -> None:
        """
        Switch the active module to the dataset selection page.

        :trigger: ``input.selection`` — fires when the user clicks the SELECT
            DATASETS nav button.

        """
        active_module.set("selection")

    @reactive.effect
    @reactive.event(input.binding, ignore_init=True)
    def _nav_binding() -> None:
        """
        Switch the active module to the binding data page.

        :trigger: ``input.binding`` — fires when the user clicks the BINDING nav
            button.

        """
        active_module.set("binding")

    @reactive.effect
    @reactive.event(input.perturbation, ignore_init=True)
    def _nav_perturbation() -> None:
        """
        Switch the active module to the perturbation data page.

        :trigger: ``input.perturbation`` — fires when the user clicks the
            PERTURBATION nav button.

        """
        active_module.set("perturbation")

    @reactive.effect
    @reactive.event(input.comparison, ignore_init=True)
    def _nav_comparison() -> None:
        """
        Switch the active module to the comparison analysis page.

        :trigger: ``input.comparison`` — fires when the user clicks the COMPARISON
            nav button.

        """
        active_module.set("comparison")

    # The page is always divided into a sidebar region and workspace region
    # this renders the sidebar region according to the active module
    @render.ui
    def sidebar_region() -> ui.Tag:
        selected_module = active_module()
        _render_counts["sidebar_region"] += 1
        t0 = time.perf_counter()
        logger.debug(
            f"RENDER app/sidebar_region #{_render_counts['sidebar_region']} "
            f"module={selected_module!r}"
        )
        if selected_module == "home":
            result: ui.Tag = ui.span()
        elif selected_module == "selection":
            result = selection_sidebar_ui("select_datasets_sidebar")
        elif selected_module == "binding":
            result = binding_sidebar_ui("binding_sidebar")
        elif selected_module == "perturbation":
            result = perturbation_sidebar_ui("perturbation_sidebar")
        elif selected_module == "comparison":
            result = comparison_sidebar_ui("comparison_sidebar")
        else:
            logger.error(f"No sidebar for active module: {selected_module}")
            result = ui.span(ui.p("ERROR: No sidebar for: " + selected_module))
        logger.debug(
            f"RENDER_DONE app/sidebar_region #{_render_counts['sidebar_region']} "
            f"module={selected_module!r} elapsed={time.perf_counter()-t0:.3f}s"
        )
        return result

    # this renders the workspace region according to the active module
    @render.ui
    def workspace_region() -> ui.Tag:
        selected_module = active_module()
        _render_counts["workspace_region"] += 1
        t0 = time.perf_counter()
        logger.debug(
            f"RENDER app/workspace_region #{_render_counts['workspace_region']} "
            f"module={selected_module!r}"
        )
        if selected_module == "home":
            result = home_ui()
        elif selected_module == "selection":
            result = selection_matrix_ui("select_datasets_workspace")
        elif selected_module == "binding":
            result = binding_workspace_ui("binding_workspace")
        elif selected_module == "perturbation":
            result = perturbation_workspace_ui("perturbation_workspace")
        elif selected_module == "comparison":
            result = comparison_workspace_ui("comparison_workspace")
        else:
            logger.error(f"No workspace for active module: {selected_module}")
            result = ui.span(ui.p("ERROR: No workspace for: " + selected_module))
        logger.debug(
            f"RENDER_DONE app/workspace_region #{_render_counts['workspace_region']} "
            f"module={selected_module!r} elapsed={time.perf_counter()-t0:.3f}s"
        )
        return result


app = App(
    ui=app_ui,
    server=app_server,
    static_assets=Path(__file__).parent / "www",
)
