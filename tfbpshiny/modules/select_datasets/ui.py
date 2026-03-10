"""UI functions for the Select Datasets page."""

from __future__ import annotations

from shiny import module, ui

from tfbpshiny.modules.module_template import workspace_shell


@module.ui
def selection_sidebar_ui() -> ui.Tag:
    """Render the Active Set sidebar shell."""
    return ui.output_ui("sidebar_panel")


@module.ui
def selection_matrix_ui() -> ui.Tag:
    """Render the intersection matrix workspace."""
    return workspace_shell(
        "selection-workspace",
        header=ui.h1("Intersection Summary"),
        body=ui.output_ui("matrix_content"),
    )


__all__ = ["selection_sidebar_ui", "selection_matrix_ui"]
