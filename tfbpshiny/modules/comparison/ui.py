"""UI functions for the Comparison (DTO) comparison page."""

from __future__ import annotations

from shiny import module, ui

from tfbpshiny.components import (
    empty_state,
    sidebar_heading,
    sidebar_shell,
    sidebar_subtitle,
    workspace_heading,
    workspace_shell,
)


@module.ui
def comparison_sidebar_ui(label: str = "Comparison") -> ui.Tag:
    return sidebar_shell(
        "comparison-sidebar",
        header=ui.div(
            sidebar_heading(label),
            sidebar_subtitle("Controls will appear here"),
        ),
        body=empty_state(ui.p("Sidebar controls coming soon.")),
    )


@module.ui
def comparison_workspace_ui(label: str = "Comparison") -> ui.Tag:
    return workspace_shell(
        "comparison-workspace",
        header=workspace_heading(label),
        body=empty_state(
            ui.h3("Coming soon"),
            ui.p("Comparison content will be implemented here."),
        ),
    )


__all__ = ["comparison_sidebar_ui", "comparison_workspace_ui"]
