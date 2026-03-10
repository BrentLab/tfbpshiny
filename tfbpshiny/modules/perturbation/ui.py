"""UI functions for the Perturbation perturbation page."""

# #DUPLICATE: modules/binding/ui.py, modules/comparison/ui.py

from __future__ import annotations

from shiny import module, ui

from tfbpshiny.modules.module_template import sidebar_shell, workspace_shell


@module.ui
def perturbation_sidebar_ui(label: str = "Perturbation") -> ui.Tag:
    return sidebar_shell(
        "perturbation-sidebar",
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
def perturbation_workspace_ui(label: str = "Perturbation") -> ui.Tag:
    return workspace_shell(
        "perturbation-workspace",
        header=ui.h1(label),
        body=ui.div(
            {"class": "empty-state"},
            ui.h3("Coming soon"),
            ui.p("Perturbation content will be implemented here."),
        ),
    )


__all__ = ["perturbation_sidebar_ui", "perturbation_workspace_ui"]
