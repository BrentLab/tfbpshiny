"""One-time application initialization for VirtualDB and dataset metadata."""

from __future__ import annotations

from dataclasses import dataclass

from labretriever import VirtualDB

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


def initialize_data(
    virtualdb_config: str,
    hf_token: str | None = None,
) -> tuple[VirtualDB, AppDatasets]:
    """
    Construct the VirtualDB, run one-time setup, and compute app-level dataset metadata.

    :param virtualdb_config: Path to the VirtualDB YAML config file.
    :param hf_token: Optional HuggingFace token for private repo access.
    :returns: Tuple of ``(vdb, app_datasets)``.
    :rtype: tuple[VirtualDB, AppDatasets]

    """
    from tfbpshiny.modules.comparison.queries import ensure_hackett_analysis_set

    vdb = VirtualDB(virtualdb_config, token=hf_token)
    ensure_hackett_analysis_set(vdb)

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

    return vdb, AppDatasets(condition_cols=condition_cols, upstream_cols=upstream_cols)


__all__ = ["HIDDEN_FILTER_FIELDS", "AppDatasets", "initialize_data"]
