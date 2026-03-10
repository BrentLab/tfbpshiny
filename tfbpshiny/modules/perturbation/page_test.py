"""
Standalone app for developing the Perturbation analysis page in isolation.

Run with:
    shiny run tfbpshiny/modules/perturbation/page_test.py

"""

from __future__ import annotations

from typing import Any

from shiny import App, reactive, ui

from tfbpshiny.modules.perturbation.server import (
    analysis_sidebar_server,
    analysis_workspace_server,
)
from tfbpshiny.modules.perturbation.ui import analysis_sidebar_ui, analysis_workspace_ui

_ACTIVE_MODULE = "perturbation"
_LABEL = "Perturbation Analysis"

app_ui = ui.page_fillable(
    ui.div(
        {"class": "app-body", "style": "display:flex; height:100vh;"},
        analysis_sidebar_ui("ana_sidebar", label=_LABEL),
        analysis_workspace_ui("ana_workspace", label=_LABEL),
    ),
    padding=0,
    gap=0,
)


def server(input: Any, output: Any, session: Any) -> None:
    active_module: reactive.Value[str] = reactive.value(_ACTIVE_MODULE)
    analysis_sidebar_server("ana_sidebar", active_module=active_module)
    analysis_workspace_server("ana_workspace", active_module=active_module)


app = App(ui=app_ui, server=server)
