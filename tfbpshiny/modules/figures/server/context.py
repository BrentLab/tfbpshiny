"""
Per-session state shared by every figure of the Figures page.

Built once when the module server starts and handed to each ``register_*`` function
in this package, so the figures never re-query labels or the registry.

"""

from __future__ import annotations

from dataclasses import dataclass, field
from logging import Logger
from typing import Any

import duckdb
from shiny import reactive, ui

from tfbpshiny.components import empty_state
from tfbpshiny.datasets import SCHEMA_VERSION
from tfbpshiny.modules.figures.queries import (
    AGREEMENT_DEFAULT_BINDING,
    AGREEMENT_DEFAULT_PERTURBATION,
    agreement_dataset_choices,
    dataset_labels,
)
from tfbpshiny.utils.schema_check import schema_mismatch_message
from tfbpshiny.utils.vdb_init import (
    binding_method_labels,
    get_regulator_display_name,
    promoter_set_labels,
)

#: Width of one panel in the three-across figure rows.
PANEL_WIDTH = "min-width: 420px; flex: 1 1 420px;"

#: Flex row holding two side-by-side panels (figures 6 and 10).
TWO_PANEL_ROW = {
    "style": "display: flex; gap: 1.5rem; align-items: flex-start; flex-wrap: wrap;"
}

#: Panel headings for the two comparison types of figures 6 and 10.
AGREEMENT_HEADINGS: dict[str, str] = {
    "binding": "Binding vs. binding",
    "perturbation": "Perturbation vs. perturbation",
}


@dataclass
class FiguresContext:
    """
    Everything a figure needs besides its own inputs.

    :param conn: Read-only DuckDB connection to the materialized database.
    :param logger: Application logger.
    :param dataset_filters: Reactive per-dataset sample filter specs.
    :param db_schema_version: The database's stamped schema version.
    :param labels: ``db_name -> base_label`` for every registry row.
    :param promoter_set_labels: ``promoter_set_id -> display_name``.
    :param method_labels: ``binding_method_id -> display_name``.
    :param reg_labels: ``locus tag -> "SYMBOL (tag)"`` (or the tag alone).
    :param reg_symbols: ``locus tag -> symbol`` for regulators that have one.
    :param agreement_choices: Selectable datasets for figures 6 and 10, per comparison
        type, in display order.
    :param agreement_defaults: Default selection per comparison type.

    """

    conn: duckdb.DuckDBPyConnection
    logger: Logger
    dataset_filters: reactive.Value[dict[str, Any]]
    db_schema_version: int | None
    labels: dict[str, str] = field(default_factory=dict)
    promoter_set_labels: dict[str, str] = field(default_factory=dict)
    method_labels: dict[str, str] = field(default_factory=dict)
    reg_labels: dict[str, str] = field(default_factory=dict)
    reg_symbols: dict[str, str] = field(default_factory=dict)
    agreement_choices: dict[str, dict[str, str]] = field(default_factory=dict)
    agreement_defaults: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def schema_current(self) -> bool:
        """
        Whether the database was built at the schema version this app reads.

        One stamp decides every figure. A database built by another materializer may
        lack whole tables or columns the read-side SQL names, so nothing is drawn from
        it; app.py shows the banner and has logged the mismatch once.

        """
        return self.db_schema_version == SCHEMA_VERSION

    def needs_rebuild(self, what: str) -> ui.Tag:
        """Empty state for a figure the database's schema version cannot support."""
        return empty_state(
            ui.p(
                ui.strong(f"{what} cannot be read from this database."),
                " ",
                schema_mismatch_message(self.db_schema_version) or "",
            ),
        )


def build_context(
    conn: duckdb.DuckDBPyConnection,
    logger: Logger,
    dataset_filters: reactive.Value[dict[str, Any]],
    db_schema_version: int | None,
) -> FiguresContext:
    """
    Read the labels and registry facts the figures share, once per session.

    :param conn: Read-only DuckDB connection.
    :param logger: Application logger.
    :param dataset_filters: Reactive per-dataset sample filter specs.
    :param db_schema_version: The database's stamped schema version.
    :returns: The populated context.

    """
    ctx = FiguresContext(conn, logger, dataset_filters, db_schema_version)
    ctx.labels = dataset_labels(conn)
    # Axis labels for the promoter-set / method boxes come from the registry
    # tables the build wrote, so they cannot drift from the Comparison page.
    ctx.promoter_set_labels = promoter_set_labels(conn)
    ctx.method_labels = binding_method_labels(conn)

    for _, row in get_regulator_display_name(conn).iterrows():
        tag = str(row["regulator_locus_tag"])
        sym = str(row.get("regulator_symbol", ""))
        if sym and sym not in ("nan", tag):
            ctx.reg_labels[tag] = f"{sym} ({tag})"
            ctx.reg_symbols[tag] = sym
        else:
            ctx.reg_labels[tag] = tag

    # Selectable datasets, read once: dataset_registry does not change per session.
    ctx.agreement_choices = (
        {
            ctype: agreement_dataset_choices(conn, ctype)
            for ctype in ("binding", "perturbation")
        }
        if ctx.schema_current
        else {"binding": {}, "perturbation": {}}
    )
    ctx.agreement_defaults = {
        "binding": AGREEMENT_DEFAULT_BINDING,
        "perturbation": AGREEMENT_DEFAULT_PERTURBATION,
    }
    # A default naming a dataset the registry does not have is dropped by the
    # membership filter in agreement_selection, which would quietly shrink figure 6
    # rather than fail. Renames make that a live risk, so say so.
    for ctype, defaults in ctx.agreement_defaults.items():
        missing = [d for d in defaults if d not in ctx.agreement_choices.get(ctype, {})]
        if missing and ctx.schema_current:
            logger.warning(
                "figures: figure 6's default %s datasets %s are not in"
                " dataset_registry and will be dropped from the default view;"
                " check for a renamed db_name",
                ctype,
                missing,
            )
    return ctx


__all__ = [
    "AGREEMENT_HEADINGS",
    "FiguresContext",
    "PANEL_WIDTH",
    "TWO_PANEL_ROW",
    "build_context",
]
