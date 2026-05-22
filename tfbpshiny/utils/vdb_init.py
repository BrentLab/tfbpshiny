"""One-time application initialization for VirtualDB and dataset metadata."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import pandas as pd
from labretriever import VirtualDB
from labretriever.constants import get_cache_dir
from labretriever.models import MetadataConfig

logger = logging.getLogger("shiny")

# Metadata fields to suppress from the filter UI, keyed by db_name.
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
    "callingcards": {"background_total_hops", "experiment_total_hops"},
    "harbison": {"condition"},
    "chec_m2025": {"condition", "mahendrawada_symbol"},
    "degron": {"env_condition", "timepoint"},
    "rossi": {"antibody", "growth_media"},
    "hackett": {"date", "mechanism", "restriction", "strain"},
    "hu_reimand": {"average_od_of_replicates", "heat_shock"},
    "hughes_overexpression": {"del_passed_qc", "sgd_description"},
    "hughes_knockout": {"oe_passed_qc", "sgd_description"},
}

# The canonical db_name for each underlying dataset. When multiple db_names exist for
# the same experiment called against different promoter sets (e.g. rossi vs
# rossi_mindel), only the entry in this set is shown in the dataset selector. Alternate
# promoter variants remain registered in VirtualDB and are accessible to analysis
# modules once a promoter selector is wired up.
PRIMARY_DATASETS: frozenset[str] = frozenset(
    {
        "callingcards",
        "harbison",
        "rossi",
        "chec_m2025",
        "hackett",
        "hu_reimand",
        "hughes_overexpression",
        "hughes_knockout",
        "kemmeren",
        "degron",
    }
)

# Datasets whose toggles are on by default. A superset of DEFAULT_DATASET_FILTERS
# — datasets with no preset conditions are listed here but not in the filter dict.
DEFAULT_ACTIVE_DATASETS: frozenset[str] = frozenset(
    {
        "harbison",
        "rossi",
        "chec_m2025",
        "hackett",
        "callingcards",
        "kemmeren",
        "degron",
    }
)

# Default filter state applied on first load. The structure is identical to the
# dict stored in the ``dataset_filters`` reactive value so it can be used as
# the initial value with no additional handling.
DEFAULT_DATASET_FILTERS: dict[str, dict] = {
    "harbison": {
        "condition": {"type": "categorical", "value": ["YPD"]},
    },
    "rossi": {
        "treatment": {"type": "categorical", "value": ["Normal"]},
    },
    "chec_m2025": {
        "Experimental condition": {"type": "categorical", "value": ["standard"]},
    },
    "hackett": {
        "time": {"type": "numeric", "value": [45.0, 45.0]},
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


_REGULATOR_DISPLAY_NAME_TABLE = "regulator_display_names"

_BUILD_REGULATOR_DISPLAY_NAMES_SQL = """
CREATE OR REPLACE TABLE {table} AS
SELECT
    regulator_locus_tag,
    FIRST(regulator_symbol) AS regulator_symbol,
    CASE
        WHEN FIRST(regulator_symbol) IS NOT NULL
             AND FIRST(regulator_symbol) != ''
             AND FIRST(regulator_symbol) != FIRST(regulator_locus_tag)
        THEN FIRST(regulator_symbol) || ' (' || regulator_locus_tag || ')'
        ELSE regulator_locus_tag
    END AS display_name
FROM ({union_sql}) __all
GROUP BY regulator_locus_tag
ORDER BY regulator_locus_tag
"""


def _build_regulator_display_names(vdb: VirtualDB) -> None:
    """
    Build the ``regulator_display_names`` DuckDB table from all dataset meta views.

    Queries each ``{db_name}_meta`` view for distinct ``(regulator_locus_tag,
    regulator_symbol)`` rows, unions them, and stores the result as a persistent
    in-memory table.  The ``display_name`` column is ``"SYMBOL (LOCUS_TAG)"`` when a
    non-empty symbol different from the tag is present; otherwise it equals the tag.

    :param vdb: The application VirtualDB instance.

    """
    db_names = [
        db
        for db in vdb.get_datasets()
        if "regulator_locus_tag" in vdb.get_fields(f"{db}_meta")
    ]
    if not db_names:
        return
    union_sql = " UNION ALL ".join(
        f"SELECT DISTINCT regulator_locus_tag, regulator_symbol FROM {db}_meta"
        for db in db_names
    )
    sql = _BUILD_REGULATOR_DISPLAY_NAMES_SQL.format(
        table=_REGULATOR_DISPLAY_NAME_TABLE,
        union_sql=union_sql,
    )
    vdb._conn.execute(sql)


def get_regulator_display_name(
    vdb: VirtualDB,
    locus_tags: list[str] | None = None,
) -> pd.DataFrame:
    """
    Return a DataFrame of regulator display names from the pre-built lookup table.

    :param vdb: The application VirtualDB instance.
    :param locus_tags: Optional list of locus tags to restrict results. When
        ``None`` all regulators in the table are returned.
    :returns: DataFrame with columns ``regulator_locus_tag``, ``regulator_symbol``,
        and ``display_name``.
    :rtype: pandas.DataFrame

    """
    if locus_tags is None:
        return vdb._conn.execute(f"SELECT * FROM {_REGULATOR_DISPLAY_NAME_TABLE}").df()
    return vdb._conn.execute(
        f"SELECT * FROM {_REGULATOR_DISPLAY_NAME_TABLE} "
        f"WHERE regulator_locus_tag = ANY(?)",
        [locus_tags],
    ).df()


@dataclass
class AppDatasets:
    """
    App-level dataset metadata derived at startup.

    Holds the column classification that requires :data:`HIDDEN_FILTER_FIELDS`
    and cannot be produced by VirtualDB alone.

    :param condition_cols: Mapping from db_name to list of column names with
        role ``experimental_condition`` and non-None ``level_definitions``,
        excluding hidden fields.
    :param upstream_cols: Mapping from db_name to list of non-condition
        categorical columns that drive the cascade filter, excluding hidden
        fields, ``sample_id``, and identifier-role columns.

    """

    condition_cols: dict[str, list[str]]
    upstream_cols: dict[str, list[str]]


def check_local_cache(virtualdb_config: str) -> list[str]:
    """
    Return a list of repo IDs from the config whose HuggingFace snapshot cache is
    absent.

    Checks for ``{cache_dir}/datasets--{owner}--{repo}/snapshots/`` with at least one
    entry. Respects ``HF_CACHE_DIR`` (set via ``--cache-dir`` CLI flag) so that a
    bundled cache directory is correctly detected. An empty list means all repos are
    cached and ``local_files_only=True`` is safe to use.

    :param virtualdb_config: Path to the VirtualDB YAML config file.
    :returns: List of uncached HuggingFace repo IDs (empty when all are cached).
    :rtype: list[str]

    """
    config = MetadataConfig.from_yaml(virtualdb_config)
    hub_cache = get_cache_dir()
    missing: list[str] = []
    for repo_id, repo_cfg in config.repositories.items():
        if repo_cfg.genome_resources is not None and not repo_cfg.dataset:
            continue  # genome-resource-only repo — nothing to download from HuggingFace
        # HF cache path: datasets--{owner}--{repo_name}
        cache_dir = hub_cache / ("datasets--" + repo_id.replace("/", "--"))
        snapshots = cache_dir / "snapshots"
        if not snapshots.exists() or not any(snapshots.iterdir()):
            missing.append(repo_id)
    return missing


def initialize_data(
    virtualdb_config: str,
    hf_token: str | None = None,
    local_files_only: bool = True,
) -> tuple[VirtualDB, AppDatasets]:
    """
    Construct the VirtualDB, run one-time setup, and compute app-level dataset metadata.

    :param virtualdb_config: Path to the VirtualDB YAML config file.
    :param hf_token: Optional HuggingFace token for private repo access.
    :param local_files_only: Passed to ``VirtualDB``; skips HuggingFace network checks
        and uses only locally cached files. Eliminates 11 sequential ``repo_info`` HTTP
        round-trips on every startup. Defaults to ``True``; pass ``False`` only when
        populating the cache for the first time (``tfbpshiny initialize``).
    :returns: Tuple of ``(vdb, app_datasets)``.
    :rtype: tuple[VirtualDB, AppDatasets]

    """
    _t0 = time.monotonic()

    t = time.monotonic()
    vdb = VirtualDB(virtualdb_config, token=hf_token, local_files_only=local_files_only)
    logger.debug(
        "initialize_data: VirtualDB() completed in %.3fs", time.monotonic() - t
    )

    t = time.monotonic()
    _build_regulator_display_names(vdb)
    logger.debug(
        "initialize_data: _build_regulator_display_names completed in %.3fs",
        time.monotonic() - t,
    )

    t = time.monotonic()
    condition_cols: dict[str, list[str]] = {}
    upstream_cols: dict[str, list[str]] = {}
    hidden_global = HIDDEN_FILTER_FIELDS.get("*", set())

    for db_name in vdb.get_datasets():
        db_meta = vdb.get_column_metadata(db_name) or {}
        hidden = hidden_global | HIDDEN_FILTER_FIELDS.get(db_name, set())

        cond = [
            col
            for col, m in db_meta.items()
            if m.role == "experimental_condition"
            and m.level_definitions is not None
            and col not in hidden
        ]
        upstream = [
            col
            for col, m in db_meta.items()
            if col not in cond
            and col not in hidden
            and col != "sample_id"
            and m.role not in ("regulator_identifier", "target_identifier")
            and m.level_definitions is None
        ]
        if cond and upstream:
            condition_cols[db_name] = cond
            upstream_cols[db_name] = upstream
    logger.debug(
        "initialize_data: column metadata classification completed in %.3fs",
        time.monotonic() - t,
    )

    logger.debug("initialize_data: total %.3fs", time.monotonic() - _t0)
    return vdb, AppDatasets(condition_cols=condition_cols, upstream_cols=upstream_cols)


__all__ = [
    "HIDDEN_FILTER_FIELDS",
    "FIELD_TYPE_OVERRIDES",
    "PRIMARY_DATASETS",
    "DEFAULT_ACTIVE_DATASETS",
    "DEFAULT_DATASET_FILTERS",
    "AppDatasets",
    "check_local_cache",
    "get_regulator_display_name",
    "initialize_data",
]
