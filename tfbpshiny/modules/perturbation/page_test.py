"""
Standalone app for developing the Perturbation perturbation page in isolation.

Run with:
    shiny run tfbpshiny/modules/perturbation/page_test.py

"""

from __future__ import annotations

from typing import Any

from shiny import App, reactive, ui

from tfbpshiny.modules.perturbation.server import (
    perturbation_sidebar_server,
    perturbation_workspace_server,
)
from tfbpshiny.modules.perturbation.ui import (
    perturbation_sidebar_ui,
    perturbation_workspace_ui,
)

_ACTIVE_MODULE = "perturbation"
_LABEL = "Perturbation"

app_ui = ui.page_fillable(
    ui.div(
        {"class": "app-body", "style": "display:flex; height:100vh;"},
        perturbation_sidebar_ui("module_sidebar", label=_LABEL),
        perturbation_workspace_ui("module_workspace", label=_LABEL),
    ),
    padding=0,
    gap=0,
)


def server(input: Any, output: Any, session: Any) -> None:
    active_module: reactive.Value[str] = reactive.value(_ACTIVE_MODULE)
    perturbation_sidebar_server("module_sidebar", active_module=active_module)
    perturbation_workspace_server("module_workspace", active_module=active_module)


app = App(ui=app_ui, server=server)
