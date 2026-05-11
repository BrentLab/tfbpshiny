from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Literal, cast

from dotenv import load_dotenv
from labretriever import VirtualDB
from shiny import App, reactive, render, ui
from shiny.reactive._core import flush as reactive_flush
from shiny.reactive._core import lock as reactive_lock

from configure_logger import configure_logger
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
from tfbpshiny.utils.vdb_init import AppDatasets, check_local_cache, initialize_data

if not os.getenv("DOCKER_ENV"):
    load_dotenv(dotenv_path=Path(".env"))

logger = logging.getLogger("shiny")

# Log config is set by __main__.py via env vars before run_app() (and before any reload
# worker re-imports this module). Env vars are the only mechanism that crosses the
# uvicorn subprocess boundary. HF_TOKEN stays env-var-only for security.
_log_file = f"tfbpshiny_{time.strftime('%Y%m%d-%H%M%S')}.log"
_log_level = int(os.getenv("TFBPSHINY_LOG_LEVEL", str(logging.INFO)))
_log_handler = cast(
    Literal["console", "file"], os.getenv("TFBPSHINY_LOG_HANDLER", "console")
)
configure_logger(
    "shiny", level=_log_level, handler_type=_log_handler, log_file=_log_file
)

virtualdb_config: str = os.getenv(
    "VIRTUALDB_CONFIG",
    str(Path(__file__).parent / "brentlab_yeast_collection.yaml"),
)
hf_token: str | None = os.getenv("HF_TOKEN")

app_ui = ui.page_fillable(
    ui.tags.head(
        ui.tags.script(src="plotly-3.5.0.min.js"),
    ),
    ui.include_css((Path(__file__).parent / "app.css").resolve()),
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

    active_module: reactive.Value[str] = reactive.value("home")

    # Holds (vdb, app_datasets) once the background thread finishes.
    # None means init is still running.
    _init_result: reactive.Value[tuple[VirtualDB, AppDatasets] | None] = reactive.value(
        None
    )

    # Capture the event loop on the main thread before spawning the worker.
    _loop = asyncio.get_event_loop()

    def _run_init() -> None:
        missing = check_local_cache(virtualdb_config)
        if missing:
            logger.error(
                "Local HuggingFace cache is incomplete. Run "
                "'tfbpshiny initialize' to download all datasets before "
                "starting the app. Missing repos: %s",
                missing,
            )
            return
        logger.info("Starting VirtualDB initialization in background thread.")
        try:
            result = initialize_data(virtualdb_config, hf_token)
            logger.info("VirtualDB initialization complete.")
        except Exception:
            logger.exception("VirtualDB initialization failed.")
            return

        async def _deliver() -> None:
            async with reactive_lock():
                _init_result.set(result)
                await reactive_flush()

        _loop.call_soon_threadsafe(asyncio.create_task, _deliver())

    threading.Thread(target=_run_init, daemon=True).start()

    # Fires exactly once when init finishes; registers all module servers.
    @reactive.effect
    def _register_modules() -> None:
        result = _init_result()
        if result is None:
            return

        vdb, app_datasets = result

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
            active_module=active_module,
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
            active_module=active_module,
        )

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

    _loading_ui = ui.div(
        {
            "style": "display:flex; align-items:center; "
            "justify-content:center; height:100%; color:#888;"
        },
        ui.p("Loading data, please wait..."),
    )

    @render.ui
    def sidebar_region() -> ui.Tag:
        selected_module = active_module()
        logger.debug(f"Rendering sidebar for active module: {selected_module}")
        if selected_module == "home":
            return ui.span()
        if _init_result() is None:
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

    @render.ui
    def workspace_region() -> ui.Tag:
        selected_module = active_module()
        logger.debug(f"Rendering workspace for active module: {selected_module}")
        if selected_module == "home":
            return home_ui()
        if _init_result() is None:
            return _loading_ui
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


app = App(
    ui=app_ui,
    server=app_server,
    static_assets=Path(__file__).parent / "www",
)
