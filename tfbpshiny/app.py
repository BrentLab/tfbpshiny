from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Literal, cast

from shiny import App, reactive, ui

from tfbpshiny.components import github_badge
from tfbpshiny.configure_logger import configure_logger
from tfbpshiny.modules.binding.server import binding_workspace_server
from tfbpshiny.modules.binding.ui import binding_ui
from tfbpshiny.modules.comparison.server import comparison_workspace_server
from tfbpshiny.modules.comparison.ui import comparison_ui
from tfbpshiny.modules.figures.server import figures_workspace_server
from tfbpshiny.modules.figures.ui import figures_ui
from tfbpshiny.modules.home.ui import HOME_CARD_NAV_TARGETS, home_ui
from tfbpshiny.modules.perturbation.server import perturbation_workspace_server
from tfbpshiny.modules.perturbation.ui import perturbation_ui
from tfbpshiny.modules.select_datasets.server import select_datasets_server
from tfbpshiny.modules.select_datasets.ui import selection_ui
from tfbpshiny.utils.corr_query import expand_filters_to_variants

logger = logging.getLogger("shiny")

log_level = int(os.getenv("TFBPSHINY_LOG_LEVEL", str(logging.INFO)))
log_handler = cast(
    Literal["console", "file"], os.getenv("TFBPSHINY_LOG_HANDLER", "console")
)
configure_logger("shiny", level=log_level, handler_type=log_handler)

_db_path = os.getenv(
    "TFBPSHINY_DB_PATH",
    str(Path(__file__).parent / "brentlab_yeast.duckdb"),
)

# Module UIs are declared once at startup.
_selection_ui = selection_ui("select_datasets")
_binding_ui = binding_ui("binding")
_perturbation_ui = perturbation_ui("perturbation")
_comparison_ui = comparison_ui("comparison")
_figures_ui = figures_ui("figures")

app_ui = ui.page_navbar(
    ui.nav_panel("Home", home_ui()),
    ui.nav_panel("Dataset selection", _selection_ui),
    ui.nav_panel("Binding", _binding_ui),
    ui.nav_panel("Perturbation", _perturbation_ui),
    ui.nav_panel(
        "Binding/Perturbation Comparisons",
        _comparison_ui,
    ),
    ui.nav_panel("Figures", _figures_ui),
    ui.nav_spacer(),
    ui.nav_control(github_badge()),
    title="TF Binding & Perturbation Explorer",
    id="main_nav",
    fillable=[
        "Dataset selection",
        "Binding",
        "Perturbation",
        "Binding/Perturbation Comparisons",
        "Figures",
    ],
    navbar_options=ui.navbar_options(bg="#722F37", theme="dark"),
    header=ui.TagList(
        ui.tags.head(
            ui.tags.script(src="plotly-3.5.0.min.js"),
            ui.include_css((Path(__file__).parent / "app.css").resolve()),
        ),
        ui.output_ui("schema_banner"),
    ),
)


def app_server(input: Any, output: Any, session: Any) -> None:
    """Create shared reactive state and call all module servers."""
    import duckdb
    from shiny import render

    from tfbpshiny.utils.schema_check import (
        check_schema_version,
        schema_mismatch_message,
    )
    from tfbpshiny.utils.vdb_init import load_app_datasets

    conn: duckdb.DuckDBPyConnection = duckdb.connect(_db_path, read_only=True)
    db_schema_version = check_schema_version(conn, logger)
    app_datasets = load_app_datasets(conn)

    @render.ui
    def schema_banner() -> ui.Tag | None:
        """One banner above every page when the database predates (or postdates) the
        app's schema version; nothing otherwise."""
        message = schema_mismatch_message(db_schema_version)
        if message is None:
            return None
        return ui.div(
            {"class": "alert alert-warning mb-0 rounded-0", "role": "alert"},
            ui.strong("Database schema mismatch. "),
            message,
        )

    # Navigate to the target tab when a home-page card title link is clicked.
    for _link_id, _target in HOME_CARD_NAV_TARGETS.items():

        def _make_nav_effect(link_id: str, target: str) -> None:
            @reactive.effect
            @reactive.event(getattr(input, link_id))
            def _nav_to_tab() -> None:
                ui.update_navset("main_nav", selected=target)

        _make_nav_effect(_link_id, _target)

    active_binding_datasets, active_perturbation_datasets, dataset_filters = (
        select_datasets_server(
            "select_datasets",
            conn=conn,
            app_datasets=app_datasets,
            logger=logger,
        )
    )

    @reactive.calc
    def analysis_filters() -> dict[str, Any]:
        """
        The committed filters with each primary's filter copied onto its variants.

        The selection tab edits the primaries; the analysis modules look filters up by
        whichever variant they resolved, so they need the expanded form. A drop-in for
        ``dataset_filters`` -- the modules only ever call it.

        :trigger: ``dataset_filters`` -- re-runs whenever the committed filters change.

        """
        return expand_filters_to_variants(conn, dataset_filters())

    binding_workspace_server(
        "binding",
        active_binding_datasets=active_binding_datasets,
        dataset_filters=analysis_filters,
        conn=conn,
        logger=logger,
    )

    perturbation_workspace_server(
        "perturbation",
        active_perturbation_datasets=active_perturbation_datasets,
        dataset_filters=analysis_filters,
        conn=conn,
        logger=logger,
    )

    comparison_workspace_server(
        "comparison",
        active_binding_datasets=active_binding_datasets,
        active_perturbation_datasets=active_perturbation_datasets,
        dataset_filters=analysis_filters,
        conn=conn,
        logger=logger,
        db_schema_version=db_schema_version,
    )

    figures_workspace_server(
        "figures",
        dataset_filters=analysis_filters,
        conn=conn,
        logger=logger,
        db_schema_version=db_schema_version,
    )


app = App(
    ui=app_ui,
    server=app_server,
    static_assets=Path(__file__).parent / "www",
)
