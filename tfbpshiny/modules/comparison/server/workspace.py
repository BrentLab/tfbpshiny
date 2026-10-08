"""
Workspace server for the Comparison module.

The server builds one
:class:`~tfbpshiny.modules.comparison.server.context.ComparisonContext` per session,
registers the shared helpers and sidebar outputs, then hands both to one
``register_*`` function per inner tab. Shiny registers a ``render.ui`` or
``reactive.calc`` against the current session wherever it is created, so the split
changes nothing about how the outputs run.

"""

from __future__ import annotations

from logging import Logger
from typing import Any

import duckdb
from shiny import module, reactive

from tfbpshiny.datasets import SCHEMA_VERSION
from tfbpshiny.modules.comparison.server.compare_datasets import (
    register_compare_datasets,
)
from tfbpshiny.modules.comparison.server.compare_methods import (
    register_compare_methods,
)
from tfbpshiny.modules.comparison.server.compare_promoters import (
    register_compare_promoters,
)
from tfbpshiny.modules.comparison.server.context import build_context
from tfbpshiny.modules.comparison.server.method_model import register_method_model
from tfbpshiny.modules.comparison.server.shared import register_shared
from tfbpshiny.modules.comparison.server.sidebar import register_sidebar
from tfbpshiny.utils.perf import reset_render_counts


@module.server
def comparison_workspace_server(
    input: Any,
    output: Any,
    session: Any,
    active_binding_datasets: reactive.Calc_[list[str]],
    active_perturbation_datasets: reactive.Calc_[list[str]],
    dataset_filters: reactive.Value[dict[str, Any]],
    conn: duckdb.DuckDBPyConnection,
    logger: Logger,
    db_schema_version: int | None = SCHEMA_VERSION,
) -> None:
    """
    Render the Comparison workspace: topN matrix, distributions, promoter/method tables.

    :param active_binding_datasets: Reactive calc returning active primary binding
        db names.
    :param active_perturbation_datasets: Reactive calc returning active perturbation
        db names.
    :param dataset_filters: Reactive value with per-dataset filter specs.
    :param conn: Read-only DuckDB connection to the materialized database.
    :param logger: Application logger.
    :param db_schema_version: The database's stamped schema version (see
        ``utils.schema_check``); the DTO metric is offered only when it equals
        :data:`tfbpshiny.datasets.SCHEMA_VERSION`.

    """
    session.on_flush(lambda: reset_render_counts(session.id))

    ctx = build_context(
        conn,
        logger,
        active_binding_datasets,
        active_perturbation_datasets,
        dataset_filters,
        db_schema_version,
    )
    shared = register_shared(input, session, ctx)
    register_sidebar(input, session, ctx, shared)
    register_compare_datasets(input, session, ctx, shared)
    register_compare_promoters(input, session, ctx, shared)
    register_compare_methods(input, session, ctx, shared)
    register_method_model(input, session, ctx, shared)


__all__ = ["comparison_workspace_server"]
