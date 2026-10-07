"""App-level dataset metadata and DuckDB initialization helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import duckdb
import pandas as pd

logger = logging.getLogger("shiny")

# Metadata fields to suppress from the filter UI, keyed by db_name.
#: Library-size columns carried by every callingcards config. Not experimental
#: conditions, so they do not belong in the filter UI.
_CC_HOP_FIELDS: set[str] = {"total_background_hops", "total_experiment_hops"}

# Use "*" for fields hidden across all datasets; use the db_name key for
# dataset-specific exclusions. The effective hidden set for a given dataset
# is the union of "*" and its own entry.
HIDDEN_FILTER_FIELDS: dict[str, set[str]] = {
    "*": {
        "regulator_locus_tag",
        "regulator_symbol",
        "Regulator locus tag",
        "Regulator symbol",
    },
    # All four callingcards configs share a schema, so they share these. The primary
    # previously spelled them background_total_hops / experiment_total_hops; the
    # yiming config conforms to the variants' total_* order. Only the primary had an
    # entry here, so the variants were exposing these as filter options.
    "callingcards_kang": _CC_HOP_FIELDS,
    "callingcards_mindel": _CC_HOP_FIELDS,
    "callingcards_500bp": _CC_HOP_FIELDS,
    "callingcards_intergenic": _CC_HOP_FIELDS,
    "harbison": {"condition"},
    "chec_m2025": {"condition", "mahendrawada_symbol"},
    "degron": {"env_condition", "timepoint"},
    "rossi": {"antibody", "growth_media"},
    "hackett": {"date", "mechanism", "restriction", "strain"},
    "hu_reimand": {"average_od_of_replicates", "heat_shock"},
    "hughes_overexpression": {"del_passed_qc", "sgd_description"},
    "hughes_knockout": {"oe_passed_qc", "sgd_description"},
}

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
# Add or modify entries here to tune what counts as a "responsive" target.
# Columns used per dataset are defined in perturbation/queries.py::DATASET_COLUMNS.
# NOTE: degron uses the "pvalue" column (raw DESeq2 p-value), NOT padj. If padj
# is preferred, add "padj" to DATASET_COLUMNS["degron"] and update the comment.

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

# Inline perturbation dataset columns so vdb_init.py has no import from the
# perturbation queries module (which would create a circular dependency risk and
# requires the old VirtualDB import chain).
_PERTURBATION_DATASET_COLUMNS: dict[str, tuple[str, str]] = {
    "degron": ("log2FoldChange", "padj"),
    "hughes_overexpression": ("mean_norm_log2fc", ""),
    "hughes_knockout": ("mean_norm_log2fc", ""),
    "kemmeren": ("Madj", "pval"),
    "hackett": ("log2_shrunken_timecourses", ""),
    "hu_reimand": ("effect", "pval"),
}


def get_responsiveness_label(preset_name: str, p_db: str) -> str:
    """
    Generate a human-readable threshold description from the preset and column tables.

    Derives the label directly from :data:`DEFAULT_RESPONSIVENESS_PRESETS` and the
    ``_PERTURBATION_DATASET_COLUMNS`` mapping, so there is a single source of truth
    for threshold values.

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

    cols = _PERTURBATION_DATASET_COLUMNS.get(p_db, ("effect", "pvalue"))
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
# Must be a key in DEFAULT_RESPONSIVENESS_PRESETS.
DEFAULT_RESPONSIVENESS_PRESET: str = "Relaxed"


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

    Holds the column classification derived from the ``dataset_column_metadata``
    table in the materialized DuckDB.

    :param condition_cols: Mapping from db_name to list of column names with
        role ``condition``, excluding hidden fields.
    :param upstream_cols: Mapping from db_name to list of column names with
        role ``upstream``, excluding hidden fields.

    """

    condition_cols: dict[str, list[str]]
    upstream_cols: dict[str, list[str]]


def load_app_datasets(conn: duckdb.DuckDBPyConnection) -> AppDatasets:
    """
    Load AppDatasets from dataset_column_metadata table in the materialized DuckDB.

    :param conn: Open read-only DuckDB connection.
    :returns: AppDatasets with condition_cols and upstream_cols populated.

    """
    df = conn.execute(
        "SELECT db_name, column_name, role FROM dataset_column_metadata"
    ).df()
    condition_cols: dict[str, list[str]] = {}
    upstream_cols: dict[str, list[str]] = {}
    for db_name, grp in df.groupby("db_name"):
        cond = grp[grp["role"] == "condition"]["column_name"].tolist()
        up = grp[grp["role"] == "upstream"]["column_name"].tolist()
        if cond and up:
            condition_cols[str(db_name)] = cond
            upstream_cols[str(db_name)] = up
    return AppDatasets(condition_cols=condition_cols, upstream_cols=upstream_cols)


__all__ = [
    "HIDDEN_FILTER_FIELDS",
    "FIELD_TYPE_OVERRIDES",
    "DEFAULT_DATASET_FILTERS",
    "ResponsivenessPreset",
    "DEFAULT_RESPONSIVENESS_PRESETS",
    "DEFAULT_RESPONSIVENESS_PRESET",
    "get_responsiveness_label",
    "AppDatasets",
    "get_regulator_display_name",
    "load_app_datasets",
]
