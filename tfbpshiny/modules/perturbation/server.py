"""Server functions for the Perturbation perturbation page."""

# #DUPLICATE: modules/binding/server.py, modules/comparison/server.py

from __future__ import annotations

from shiny import module


@module.server
def perturbation_sidebar_server(input, output, session, active_module) -> None:  # type: ignore[no-untyped-def] # noqa: E501
    pass


@module.server
def perturbation_workspace_server(input, output, session, active_module) -> None:  # type: ignore[no-untyped-def] # noqa: E501
    pass


__all__ = ["perturbation_sidebar_server", "perturbation_workspace_server"]
