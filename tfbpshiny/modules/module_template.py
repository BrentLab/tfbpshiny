"""Shared UI scaffolding for sidebar+workspace module views."""

from __future__ import annotations

from shiny import ui


def sidebar_shell(
    id: str,
    *,
    header: ui.Tag | str,
    body: ui.Tag,
    footer: ui.Tag | None = None,
) -> ui.Tag:
    children = [
        ui.div({"class": "sidebar-header"}, header),
        ui.div({"class": "sidebar-body"}, body),
    ]
    if footer is not None:
        children.append(ui.div({"class": "sidebar-footer"}, footer))
    return ui.div({"class": "context-sidebar", "id": id}, *children)


def workspace_shell(id: str, *, header: ui.Tag | str, body: ui.Tag) -> ui.Tag:
    return ui.div(
        {"class": "main-workspace", "id": id},
        ui.div({"class": "workspace-header"}, header),
        ui.div({"class": "workspace-body"}, body),
    )
