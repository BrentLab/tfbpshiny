"""App-level dataset metadata and DuckDB initialization helpers."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

import duckdb
import pandas as pd
from labretriever import ColumnMeta

from tfbpshiny.datasets import DEFAULT_PRESET, PERTURBATION_DATASET_COLUMNS

logger = logging.getLogger("shiny")

# Metadata fields to suppress from the filter UI, keyed by db_name.
#: Library-size columns carried by every callingcards config. Not experimental
#: conditions, so they do not belong in the filter UI.
_CC_HOP_FIELDS: set[str] = {"total_background_hops", "total_experiment_hops"}

# Metadata columns kept out of the filter UI: identifiers, library sizes, and the raw
# source column behind a standardised alias (e.g. ``condition``, which the collection
# config exposes as ``Experimental condition``). Use "*" for fields hidden across all
# datasets; use a *primary* db_name for dataset-specific exclusions, which its
# promoter-set and peak-calling variants inherit. :func:`hidden_filter_fields` resolves
# the effective set.
HIDDEN_FILTER_FIELDS: dict[str, set[str]] = {
    "*": {
        "regulator_locus_tag",
        "regulator_symbol",
        "Regulator locus tag",
        "Regulator symbol",
    },
    "callingcards_500bp": _CC_HOP_FIELDS,
    "harbison": {"condition"},
    # ``mahendrawada_symbol`` is the symbol as printed in the paper; regulators are
    # identified by ``regulator_symbol`` and ``regulator_locus_tag``.
    "chec_m2025_500bp": {"condition", "mahendrawada_symbol"},
    "degron": {"env_condition", "timepoint"},
    "rossi_500bp": {"antibody", "growth_media"},
    "hackett": {"date", "mechanism", "restriction", "strain"},
    "hu_reimand": {"average_od_of_replicates", "heat_shock"},
    "hughes_overexpression": {"del_passed_qc", "sgd_description"},
    "hughes_knockout": {"oe_passed_qc", "sgd_description"},
}


def hidden_filter_fields(db_name: str, primary_db_name: str | None = None) -> set[str]:
    """
    Metadata columns kept out of a dataset's filter UI.

    :param db_name: Dataset name.
    :param primary_db_name: The primary ``db_name`` when ``db_name`` is a variant of
        one; ``None`` or ``db_name`` itself for a primary.
    :returns: The union of the ``"*"`` entry, the primary's entry and the dataset's
        own entry of :data:`HIDDEN_FILTER_FIELDS`.

    """
    return (
        HIDDEN_FILTER_FIELDS.get("*", set())
        | HIDDEN_FILTER_FIELDS.get(primary_db_name or db_name, set())
        | HIDDEN_FILTER_FIELDS.get(db_name, set())
    )


# Which datasets are primary and which are on by default is recorded in the
# materialized ``dataset_registry`` (``is_primary`` / ``is_active_default``), which the
# selection tab reads directly; it is not restated here.

# Default filter state applied on first load. The structure is identical to the
# dict stored in the ``dataset_filters`` reactive value so it can be used as
# the initial value with no additional handling.
DEFAULT_DATASET_FILTERS: dict[str, dict] = {
    "harbison": {
        "Experimental condition": {"type": "categorical", "value": ["YPD"]},
    },
    # Filters are keyed by the *primary* dataset the selection tab shows; every variant
    # (other promoter sets, peak calls) inherits its primary's -- see
    # ``utils.corr_query.expand_filters_to_variants``. Unfiltered, Rossi has 792 samples
    # for 777 regulators (heat-shock repeats) and ChEC-seq 197 for 178 (non-standard
    # conditions such as galactose or the activation-domain mutants); filtered they are
    # one sample per regulator.
    "rossi_500bp": {
        "treatment": {"type": "categorical", "value": ["Normal"]},
    },
    "chec_m2025_500bp": {
        "Experimental condition": {"type": "categorical", "value": ["standard"]},
    },
    "hackett": {
        "time": {"type": "categorical", "value": [45.0]},
    },
}

# Column-type overrides for fields whose DuckDB type does not match how they
# should be filtered in the UI. Keys are ``(db_name, field_name)`` tuples;
# use an empty string as db_name to apply the override to every dataset that
# has the field. Values are ``("categorical", level_dtype)`` where
# ``level_dtype`` is ``"numeric"`` (sort levels numerically) or ``"string"``
# (sort lexicographically).
FIELD_TYPE_OVERRIDES: dict[tuple[str, str], tuple[str, str]] = {
    ("hackett", "time"): ("categorical", "numeric"),
    ("", "temperature_celsius"): ("categorical", "string"),
}

# Type alias for one responsiveness preset used by the Comparison module.
# Keys are db_names; use "*" as a fallback for datasets not explicitly listed.
# Values are (effect_threshold, pvalue_threshold) tuples.
ResponsivenessPreset = dict[str, tuple[float, float]]

# Named presets for per-dataset responsiveness definitions in the Comparison module.
# Add or modify entries here to tune what counts as a "responsive" target. The keys
# must be exactly ``tfbpshiny.datasets.PRESET_NAMES``; the columns each threshold
# applies to are ``tfbpshiny.datasets.PERTURBATION_DATASET_COLUMNS`` (degron is
# thresholded on ``padj``).

# provide two options: author settings (more stringent) and relaxed thresholds
# (chose reasonable, with result)
DEFAULT_RESPONSIVENESS_PRESETS: dict[str, ResponsivenessPreset] = {
    "Stringent": {
        "*": (1.0, 0.05),
        "degron": (0.38, 0.1),  # |fold change| > log2(1.3) and padj < 0.1
        # hackett/hughes have no pvalue column; materialized with pvalue_threshold=0.05.
        # Use effect_threshold only to distinguish Stringent from Relaxed.
        "hackett": (0.1, 0.05),
        "kemmeren": (0.77, 0.05),  # |Madj| > log2(1.7) and pval < 0.05
        "hu_reimand": (0.0, 0.05),  # pval < 0.05 (no effect threshold)
        "hughes_overexpression": (1.0, 0.05),
        "hughes_knockout": (1.0, 0.05),
    },
    "Relaxed": {
        "*": (0.0, 0.05),
        # hackett/hughes have no pvalue column; omit override so they use "*" default.
    },
}


def get_responsiveness_label(preset_name: str, p_db: str) -> str:
    """
    Generate a human-readable threshold description from the preset and column tables.

    Derives the label directly from :data:`DEFAULT_RESPONSIVENESS_PRESETS` and
    :data:`tfbpshiny.datasets.PERTURBATION_DATASET_COLUMNS`, so there is a single
    source of truth for threshold values.

    :param preset_name: Active preset name (key in
        :data:`DEFAULT_RESPONSIVENESS_PRESETS`).
    :param p_db: Perturbation dataset db_name.
    :returns: Threshold description string, or empty string if preset unknown.
    :rtype: str

    """
    preset = DEFAULT_RESPONSIVENESS_PRESETS.get(preset_name)
    if preset is None:
        return ""

    thresholds = preset.get(p_db, preset.get("*", (0.0, 0.05)))
    effect_thresh, pval_thresh = thresholds

    cols = PERTURBATION_DATASET_COLUMNS.get(p_db, ("effect", "pvalue"))
    effect_col = cols[0] if cols[0] else "effect"
    pval_col = cols[1] if len(cols) > 1 else ""

    parts: list[str] = []
    parts.append(f"|{effect_col}| > {effect_thresh}")
    if pval_col and pval_thresh < 1.0:
        parts.append(f"{pval_col} < {pval_thresh}")
    else:
        parts.append("no p-value threshold")

    return ", ".join(parts)


# The default preset shown in the Comparison module sidebar.
DEFAULT_RESPONSIVENESS_PRESET: str = DEFAULT_PRESET

assert DEFAULT_RESPONSIVENESS_PRESET in DEFAULT_RESPONSIVENESS_PRESETS


def get_regulator_display_name(
    conn: duckdb.DuckDBPyConnection,
    locus_tags: list[str] | None = None,
) -> pd.DataFrame:
    """
    Return a DataFrame of regulator display names from the pre-built lookup table.

    :param conn: Open read-only DuckDB connection to the materialized database.
    :param locus_tags: Optional list of locus tags to restrict results. When
        ``None`` all regulators in the table are returned.
    :returns: DataFrame with columns ``regulator_locus_tag``, ``regulator_symbol``,
        and ``display_name``.
    :rtype: pandas.DataFrame

    """
    if locus_tags is None:
        return conn.execute("SELECT * FROM regulator_display_names").df()
    return conn.execute(
        "SELECT * FROM regulator_display_names WHERE regulator_locus_tag = ANY(?)",
        [locus_tags],
    ).df()


@dataclass
class AppDatasets:
    """
    App-level dataset metadata derived at startup.

    Holds the column classification and labels from the ``dataset_column_metadata``
    table in the materialized DuckDB.

    :param condition_cols: Mapping from db_name to list of column names with
        role ``condition``, excluding hidden fields.
    :param upstream_cols: Mapping from db_name to list of column names with
        role ``upstream``, excluding hidden fields.
    :param column_meta: ``db_name -> column -> ColumnMeta`` for every filterable
        column: its description, labretriever role and per-level definitions. The
        filter modal labels its controls from these.

    """

    condition_cols: dict[str, list[str]]
    upstream_cols: dict[str, list[str]]
    column_meta: dict[str, dict[str, ColumnMeta]] = field(default_factory=dict)


def promoter_set_labels(conn: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """
    Display label for every promoter set, from the ``promoter_sets`` registry table.

    :param conn: Open read-only DuckDB connection to the materialized database.
    :returns: ``promoter_set_id`` -> ``display_name``, e.g.
        ``"intergenic" -> "Intergenic"``.

    """
    rows = conn.execute(
        "SELECT promoter_set_id, display_name FROM promoter_sets"
    ).fetchall()
    return {str(k): str(v) for k, v in rows}


def binding_method_labels(conn: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """
    Display label for every binding method, from the ``binding_methods`` table.

    :param conn: Open read-only DuckDB connection to the materialized database.
    :returns: ``binding_method_id`` -> ``display_name``.

    """
    rows = conn.execute(
        "SELECT binding_method_id, display_name FROM binding_methods"
    ).fetchall()
    return {str(k): str(v) for k, v in rows}


def promoter_set_info(
    conn: duckdb.DuckDBPyConnection,
) -> dict[str, dict[str, str | None]]:
    """
    Everything the UI shows about each promoter set, from ``promoter_sets``.

    :param conn: Open read-only DuckDB connection to the materialized database.
    :returns: ``promoter_set_id -> {display_name, description, color, reference}``.

    """
    rows = conn.execute(
        "SELECT promoter_set_id, display_name, description, color, reference"
        " FROM promoter_sets"
    ).fetchall()
    return {
        str(r[0]): {
            "display_name": r[1],
            "description": r[2],
            "color": r[3],
            "reference": r[4],
        }
        for r in rows
    }


def binding_method_colors(conn: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """
    Series colour of each binding method, from ``binding_methods``.

    :param conn: Open read-only DuckDB connection to the materialized database.
    :returns: ``binding_method_id -> color``.

    """
    rows = conn.execute(
        "SELECT binding_method_id, color FROM binding_methods WHERE color IS NOT NULL"
    ).fetchall()
    return {str(k): str(v) for k, v in rows}


def dataset_colors(conn: duckdb.DuckDBPyConnection, data_type: str) -> dict[str, str]:
    """
    Series colour of each experiment of one data type, keyed by ``base_label``.

    Colours are declared on primaries; every variant of a primary shares its
    ``base_label``, so one entry per experiment covers them all.

    :param conn: Open read-only DuckDB connection to the materialized database.
    :param data_type: ``'binding'`` or ``'perturbation'``.
    :returns: ``base_label -> color``.

    """
    rows = conn.execute(
        "SELECT base_label, color FROM dataset_registry"
        " WHERE data_type = ? AND is_primary AND color IS NOT NULL",
        [data_type],
    ).fetchall()
    return {str(k): str(v) for k, v in rows}


def peak_calling_notes(conn: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """
    How each assay's peak calls were made, keyed by its primary ``db_name``.

    :param conn: Open read-only DuckDB connection to the materialized database.
    :returns: ``db_name -> note`` for primaries that have one.

    """
    rows = conn.execute(
        "SELECT db_name, peak_calling_note FROM dataset_registry"
        " WHERE peak_calling_note IS NOT NULL"
    ).fetchall()
    return {str(k): str(v) for k, v in rows}


def load_app_datasets(conn: duckdb.DuckDBPyConnection) -> AppDatasets:
    """
    Load AppDatasets from dataset_column_metadata table in the materialized DuckDB.

    :param conn: Open read-only DuckDB connection.
    :returns: AppDatasets with condition_cols, upstream_cols and column_meta populated.

    """
    df = conn.execute(
        "SELECT db_name, column_name, role, description, level_definitions"
        " FROM dataset_column_metadata"
    ).df()
    column_meta: dict[str, dict[str, ColumnMeta]] = {}
    for row in df.itertuples(index=False):
        levels = row.level_definitions
        column_meta.setdefault(str(row.db_name), {})[str(row.column_name)] = ColumnMeta(
            description=row.description if pd.notna(row.description) else None,
            # The materializer only marks a column 'condition' when labretriever
            # gave it the experimental_condition role and level definitions.
            role="experimental_condition" if row.role == "condition" else None,
            level_definitions=(
                {str(k): str(v) for k, v in json.loads(levels).items()}
                if isinstance(levels, str)
                else None
            ),
        )
    condition_cols: dict[str, list[str]] = {}
    upstream_cols: dict[str, list[str]] = {}
    for db_name, grp in df.groupby("db_name"):
        cond = grp[grp["role"] == "condition"]["column_name"].tolist()
        up = grp[grp["role"] == "upstream"]["column_name"].tolist()
        if cond and up:
            condition_cols[str(db_name)] = cond
            upstream_cols[str(db_name)] = up
    return AppDatasets(
        condition_cols=condition_cols,
        upstream_cols=upstream_cols,
        column_meta=column_meta,
    )


__all__ = [
    "HIDDEN_FILTER_FIELDS",
    "hidden_filter_fields",
    "FIELD_TYPE_OVERRIDES",
    "DEFAULT_DATASET_FILTERS",
    "ResponsivenessPreset",
    "DEFAULT_RESPONSIVENESS_PRESETS",
    "DEFAULT_RESPONSIVENESS_PRESET",
    "get_responsiveness_label",
    "AppDatasets",
    "binding_method_colors",
    "binding_method_labels",
    "dataset_colors",
    "get_regulator_display_name",
    "load_app_datasets",
    "peak_calling_notes",
    "promoter_set_info",
    "promoter_set_labels",
]
