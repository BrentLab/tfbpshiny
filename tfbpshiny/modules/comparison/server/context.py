"""
Per-session state and pure helpers shared by every tab of the Comparison page.

Built once when the module server starts and handed to each ``register_*`` function in
this package. The input readers and small formatting helpers live here too, so the tab
modules import them rather than redefining them.

"""

from __future__ import annotations

from dataclasses import dataclass, field
from logging import Logger
from typing import Any

import duckdb
import pandas as pd
from shiny import reactive

from tfbpshiny.datasets import PRESET_NAMES, SCHEMA_VERSION
from tfbpshiny.modules.comparison.queries import (
    DEFAULT_DTO_RANKING_COLUMN,
    DEFAULT_TOP_N,
    METRIC_TOPN,
    BindingIndex,
    build_binding_index,
)
from tfbpshiny.utils.inputs import read_input
from tfbpshiny.utils.vdb_init import (
    DEFAULT_RESPONSIVENESS_PRESET,
    DEFAULT_RESPONSIVENESS_PRESETS,
    get_regulator_display_name,
)

#: Row order of the Compare Promoter Definitions tables, by binding base label.
BINDING_ORDER_LABELS = [
    "2004 ChIP-chip",
    "2021 ChIP-exo",
    "2025 ChEC-seq",
    "2026 Calling Cards",
]

#: Tooltip for each responsiveness preset, keyed by name.
PRESET_HELP: dict[str, str] = {
    "Relaxed": (
        "Applies a uniform pvalue < 0.05 threshold. Hover over"
        " perturbation column headers in Compare Datasets for"
        " per-dataset details."
    ),
    "Stringent": (
        "Uses the original authors' thresholds for each dataset."
        " Hover over perturbation column headers in Compare"
        " Datasets for per-dataset details."
    ),
}

assert set(PRESET_HELP) == set(PRESET_NAMES)

#: Selector label for each promoter set, keyed by ``promoter_set_id``.
PROMOTER_SET_ALIAS: dict[str, str] = {
    "kang": "Promoter Set 1 (Kang)",
    "mindel": "Promoter Set 2 (Mindel)",
    "500bp": "Promoter Set 3 (500bp)",
    "intergenic": "Promoter Set 4 (Intergenic)",
}

#: Tooltip text for each promoter set, keyed by ``promoter_set_id``.
PROMOTER_TOOLTIPS: dict[str, str] = {
    "kang": (
        "700 bp upstream of each start codon, truncated if there exists a feature "
        "within 700 bp of the ORF."
    ),
    "mindel": (
        "Promoter regions defined from the start codon to at least 700 bp upstream "
        "of the TSS defined by Park et al., 2014; Pelechano et al., 2013; Policastro "
        "et al., 2020 (provided in the SGD annotations). If no TSS is defined, the "
        "start codon is used."
    ),
    "500bp": (
        "Promoter regions defined as exactly 500 bp upstream of the start codon. "
        "No truncation or extension; all promoters are the same length."
    ),
    "intergenic": (
        "Promoter regions defined as the full intergenic region upstream of the 5' "
        "end of each feature. Note that approximately 1410 of 6040 features are "
        "divergently transcribed."
    ),
}


def inputs_ready(input: Any, *names: str) -> bool:
    """
    Whether every named input exists and has a value yet.

    ``tab_specific_controls`` creates the per-tab inputs on demand, so on first
    load and for one flush after a tab switch they are absent. The ``read_*``
    helpers below fall back to defaults when that happens, which would make a
    live data calc fetch once against the fallbacks and again once the real
    values arrive. Gating on this avoids that double fetch.

    Reading each input registers a reactive dependency, so the calc re-runs as
    soon as the inputs appear.

    :param input: Shiny input object.
    :param names: Input ids that must be present.
    :returns: ``True`` when all are available.

    """
    return all(read_input(input, name, None) is not None for name in names)


def read_metric(input: Any) -> str:
    return read_input(input, "metric", METRIC_TOPN, str)


def read_dto_ranking(input: Any) -> str:
    return read_input(input, "dto_ranking_column", DEFAULT_DTO_RANKING_COLUMN, str)


def read_top_n(input: Any) -> int:
    return read_input(input, "top_n", DEFAULT_TOP_N, int)


def read_full_overlap(input: Any) -> bool:
    return read_input(input, "require_intersecting_floor", True, bool)


def read_common_regulators_only(input: Any) -> bool:
    return read_input(input, "cm_common_regulators_only", False, bool)


def read_preset_name(input: Any) -> str:
    return read_input(
        input, "responsiveness_preset", DEFAULT_RESPONSIVENESS_PRESET, str
    )


def read_preset(input: Any) -> dict[str, tuple[float, float]]:
    return DEFAULT_RESPONSIVENESS_PRESETS.get(
        read_preset_name(input),
        DEFAULT_RESPONSIVENESS_PRESETS[DEFAULT_RESPONSIVENESS_PRESET],
    )


def cell_style(val: float) -> str:
    """HSL green scale: 0% -> white, 100% -> full green."""
    clamped = max(0.0, min(100.0, val))
    lightness = 100 - clamped * 0.5
    return (
        f"background-color: hsl(120, 60%, {lightness:.0f}%);"
        " padding: 6px 10px; text-align: right;"
    )


@dataclass
class ComparisonContext:
    """
    Everything a tab needs besides its own inputs.

    :param conn: Read-only DuckDB connection to the materialized database.
    :param logger: Application logger.
    :param active_binding_datasets: Reactive calc of active primary binding db names.
    :param active_perturbation_datasets: Reactive calc of active perturbation db names.
    :param dataset_filters: Reactive per-dataset sample filter specs.
    :param db_schema_version: The database's stamped schema version.
    :param registry_df: ``dataset_registry`` rows, read once.
    :param display_names: ``db_name -> display_name``.
    :param binding_index: Registry-derived promoter set x method index.
    :param reg_labels: ``locus tag -> "SYMBOL (tag)"`` (or the tag alone).
    :param all_binding_dbs: Every binding db_name in the registry.
    :param all_perturbation_dbs: Every perturbation db_name in the registry.

    """

    conn: duckdb.DuckDBPyConnection
    logger: Logger
    active_binding_datasets: reactive.Calc_[list[str]]
    active_perturbation_datasets: reactive.Calc_[list[str]]
    dataset_filters: reactive.Value[dict[str, Any]]
    db_schema_version: int | None
    registry_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    display_names: dict[str, str] = field(default_factory=dict)
    binding_index: BindingIndex = field(init=False)
    reg_labels: dict[str, str] = field(default_factory=dict)
    all_binding_dbs: list[str] = field(default_factory=list)
    all_perturbation_dbs: list[str] = field(default_factory=list)

    @property
    def dto_available(self) -> bool:
        """
        Whether the DTO metric can be served.

        The ``dto`` and ``sample_regulator`` tables exist in every database built at
        the current schema version, so this is the schema stamp (see
        ``utils.schema_check``).

        """
        return self.db_schema_version == SCHEMA_VERSION


def build_context(
    conn: duckdb.DuckDBPyConnection,
    logger: Logger,
    active_binding_datasets: reactive.Calc_[list[str]],
    active_perturbation_datasets: reactive.Calc_[list[str]],
    dataset_filters: reactive.Value[dict[str, Any]],
    db_schema_version: int | None,
) -> ComparisonContext:
    """
    Read the registry and labels the tabs share, once per session.

    :returns: The populated context.

    """
    ctx = ComparisonContext(
        conn,
        logger,
        active_binding_datasets,
        active_perturbation_datasets,
        dataset_filters,
        db_schema_version,
    )
    # Pre-load the registry once. `binding_index` decomposes every binding
    # dataset into promoter set x method, replacing the label dicts this module
    # used to hand-maintain alongside the collection YAML.
    ctx.registry_df = conn.execute(
        "SELECT db_name, data_type, display_name, base_label,"
        " primary_db_name, promoter_set_id, binding_method_id"
        " FROM dataset_registry"
    ).df()
    ctx.display_names = dict(
        zip(ctx.registry_df["db_name"], ctx.registry_df["display_name"])
    )
    ctx.binding_index = build_binding_index(ctx.registry_df)

    if not ctx.dto_available:
        logger.warning(
            "comparison: the database's schema version is not the app's; the DTO"
            " metric will be unavailable until it is re-materialized"
        )

    for _, row in get_regulator_display_name(conn).iterrows():
        tag = str(row["regulator_locus_tag"])
        sym = str(row.get("regulator_symbol", ""))
        if sym and sym != "nan" and sym != tag:
            ctx.reg_labels[tag] = f"{sym} ({tag})"
        else:
            ctx.reg_labels[tag] = tag

    ctx.all_binding_dbs = (
        conn.execute("SELECT db_name FROM dataset_registry WHERE data_type = 'binding'")
        .df()["db_name"]
        .tolist()
    )
    ctx.all_perturbation_dbs = (
        conn.execute(
            "SELECT db_name FROM dataset_registry WHERE data_type = 'perturbation'"
        )
        .df()["db_name"]
        .tolist()
    )
    return ctx


__all__ = [
    "BINDING_ORDER_LABELS",
    "ComparisonContext",
    "PRESET_HELP",
    "PROMOTER_SET_ALIAS",
    "PROMOTER_TOOLTIPS",
    "build_context",
    "cell_style",
    "inputs_ready",
    "read_common_regulators_only",
    "read_dto_ranking",
    "read_full_overlap",
    "read_metric",
    "read_preset",
    "read_preset_name",
    "read_top_n",
]
