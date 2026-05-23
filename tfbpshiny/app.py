from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any, Literal, cast

from dotenv import load_dotenv
from shiny import App, reactive, render, ui
from shiny.reactive import extended_task

from configure_logger import configure_logger
from tfbpshiny.components import github_badge
from tfbpshiny.modules.binding.server import binding_server
from tfbpshiny.modules.binding.ui import binding_ui
from tfbpshiny.modules.comparison.server import comparison_server
from tfbpshiny.modules.comparison.ui import comparison_ui
from tfbpshiny.modules.home.ui import home_ui
from tfbpshiny.modules.perturbation.server import perturbation_server
from tfbpshiny.modules.perturbation.ui import perturbation_ui
from tfbpshiny.modules.select_datasets.server import select_datasets_server
from tfbpshiny.modules.select_datasets.ui import selection_ui
from tfbpshiny.utils.vdb_init import check_local_cache, initialize_data

# Module UIs are declared once at startup. The actual output bindings inside
# each module only resolve after the server is registered (post-init), so the
# panels show Shiny's default blank/loading state until data is ready without
# any extra wrapper render functions.
_selection_ui = selection_ui("select_datasets")
_binding_ui = binding_ui("binding")
_perturbation_ui = perturbation_ui("perturbation")
_comparison_ui = comparison_ui("comparison")

if not os.getenv("DOCKER_ENV"):
    load_dotenv(dotenv_path=Path(".env"))

logger = logging.getLogger("shiny")

_log_dir = Path("tfbpshiny_log")
_log_dir.mkdir(exist_ok=True)
_log_file = str(_log_dir / f"tfbpshiny_{time.strftime('%Y%m%d-%H%M%S')}.log")
_log_level = int(os.getenv("TFBPSHINY_LOG_LEVEL", str(logging.INFO)))
_log_handler = cast(
    Literal["console", "file"], os.getenv("TFBPSHINY_LOG_HANDLER", "console")
)
configure_logger(
    "shiny", level=_log_level, handler_type=_log_handler, log_file=_log_file
)
configure_logger(
    "labretriever", level=_log_level, handler_type=_log_handler, log_file=_log_file
)

virtualdb_config: str = os.getenv(
    "VIRTUALDB_CONFIG",
    str(Path(__file__).parent / "brentlab_yeast_collection.yaml"),
)
hf_token: str | None = os.getenv("HF_TOKEN")


_not_ready_ui = ui.div(
    {
        "style": "display:flex; align-items:center; justify-content:center;"
        " height:60%; color:#888; text-align:center;"
    },
    ui.p("Please visit the Dataset selection tab first to load the data."),
)

app_ui = ui.page_navbar(
    ui.nav_panel("Home", home_ui()),
    ui.nav_panel("Dataset selection", ui.output_ui("selection_status"), _selection_ui),
    ui.nav_panel("Binding", ui.output_ui("binding_status"), _binding_ui),
    ui.nav_panel("Perturbation", ui.output_ui("perturbation_status"), _perturbation_ui),
    ui.nav_panel("Comparison", ui.output_ui("comparison_status"), _comparison_ui),
    ui.nav_spacer(),
    ui.nav_control(github_badge()),
    title="TF Binding & Perturbation Explorer",
    id="main_nav",
    fillable=["Dataset selection", "Binding", "Perturbation", "Comparison"],
    navbar_options=ui.navbar_options(bg="#722F37", theme="dark"),
    header=ui.tags.head(
        ui.tags.script(src="plotly-3.5.0.min.js"),
        ui.include_css((Path(__file__).parent / "app.css").resolve()),
    ),
)


def app_server(input: Any, output: Any, session: Any) -> None:
    """Create shared reactive state and call all module servers."""

    @reactive.calc
    def _active_tab() -> str:
        return input.main_nav()

    # Fires exactly once when init succeeds; registers all module servers.
    @reactive.effect
    def _register_modules() -> None:
        if _init_task.status() != "success":
            return

        vdb, app_datasets = _init_task.result()

        active_binding_datasets, active_perturbation_datasets, dataset_filters = (
            select_datasets_server(
                "select_datasets",
                vdb=vdb,
                app_datasets=app_datasets,
                logger=logger,
                active_tab=_active_tab,
            )
        )

        binding_server(
            "binding",
            active_binding_datasets=active_binding_datasets,
            dataset_filters=dataset_filters,
            vdb=vdb,
            app_datasets=app_datasets,
            logger=logger,
            active_tab=_active_tab,
        )

        perturbation_server(
            "perturbation",
            active_perturbation_datasets=active_perturbation_datasets,
            dataset_filters=dataset_filters,
            vdb=vdb,
            app_datasets=app_datasets,
            logger=logger,
            active_tab=_active_tab,
        )

        comparison_server(
            "comparison",
            active_binding_datasets=active_binding_datasets,
            active_perturbation_datasets=active_perturbation_datasets,
            dataset_filters=dataset_filters,
            vdb=vdb,
            logger=logger,
            active_tab=_active_tab,
        )

    @extended_task
    async def _init_task(config: str, token: str | None) -> Any:
        """Run VirtualDB initialization off the main thread."""
        missing = await asyncio.to_thread(check_local_cache, config)
        if missing:
            raise RuntimeError(
                "Data cache is insufficient. Contact administrator with "
                "an issue at https://github.com/BrentLab/tfbpshiny/issues. "
                f"Missing repos: {missing}"
            )
        return await asyncio.to_thread(initialize_data, config, token)

    # Auto-start init on session load — no button required.
    _init_task.invoke(virtualdb_config, hf_token)

    _preparing_ui = ui.div(
        {
            "style": "display:flex; align-items:center; justify-content:center;"
            " padding: 2rem; color:#888; text-align:center;"
        },
        ui.p(
            "Preparing datasets. "
            "This typically takes less than 5 seconds. "
            "Thank you for your patience..."
        ),
    )

    def _status_panel(ready_content: ui.Tag | None = None) -> ui.Tag:
        """Return a status message or empty span based on init task state."""
        status = _init_task.status()
        if status == "success":
            return ready_content if ready_content is not None else ui.span()
        if status in ("error", "cancelled"):
            err = _init_task.error() if status == "error" else None
            msg = str(err) if err else "Initialisation was cancelled."
            return ui.div(
                {
                    "style": "display:flex; align-items:center;"
                    " justify-content:center; padding:2rem; color:#b00;"
                    " text-align:center;"
                },
                ui.p(msg),
            )
        return _preparing_ui

    @render.ui
    def selection_status() -> ui.Tag:
        return _status_panel()

    @render.ui
    def binding_status() -> ui.Tag:
        status = _init_task.status()
        if status == "success":
            return ui.span()
        return _status_panel(_not_ready_ui)

    @render.ui
    def perturbation_status() -> ui.Tag:
        status = _init_task.status()
        if status == "success":
            return ui.span()
        return _status_panel(_not_ready_ui)

    @render.ui
    def comparison_status() -> ui.Tag:
        status = _init_task.status()
        if status == "success":
            return ui.span()
        return _status_panel(_not_ready_ui)


app = App(
    ui=app_ui,
    server=app_server,
    static_assets=Path(__file__).parent / "www",
)
