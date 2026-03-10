"""UI functions for the Comparison (DTO) comparison page."""

# #DUPLICATE: modules/binding/ui.py, modules/perturbation/ui.py

from __future__ import annotations

from shiny import module, ui

from tfbpshiny.modules.module_template import sidebar_shell, workspace_shell


@module.ui
def comparison_sidebar_ui(label: str = "Comparison") -> ui.Tag:
    return sidebar_shell(
        "comparison-sidebar",
        header=ui.div(
            ui.h2(label),
            ui.div({"class": "subtitle"}, "Controls will appear here"),
        ),
        body=ui.div(
            {"class": "empty-state"},
            ui.p("Sidebar controls coming soon."),
        ),
    )


@module.ui
def comparison_workspace_ui(label: str = "Comparison") -> ui.Tag:
    return workspace_shell(
        "comparison-workspace",
        header=ui.h1(label),
        body=ui.div(
            {"class": "empty-state"},
            ui.h3("Coming soon"),
            ui.p("Comparison content will be implemented here."),
        ),
    )


__all__ = ["comparison_sidebar_ui", "comparison_workspace_ui"]
