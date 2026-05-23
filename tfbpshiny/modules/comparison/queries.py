# flake8: noqa
"""SQL queries for the Comparison (DTO / Top-N by Binding) module."""

from __future__ import annotations

from typing import Any

import pandas as pd
from labretriever import VirtualDB

from tfbpshiny.modules.perturbation.queries import DATASET_COLUMNS

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: callingcards target locus tags excluded from the top-N analysis (matching R)
CC_TARGET_BLACKLIST = ("YOR201C", "YOR202W", "YOR203W", "YCL018W", "YEL021W")

#: Pseudo-value added before -log10 to avoid log(0)
DTO_LOG_PSEUDO = 1e-3

#: Default top-N cutoff
DEFAULT_TOP_N = 25

#: Default effect size threshold (|effect| must exceed this to be "responsive")
DEFAULT_EFFECT_THRESHOLD = 0.0

#: Default p-value threshold (pvalue must be below this to be "responsive")
DEFAULT_PVALUE_THRESHOLD = 0.05

# ---------------------------------------------------------------------------
# DTO query
# ---------------------------------------------------------------------------

_DTO_SQL = """
SELECT
    d.binding_id_source,
    d.perturbation_id_source,
    d.dto_empirical_pvalue,
    d.dto_fdr,
    d.binding_set_size,
    d.perturbation_set_size,
    CAST(d.binding_id_id   AS VARCHAR)    AS binding_sample_id,
    CAST(d.perturbation_id_id AS VARCHAR) AS pert_sample_id,
    COALESCE(CAST(h.time AS VARCHAR), 'standard') AS time
FROM dto_expanded d
LEFT JOIN (
    SELECT DISTINCT sample_id, time FROM hackett_meta WHERE time = 45
) h
    ON  d.perturbation_id_source = 'hackett'
    AND CAST(d.perturbation_id_id AS VARCHAR) = CAST(h.sample_id AS VARCHAR)
LEFT JOIN (
    SELECT DISTINCT sample_id FROM callingcards
) cc
    ON  d.binding_id_source = 'callingcards'
    AND CAST(d.binding_id_id AS VARCHAR) = CAST(cc.sample_id AS VARCHAR)
LEFT JOIN (
    SELECT DISTINCT sample_id FROM harbison WHERE condition = 'YPD'
) harb
    ON  d.binding_id_source = 'harbison'
    AND CAST(d.binding_id_id AS VARCHAR) = CAST(harb.sample_id AS VARCHAR)
WHERE
    d.pr_ranking_column = 'log2fc'
    AND (d.perturbation_id_source != 'hackett'     OR h.sample_id IS NOT NULL)
    AND (d.binding_id_source      != 'callingcards' OR cc.sample_id IS NOT NULL)
    AND (d.binding_id_source      != 'harbison'     OR harb.sample_id IS NOT NULL)
"""


def fetch_dto_data(
    vdb: VirtualDB, sql_only: bool = False
) -> pd.DataFrame | tuple[str, dict]:
    """
    Fetch DTO empirical p-value data from ``dto_expanded``.

    Requires ``hackett_analysis_set`` to be registered first (done by
    :func:`tfbpshiny.utils.vdb_init.initialize_data`).

    :param vdb: VirtualDB instance.
    :param sql_only: If ``True`` return ``(sql, {})`` instead of executing.
    :returns: DataFrame with columns ``binding_id_source``,
        ``perturbation_id_source``, ``dto_empirical_pvalue``, ``dto_fdr``,
        ``binding_set_size``, ``perturbation_set_size``, ``binding_sample_id``,
        ``pert_sample_id``, ``time``.

    """
    if sql_only:
        return _DTO_SQL, {}
    return vdb.query(_DTO_SQL)


# ---------------------------------------------------------------------------
# Top-N responsive ratio query
# ---------------------------------------------------------------------------

_HARBISON_DEDUP_CTE = """
    SELECT
        CAST(sample_id AS VARCHAR) AS binding_sample_id,
        regulator_locus_tag,
        target_locus_tag,
        MIN(pvalue) AS pvalue
    FROM harbison
    WHERE condition = 'YPD'
    GROUP BY sample_id, regulator_locus_tag, target_locus_tag
"""


def _build_where(clauses: list[str]) -> str:
    return ("WHERE " + " AND ".join(clauses)) if clauses else ""


def _build_filter_where(
    filters: dict[str, Any] | None,
    params: dict[str, Any],
    prefix: str,
) -> str:
    """Build a WHERE clause from a dataset_filters spec, populating params in-place."""
    if not filters:
        return ""
    clauses: list[str] = []
    for field, spec in filters.items():
        kind = spec["type"]
        val = spec["value"]
        p = f"{prefix}_{field}".replace(" ", "_")
        if kind == "categorical":
            placeholders = ", ".join(f"$cat_{p}_{i}" for i in range(len(val)))
            clauses.append(f'"{field}" IN ({placeholders})')
            for i, v in enumerate(val):
                params[f"cat_{p}_{i}"] = v
        elif kind == "numeric":
            clauses.append(f'"{field}" BETWEEN $num_{p}_lo AND $num_{p}_hi')
            params[f"num_{p}_lo"] = val[0]
            params[f"num_{p}_hi"] = val[1]
        elif kind == "bool":
            clauses.append(f'"{field}" = $bool_{p}')
            params[f"bool_{p}"] = bool(val)
    return _build_where(clauses)


def _responsive_expr(
    perturbation_view: str,
    effect_threshold: float,
    pvalue_threshold: float,
    param_prefix: str,
    params: dict[str, Any],
) -> str:
    """
    Build a SQL expression that evaluates to 1 (responsive) or 0.

    Uses the effect and pvalue columns from ``DATASET_COLUMNS`` for the given
    perturbation view. If the dataset has no pvalue column only the effect
    threshold is applied.

    :param perturbation_view: Dataset name (key in ``DATASET_COLUMNS``).
    :param effect_threshold: Absolute effect magnitude must exceed this.
    :param pvalue_threshold: P-value must be below this (ignored if no pvalue
        column exists for the dataset).
    :param param_prefix: Namespace prefix for SQL parameter names.
    :param params: Dict populated in-place with threshold parameter values.
    :returns: SQL CASE expression string evaluating to 1 or 0.

    """
    effect_col, pvalue_col = DATASET_COLUMNS.get(perturbation_view, ("", ""))

    eff_key = f"{param_prefix}_eff_thresh"
    pval_key = f"{param_prefix}_pval_thresh"
    params[eff_key] = effect_threshold

    if effect_col and pvalue_col:
        params[pval_key] = pvalue_threshold
        return (
            f"CASE WHEN ABS(p.{effect_col}) > ${eff_key} "
            f"AND p.{pvalue_col} < ${pval_key} THEN 1 ELSE 0 END"
        )
    elif effect_col:
        return f"CASE WHEN ABS(p.{effect_col}) > ${eff_key} THEN 1 ELSE 0 END"
    else:
        # Fall back to pre-computed responsive column
        return "CAST(p.responsive AS INTEGER)"


def topn_responsive_ratio(
    vdb: VirtualDB,
    binding_view: str,
    perturbation_view: str,
    binding_sample_col: str,
    rank_col: str,
    top_n: int = DEFAULT_TOP_N,
    effect_threshold: float = DEFAULT_EFFECT_THRESHOLD,
    pvalue_threshold: float = DEFAULT_PVALUE_THRESHOLD,
    binding_filters: dict[str, Any] | None = None,
    perturbation_filters: dict[str, Any] | None = None,
    rank_asc: bool = True,
    target_blacklist: tuple[str, ...] = (),
    binding_dedup_cte: str = "",
    param_prefix: str = "p",
    sql_only: bool = False,
) -> pd.DataFrame | tuple[str, dict]:
    """
    Compute the top-N-by-binding responsive ratio for one (binding, perturbation) pair.

    Ranks binding targets per binding sample (PARTITION BY binding_sample_id),
    keeps the top ``top_n``, then joins to perturbation data and applies the
    effect/pvalue thresholds to determine responsiveness dynamically.

    :param vdb: VirtualDB instance.
    :param binding_view: View name for binding data.
    :param perturbation_view: View name for perturbation data.
    :param binding_sample_col: Column in binding view for the sample identifier.
    :param rank_col: Column used to rank binding hits.
    :param top_n: Number of top binding targets to keep per binding sample.
    :param effect_threshold: Minimum absolute effect size to count as responsive.
    :param pvalue_threshold: Maximum p-value to count as responsive (ignored if
        the dataset has no p-value column).
    :param binding_filters: dataset_filters spec for the binding dataset.
    :param perturbation_filters: dataset_filters spec for the perturbation dataset.
    :param rank_asc: If ``True``, lower values of ``rank_col`` rank better.
    :param target_blacklist: Locus tags to exclude from binding targets.
    :param binding_dedup_cte: Optional CTE body SQL to replace the default
        binding SELECT (used for Harbison dedup).
    :param param_prefix: Namespace prefix for SQL parameters to avoid collisions.
    :param sql_only: If ``True`` return ``(sql, params)`` instead of executing.

    """
    params: dict[str, Any] = {}
    rank_dir = "ASC" if rank_asc else "DESC"

    # binding CTE
    if binding_dedup_cte:
        binding_cte_body = binding_dedup_cte
    else:
        b_filter_where = _build_filter_where(
            binding_filters, params, prefix=f"{param_prefix}_b"
        )
        blacklist_clauses = []
        if b_filter_where:
            blacklist_clauses.append(b_filter_where.lstrip("WHERE "))
        if target_blacklist:
            ph = ", ".join(
                f"$bl_{param_prefix}_{i}" for i in range(len(target_blacklist))
            )
            blacklist_clauses.append(f"target_locus_tag NOT IN ({ph})")
            for i, tag in enumerate(target_blacklist):
                params[f"bl_{param_prefix}_{i}"] = tag
        binding_extra = _build_where(blacklist_clauses)
        binding_cte_body = f"""
        SELECT
            CAST({binding_sample_col} AS VARCHAR) AS binding_sample_id,
            regulator_locus_tag,
            target_locus_tag,
            {rank_col}
        FROM {binding_view}
        {binding_extra}
        """

    # perturbation responsive expression
    responsive_expr = _responsive_expr(
        perturbation_view,
        effect_threshold,
        pvalue_threshold,
        param_prefix,
        params,
    )

    # perturbation CTE
    pert_filter_where = _build_filter_where(
        perturbation_filters, params, prefix=f"{param_prefix}_p"
    )

    top_n_key = f"{param_prefix}_top_n"
    params[top_n_key] = top_n

    sql = f"""
    WITH binding AS (
        {binding_cte_body}
    ),
    binding_ranked AS (
        SELECT
            binding_sample_id,
            regulator_locus_tag,
            target_locus_tag,
            {rank_col},
            RANK() OVER (
                PARTITION BY binding_sample_id
                ORDER BY {rank_col} {rank_dir}
            ) AS rnk
        FROM binding
        WHERE regulator_locus_tag != target_locus_tag
    ),
    top_n_binding AS (
        SELECT binding_sample_id, regulator_locus_tag, target_locus_tag
        FROM binding_ranked
        WHERE rnk <= ${top_n_key}
    ),
    perturbation AS (
        SELECT
            CAST(p.sample_id AS VARCHAR) AS perturbation_sample_id,
            p.regulator_locus_tag,
            p.target_locus_tag,
            {responsive_expr} AS is_responsive
        FROM {perturbation_view} p
        {pert_filter_where}
    )
    SELECT
        b.binding_sample_id,
        b.regulator_locus_tag,
        pert.perturbation_sample_id,
        COUNT(*)                                         AS n,
        SUM(pert.is_responsive)::INTEGER                 AS n_responsive,
        SUM(pert.is_responsive)::DOUBLE / COUNT(*)       AS responsive_ratio
    FROM top_n_binding b
    JOIN perturbation pert
        ON  b.regulator_locus_tag = pert.regulator_locus_tag
        AND b.target_locus_tag    = pert.target_locus_tag
    GROUP BY b.binding_sample_id, b.regulator_locus_tag, pert.perturbation_sample_id
    """

    if sql_only:
        return sql, params
    return vdb.query(sql, **params)


# ---------------------------------------------------------------------------
# Source label maps (matching the R code)
# ---------------------------------------------------------------------------

# Promoter-set-aware constants -----------------------------------------------

#: Maps every binding db_name to its base label (Mindel suffix stripped).
#: Primary and Mindel variants of the same dataset share the same base label.
BINDING_BASE_LABEL_MAP: dict[str, str] = {
    "callingcards": "2026 Calling Cards",
    "callingcards_mindel": "2026 Calling Cards",
    "harbison": "2004 ChIP-chip",
    "rossi": "2021 ChIP-exo",
    "rossi_mindel": "2021 ChIP-exo",
    "chec_m2025": "2025 ChEC-seq",
    "chec_m2025_mindel": "2025 ChEC-seq",
}

#: Maps every binding db_name to its promoter-set label ("Kang" or "Mindel").
PROMOTER_SET_MAP: dict[str, str] = {
    db: (
        "Mindel"
        if db in ("callingcards_mindel", "rossi_mindel", "chec_m2025_mindel")
        else "Kang"
    )
    for db in BINDING_BASE_LABEL_MAP
}

BINDING_LABEL_MAP: dict[str, str] = {
    "callingcards": "2026 Calling Cards",
    "harbison": "2004 ChIP-chip",
    "chec_m2025": "2025 ChEC-seq",
    "rossi": "2021 ChIP-exo",
    "chec_m2025_mindel": "2025 ChEC-seq (Mindel)",
    "rossi_mindel": "2021 ChIP-exo (Mindel)",
    "callingcards_mindel": "2026 Calling Cards (Mindel)",
}

#: Maps primary binding db_name to its Mindel-promoter variant db_name.
PROMOTER_VARIANT_PAIRS: dict[str, str] = {
    "rossi": "rossi_mindel",
    "chec_m2025": "chec_m2025_mindel",
    "callingcards": "callingcards_mindel",
}

# ---------------------------------------------------------------------------
# Method Comparison constants
# ---------------------------------------------------------------------------

#: Maps every binding db_name that appears in the Method Comparison tab to its
#: base label; all scoring variants of the same dataset share the same label.
METHOD_BASE_LABEL_MAP: dict[str, str] = {
    "chec_m2025": "2025 ChEC-seq",
    "chec_m2025_peaks": "2025 ChEC-seq",
    "rossi": "2021 ChIP-exo",
    "rossi_mindel": "2021 ChIP-exo",
    "rossi_peaks_kang": "2021 ChIP-exo",
    "rossi_peaks_mindel": "2021 ChIP-exo",
}

#: Human-readable label for each scoring variant in the Method Comparison tab.
SCORING_VARIANT_MAP: dict[str, str] = {
    "chec_m2025": "Re-quantified",
    "chec_m2025_peaks": "Original Peaks",
    "rossi": "Re-quantified (Kang)",
    "rossi_mindel": "Re-quantified (Mindel)",
    "rossi_peaks_kang": "Original Peaks (Kang)",
    "rossi_peaks_mindel": "Original Peaks (Mindel)",
}

#: Maps each primary binding dataset to the peaks variants produced by the
#: original authors' peak-calling pipeline.
PEAKS_VARIANT_MAP: dict[str, list[str]] = {
    "rossi": ["rossi_peaks_kang", "rossi_peaks_mindel"],
    "chec_m2025": ["chec_m2025_peaks"],
}

#: Display order for scoring variants within a subplot.
SCORING_VARIANT_ORDER: list[str] = [
    "Re-quantified",
    "Re-quantified (Kang)",
    "Re-quantified (Mindel)",
    "Original Peaks",
    "Original Peaks (Kang)",
    "Original Peaks (Mindel)",
]

#: Color palette for scoring variants in the Method Comparison tab.
SCORING_VARIANT_COLORS: dict[str, str] = {
    "Re-quantified": "#4DBBD5",
    "Re-quantified (Kang)": "#4DBBD5",
    "Re-quantified (Mindel)": "#00A087",
    "Original Peaks": "#E64B35",
    "Original Peaks (Kang)": "#E64B35",
    "Original Peaks (Mindel)": "#F39B7F",
}

PERTURBATION_LABEL_MAP: dict[str, str] = {
    "hackett": "2020 Overexpression",
    "hughes_overexpression": "2006 Overexpression",
    "hughes_knockout": "2006 TFKO",
    "hu_reimand": "2007 TFKO",
    "kemmeren": "2014 TFKO",
    "degron": "2025 Degron",
}

# ---------------------------------------------------------------------------
# Per-source configuration for top-N analysis
# ---------------------------------------------------------------------------

#: Per-binding-source kwargs passed to topn_responsive_ratio (excluding filters).
BINDING_CONFIGS: dict[str, dict] = {
    "callingcards": dict(
        binding_sample_col="sample_id",
        rank_col="poisson_pval",
        rank_asc=True,
        target_blacklist=CC_TARGET_BLACKLIST,
    ),
    "callingcards_mindel": dict(
        binding_sample_col="sample_id",
        rank_col="poisson_pval",
        rank_asc=True,
        target_blacklist=CC_TARGET_BLACKLIST,
    ),
    "harbison": dict(
        binding_sample_col="sample_id",
        rank_col="pvalue",
        rank_asc=True,
        binding_dedup_cte=_HARBISON_DEDUP_CTE,
    ),
    "chec_m2025": dict(
        binding_sample_col="sample_id",
        rank_col="enrichment",
        rank_asc=False,
    ),
    "rossi": dict(
        binding_sample_col="sample_id",
        rank_col="enrichment",
        rank_asc=False,
    ),
    "rossi_mindel": dict(
        binding_sample_col="sample_id",
        rank_col="enrichment",
        rank_asc=False,
    ),
    "chec_m2025_mindel": dict(
        binding_sample_col="sample_id",
        rank_col="enrichment",
        rank_asc=False,
    ),
    "chec_m2025_peaks": dict(
        binding_sample_col="sample_id",
        rank_col="peak_score",
        rank_asc=False,
    ),
    "rossi_peaks_kang": dict(
        binding_sample_col="sample_id",
        rank_col="score",
        rank_asc=False,
    ),
    "rossi_peaks_mindel": dict(
        binding_sample_col="sample_id",
        rank_col="score",
        rank_asc=False,
    ),
}

#: Per-perturbation-source kwargs passed to topn_responsive_ratio (excluding filters).
PERTURBATION_CONFIGS: dict[str, dict] = {
    "hackett": {},
    "hughes_overexpression": {},
    "hughes_knockout": {},
    "hu_reimand": {},
    "kemmeren": {},
    "degron": {},
}


def topn_all_pairs_sql(
    vdb: VirtualDB,
    pairs: list[tuple[str, str]],
    filters: dict[str, Any],
    top_n: int,
    effect_threshold: float,
    pvalue_threshold: float,
) -> pd.DataFrame:
    """
    Compute top-N responsive ratio for all (binding, perturbation) pairs in one query.

    Builds a UNION ALL of per-pair subqueries and executes as a single
    ``vdb.query()`` call. Each pair is prefixed with ``bp{i}_`` to prevent
    parameter name collisions.

    :param vdb: VirtualDB instance.
    :param pairs: List of ``(binding_db, perturbation_db)`` tuples.
    :param filters: Active filter dict keyed by dataset name.
    :param top_n: Number of top binding targets per binding sample.
    :param effect_threshold: Minimum absolute effect size to count as responsive.
    :param pvalue_threshold: Maximum p-value to count as responsive.
    :returns: DataFrame with all columns returned by ``topn_responsive_ratio``
        plus ``pair_key`` (``"{b_db}__{p_db}"``).

    """
    if not pairs:
        return pd.DataFrame()

    parts: list[str] = []
    all_params: dict[str, Any] = {}

    for i, (b_db, p_db) in enumerate(pairs):
        b_cfg = BINDING_CONFIGS.get(b_db)
        p_cfg = PERTURBATION_CONFIGS.get(p_db)
        if b_cfg is None or p_cfg is None:
            continue
        pair_sql, pair_params = topn_responsive_ratio(
            vdb=vdb,
            binding_view=b_db,
            perturbation_view=p_db,
            top_n=top_n,
            effect_threshold=effect_threshold,
            pvalue_threshold=pvalue_threshold,
            binding_filters=filters.get(b_db),
            perturbation_filters=filters.get(p_db),
            param_prefix=f"bp{i}",
            sql_only=True,
            **b_cfg,
            **p_cfg,
        )
        assert isinstance(pair_sql, str) and isinstance(pair_params, dict)
        all_params.update(pair_params)
        pair_key = f"{b_db}__{p_db}"
        parts.append(f"SELECT *, '{pair_key}' AS pair_key FROM ({pair_sql.strip()})")

    if not parts:
        return pd.DataFrame()

    sql = "\nUNION ALL\n".join(parts)
    return vdb.query(sql, **all_params)
