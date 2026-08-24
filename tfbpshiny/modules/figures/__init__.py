__all__ = ["figures_workspace_server"]


def __getattr__(name: str):  # type: ignore[return]
    if name == "figures_workspace_server":
        from tfbpshiny.modules.figures.server.workspace import figures_workspace_server

        return figures_workspace_server
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
