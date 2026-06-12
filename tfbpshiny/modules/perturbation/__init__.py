__all__ = ["perturbation_server", "perturbation_workspace_server"]


def __getattr__(name: str):  # type: ignore[return]
    if name == "perturbation_server":
        from tfbpshiny.modules.perturbation.server import perturbation_server

        return perturbation_server
    if name == "perturbation_workspace_server":
        from tfbpshiny.modules.perturbation.server.workspace import (
            perturbation_workspace_server,
        )

        return perturbation_workspace_server
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
