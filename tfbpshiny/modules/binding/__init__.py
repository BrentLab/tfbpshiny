__all__ = ["binding_workspace_server"]


def __getattr__(name: str):  # type: ignore[return]
    if name == "binding_workspace_server":
        from tfbpshiny.modules.binding.server.workspace import binding_workspace_server

        return binding_workspace_server
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
