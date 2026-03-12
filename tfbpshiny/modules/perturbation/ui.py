"""UI functions for the Perturbation analysis page."""

from __future__ import annotations

from shiny import module, ui

from tfbpshiny.modules.module_template import sidebar_shell, workspace_shell


@module.ui
def perturbation_sidebar_ui() -> ui.Tag:
    return sidebar_shell(
        "perturbation-sidebar",
        header=ui.h2("Perturbation"),
        body=ui.output_ui("sidebar_controls"),
    )


@module.ui
def perturbation_workspace_ui() -> ui.Tag:
    return workspace_shell(
        "perturbation-workspace",
        header=ui.h1("Perturbation Analysis"),
        body=ui.div(
            ui.output_ui("distributions_plot"),
            ui.hr(),
            ui.output_ui("regulator_selector"),
            ui.output_ui("regulator_plots"),
        ),
    )


__all__ = ["perturbation_sidebar_ui", "perturbation_workspace_ui"]
