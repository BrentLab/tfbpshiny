"""UI functions for the Binding analysis page."""

from __future__ import annotations

from shiny import module, ui

from tfbpshiny.modules.module_template import sidebar_shell, workspace_shell


@module.ui
def binding_sidebar_ui() -> ui.Tag:
    return sidebar_shell(
        "binding-sidebar",
        header=ui.h2("Binding"),
        body=ui.output_ui("sidebar_controls"),
    )


@module.ui
def binding_workspace_ui() -> ui.Tag:
    return workspace_shell(
        "binding-workspace",
        header=ui.h1("Binding Correlation"),
        body=ui.div(
            ui.output_ui("distributions_plot"),
            ui.hr(),
            ui.output_ui("regulator_selector"),
            ui.output_ui("regulator_plots"),
        ),
    )


__all__ = ["binding_sidebar_ui", "binding_workspace_ui"]
