"""
Standalone app for developing the Comparison (DTO) comparison page in isolation.

Run with:
    shiny run tfbpshiny/modules/comparison/page_test.py

"""

from __future__ import annotations

from typing import Any

from shiny import App, reactive, ui

from tfbpshiny.modules.comparison.server import (
    comparison_sidebar_server,
    comparison_workspace_server,
)
from tfbpshiny.modules.comparison.ui import (
    comparison_sidebar_ui,
    comparison_workspace_ui,
)

_ACTIVE_MODULE = "comparison"
_LABEL = "Comparison"

app_ui = ui.page_fillable(
    ui.div(
        {"class": "app-body", "style": "display:flex; height:100vh;"},
        comparison_sidebar_ui("module_sidebar", label=_LABEL),
        comparison_workspace_ui("module_workspace", label=_LABEL),
    ),
    padding=0,
    gap=0,
)


def server(input: Any, output: Any, session: Any) -> None:
    active_module: reactive.Value[str] = reactive.value(_ACTIVE_MODULE)
    comparison_sidebar_server("module_sidebar", active_module=active_module)
    comparison_workspace_server("module_workspace", active_module=active_module)


app = App(ui=app_ui, server=server)
