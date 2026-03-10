"""Server functions for the Binding analysis page."""

from __future__ import annotations

from shiny import module


@module.server
def binding_sidebar_server(input, output, session, active_module) -> None:  # type: ignore[no-untyped-def] # noqa: E501
    pass


@module.server
def binding_workspace_server(input, output, session, active_module) -> None:  # type: ignore[no-untyped-def] # noqa: E501
    pass


__all__ = ["binding_sidebar_server", "binding_workspace_server"]
