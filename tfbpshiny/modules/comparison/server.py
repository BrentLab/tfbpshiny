"""Server functions for the comparison page."""

# #DUPLICATE: modules/binding/server.py, modules/perturbation/server.py

from __future__ import annotations

from shiny import module


@module.server
def comparison_sidebar_server(input, output, session, active_module) -> None:  # type: ignore[no-untyped-def] # noqa: E501
    pass


@module.server
def comparison_workspace_server(input, output, session, active_module) -> None:  # type: ignore[no-untyped-def] # noqa: E501
    pass


__all__ = ["comparison_sidebar_server", "comparison_workspace_server"]
