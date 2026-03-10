"""UI functions for the Binding binding page."""

# #DUPLICATE: modules/perturbation/ui.py, modules/comparison/ui.py

from __future__ import annotations

from shiny import module, ui

from tfbpshiny.modules.module_template import sidebar_shell, workspace_shell


@module.ui
def binding_sidebar_ui(label: str = "Binding") -> ui.Tag:
    return sidebar_shell(
        "binding-sidebar",
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
def binding_workspace_ui(label: str = "Binding") -> ui.Tag:
    return workspace_shell(
        "binding-workspace",
        header=ui.h1(label),
        body=ui.div(
            {"class": "empty-state"},
            ui.h3("Coming soon"),
            ui.p("Binding content will be implemented here."),
        ),
    )


__all__ = ["binding_sidebar_ui", "binding_workspace_ui"]
