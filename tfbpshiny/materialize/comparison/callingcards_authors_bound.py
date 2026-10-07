"""
Calling Cards' authors'-threshold "bound" set, for figure 3 (authors' binding
thresholds).

Calling Cards has no separate authors'-peak-call dataset the way Rossi/Mahendrawada do
(``rossi_peaks``/``chec_m2025_peaks`` are literal peak tables materialize can keep
every row of via `topn.py`'s ``TOP_N_ALL``/``PEAK_BINDING_DATASETS``) -- its raw
per-target rows carry a Poisson p-value for every gene, and "bound" only becomes
well-defined once a threshold is chosen. This module applies one, writing rows
directly into the existing ``topn_results`` table at the same ``TOP_N_ALL`` sentinel
those two datasets use, so ``modules/figures/queries.py::fetch_authors_bound`` can
read Calling Cards exactly the way it reads them -- no query changes needed there,
only adding ``"callingcards_500bp"`` to the caller's dataset list.

Deliberately self-contained rather than threaded through ``topn.py``'s shared
``BINDING_TOPN_CONFIGS``/staged-SQL machinery: that machinery applies one binding CTE
uniformly across every ``top_n`` value for a dataset, but this needs *different*
binding rows for the ``TOP_N_ALL`` pass (threshold-filtered) than for the ordinary
ranked cutoffs (unfiltered, ranked by ``poisson_pval`` -- unchanged by this module).
Forcing that distinction through the shared path would need a per-``top_n`` override
parameter nothing else needs.

"""

from __future__ import annotations

import math
from typing import Any

from tfbpshiny.materialize.comparison.topn import (
    CC_TARGET_BLACKLIST,
    TOP_N_ALL,
    responsive_expr,
)
from tfbpshiny.materialize.rounding import DEFAULT_FLOAT_DECIMALS, round_expr

#: Binding dataset this applies to -- the primary 500bp Calling Cards variant, matching
#: what figure 3 already shows for the other authors'-threshold datasets.
CALLINGCARDS_BINDING_VIEW = "callingcards_500bp"

#: log-space Poisson p-value threshold below which a target counts as "bound", i.e.
#: ``poisson_pval < 1e-4``. Kept in log space because the linear ``poisson_pval``
#: underflows to exactly 0 for many strongly-bound targets (see `agreement.py`'s
#: ``AGREEMENT_RANK_OVERRIDES`` note) -- 0 would still correctly compare as "less than
#: 1e-4", but ``log_poisson_pval`` is the column already used elsewhere in this
#: codebase for exactly this dataset's precision concerns, so it is used here too for
#: consistency. A single named constant, deliberately not a CLI flag: this is a
#: modelling choice (what the authors would have called "bound"), not a per-run
#: parameter -- change this one line to revisit it.
CALLINGCARDS_LOG_POISSON_THRESHOLD: float = math.log(1e-4)


def callingcards_authors_bound_select_sql(
    binding_hf_repo: str,
    binding_hf_config: str,
    perturbation_view: str,
    pert_hf_repo: str,
    pert_hf_config: str,
    effect_threshold: float,
    pvalue_threshold: float,
    round_decimals: int = DEFAULT_FLOAT_DECIMALS,
) -> tuple[str, dict[str, Any]]:
    """
    Return a SELECT producing ``topn_results``-shaped rows for Calling Cards' authors'
    threshold, for one perturbation dataset.

    Structurally mirrors ``topn.py::topn_pair_select_sql_v2``: an
    ``intersecting_targets``
    restriction (only score a target if it is also measured by the perturbation
    dataset), a per-sample summary, and a left join back to the full (unthresholded)
    intersecting-target count -- the same ``n_intersecting_targets`` semantics every
    other ``topn_results`` row carries. The only structural difference is that "bound"
    here comes from :data:`CALLINGCARDS_LOG_POISSON_THRESHOLD`, not a rank cutoff.

    :param binding_hf_repo: HuggingFace repo for the Calling Cards binding dataset.
    :param binding_hf_config: HuggingFace config for the Calling Cards binding dataset.
    :param perturbation_view: Perturbation dataset name (key in
        ``topn.PERTURBATION_DATASET_COLUMNS``).
    :param pert_hf_repo: HuggingFace repo for the perturbation dataset.
    :param pert_hf_config: HuggingFace config for the perturbation dataset.
    :param effect_threshold: Minimum absolute effect size to count as responsive.
    :param pvalue_threshold: Maximum p-value to count as responsive.
    :param round_decimals: Decimal places kept for ``responsive_ratio``.
    :returns: ``(sql, params)``, ready for ``vdb.query(sql, **params)``.

    """
    params: dict[str, Any] = {
        "log_poisson_threshold": CALLINGCARDS_LOG_POISSON_THRESHOLD
    }
    responsive_case = responsive_expr(
        perturbation_view, effect_threshold, pvalue_threshold, "p", params
    )

    blacklist_ph = ", ".join(f"$bl_{i}" for i in range(len(CC_TARGET_BLACKLIST)))
    for i, tag in enumerate(CC_TARGET_BLACKLIST):
        params[f"bl_{i}"] = tag

    b_prefix = f"{binding_hf_repo};{binding_hf_config};".replace("'", "''")
    p_prefix = f"{pert_hf_repo};{pert_hf_config};".replace("'", "''")
    ratio_expr = round_expr(
        "SUM(pert.is_responsive)::DOUBLE / COUNT(*)", round_decimals
    )

    sql = f"""
    WITH binding_all AS (
        SELECT
            CAST(sample_id AS VARCHAR) AS binding_sample_id,
            regulator_locus_tag,
            target_locus_tag,
            log_poisson_pval
        FROM {CALLINGCARDS_BINDING_VIEW}
        WHERE target_locus_tag NOT IN ({blacklist_ph})
    ),
    perturbation AS (
        SELECT
            CAST(p.sample_id AS VARCHAR) AS perturbation_sample_id,
            p.regulator_locus_tag,
            p.target_locus_tag,
            {responsive_case} AS is_responsive
        FROM {perturbation_view} p
    ),
    intersecting_counts AS (
        SELECT
            b.binding_sample_id,
            b.regulator_locus_tag,
            pert.perturbation_sample_id,
            COUNT(DISTINCT b.target_locus_tag) AS n_intersecting_targets
        FROM binding_all b
        JOIN perturbation pert
            ON  b.regulator_locus_tag = pert.regulator_locus_tag
            AND b.target_locus_tag    = pert.target_locus_tag
        WHERE b.regulator_locus_tag != b.target_locus_tag
        GROUP BY b.binding_sample_id, b.regulator_locus_tag, pert.perturbation_sample_id
    ),
    intersecting_targets AS (
        SELECT DISTINCT b.regulator_locus_tag, b.target_locus_tag
        FROM binding_all b
        INNER JOIN perturbation pert
            ON  b.regulator_locus_tag = pert.regulator_locus_tag
            AND b.target_locus_tag    = pert.target_locus_tag
    ),
    bound AS (
        SELECT b.binding_sample_id, b.regulator_locus_tag, b.target_locus_tag
        FROM binding_all b
        INNER JOIN intersecting_targets it
            ON  b.regulator_locus_tag = it.regulator_locus_tag
            AND b.target_locus_tag    = it.target_locus_tag
        WHERE b.regulator_locus_tag != b.target_locus_tag
          AND b.log_poisson_pval < $log_poisson_threshold
    ),
    summary AS (
        SELECT
            b.binding_sample_id,
            b.regulator_locus_tag,
            pert.perturbation_sample_id,
            COUNT(*)                         AS n,
            SUM(pert.is_responsive)::INTEGER AS n_responsive,
            {ratio_expr}                     AS responsive_ratio
        FROM bound b
        JOIN perturbation pert
            ON  b.regulator_locus_tag = pert.regulator_locus_tag
            AND b.target_locus_tag    = pert.target_locus_tag
        GROUP BY b.binding_sample_id, b.regulator_locus_tag, pert.perturbation_sample_id
    )
    SELECT
        '{b_prefix}' || s.binding_sample_id         AS binding_source_sample,
        '{p_prefix}' || s.perturbation_sample_id    AS perturbation_source_sample,
        s.regulator_locus_tag,
        {TOP_N_ALL}                                 AS top_n,
        'log_poisson_pval_threshold'                AS rank_col,
        TRUE                                        AS rank_asc,
        {effect_threshold!r}::DOUBLE                AS effect_threshold,
        {pvalue_threshold!r}::DOUBLE                AS pvalue_threshold,
        s.n,
        s.n_responsive,
        s.responsive_ratio,
        COALESCE(ic.n_intersecting_targets, 0)::INTEGER AS n_intersecting_targets
    FROM summary s
    LEFT JOIN intersecting_counts ic
        ON  s.binding_sample_id      = ic.binding_sample_id
        AND s.regulator_locus_tag    = ic.regulator_locus_tag
        AND s.perturbation_sample_id = ic.perturbation_sample_id
    """
    return sql, params


__all__ = [
    "CALLINGCARDS_BINDING_VIEW",
    "CALLINGCARDS_LOG_POISSON_THRESHOLD",
    "callingcards_authors_bound_select_sql",
]
