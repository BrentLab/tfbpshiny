"""
Workspace server for the Figures page.

The server builds one :class:`~tfbpshiny.modules.figures.server.context.FiguresContext`
per session and hands it to the per-figure ``register_*`` functions, each of which
creates that figure's reactives and outputs. Shiny registers a ``render.ui`` or
``reactive.calc`` against the current session wherever it is created, so moving them
into helper functions changes nothing about how they run; it only keeps each figure in
a file of its own.

"""

from __future__ import annotations

from logging import Logger
from typing import Any

import duckdb
from shiny import module, reactive

from tfbpshiny.datasets import SCHEMA_VERSION
from tfbpshiny.modules.figures.server.context import build_context
from tfbpshiny.modules.figures.server.fig1_3 import register_fig1_3
from tfbpshiny.modules.figures.server.fig4_5 import register_fig4_5
from tfbpshiny.modules.figures.server.fig6 import register_fig6
from tfbpshiny.modules.figures.server.fig7_9 import register_fig7_9
from tfbpshiny.modules.figures.server.fig10 import register_fig10
from tfbpshiny.modules.figures.server.shared import register_shared
from tfbpshiny.utils.perf import reset_render_counts


@module.server
def figures_workspace_server(
    input: Any,
    output: Any,
    session: Any,
    dataset_filters: reactive.Value[dict[str, Any]],
    conn: duckdb.DuckDBPyConnection,
    logger: Logger,
    db_schema_version: int | None = SCHEMA_VERSION,
) -> None:
    """
    Render the publication figures.

    Unlike the analysis pages, the figures are drawn over fixed dataset sets rather than
    the sidebar's active selection -- each figure is defined by an intersection of
    specific datasets, so letting the selection change them would change what the figure
    means. Per-dataset *sample* filters are honoured, since those decide which samples
    represent a dataset (e.g. the Hackett timepoint).

    :param dataset_filters: Reactive per-dataset sample filter specs.
    :param conn: Read-only DuckDB connection to the materialized database.
    :param logger: Application logger.
    :param db_schema_version: The database's stamped schema version (see
        ``utils.schema_check``); every figure shows a rebuild notice unless it equals
        :data:`tfbpshiny.datasets.SCHEMA_VERSION`.

    """
    session.on_flush(lambda: reset_render_counts(session.id))

    ctx = build_context(conn, logger, dataset_filters, db_schema_version)
    shared = register_shared(input, session, ctx)
    register_fig1_3(input, session, ctx, shared)
    register_fig4_5(input, session, ctx, shared)
    register_fig6(input, session, ctx, shared)
    register_fig7_9(input, session, ctx, shared)
    register_fig10(input, session, ctx, shared)


__all__ = ["figures_workspace_server"]
