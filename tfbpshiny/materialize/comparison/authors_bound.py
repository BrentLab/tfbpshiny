"""
Authors'-threshold "bound" sets, for figure 3 (authors' binding thresholds).

Rossi and Mahendrawada ship their own peak calls (``rossi_peaks``,
``chec_m2025_peaks``), which ``topn.py`` keeps every row of at the ``TOP_N_ALL``
sentinel. Harbison (2004 ChIP-chip) and Calling Cards ship only a per-target p-value,
so "bound" becomes well-defined only once a threshold is chosen. This module applies
one per dataset and writes rows into the same ``topn_results`` table at the same
``TOP_N_ALL`` sentinel, so ``modules/figures/queries.py::fetch_authors_bound`` reads
all four datasets through one query.

The SQL is one template. The two datasets differ only in how the binding rows are
produced (Calling Cards drops its blacklisted targets; Harbison goes through the
YPD-only, minimum-p-value dedup CTE every other Harbison analysis uses) and in the
predicate that makes a row "bound". Each is an :class:`AuthorsBoundConfig`.

Deliberately not threaded through ``topn.py``'s shared staged-SQL machinery: that
applies one binding CTE uniformly across every ``top_n`` value for a dataset, whereas
these need *different* binding rows for the ``TOP_N_ALL`` pass (threshold-filtered)
than for the ordinary ranked cutoffs (unfiltered).

"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from tfbpshiny.datasets import TOP_N_ALL
from tfbpshiny.materialize.comparison.topn import (
    CC_TARGET_BLACKLIST,
    HARBISON_DEDUP_CTE,
    responsive_expr,
)
from tfbpshiny.materialize.rounding import DEFAULT_FLOAT_DECIMALS, round_expr


@dataclass(frozen=True)
class AuthorsBoundConfig:
    """
    How one dataset's "bound" rows are produced.

    :param binding_view: The VirtualDB view the rows come from.
    :param binding_cte_sql: SELECT yielding ``binding_sample_id``,
        ``regulator_locus_tag``, ``target_locus_tag`` and the column the predicate
        tests; it becomes the ``binding_all`` CTE.
    :param bound_predicate_sql: Boolean SQL over alias ``b`` that makes a
        ``binding_all`` row bound. Thresholds are ``$named`` parameters.
    :param rank_col_label: Written to ``topn_results.rank_col`` so a reader can tell
        which threshold produced the row.
    :param params: Values for the predicate's named parameters.

    """

    binding_view: str
    binding_cte_sql: str
    bound_predicate_sql: str
    rank_col_label: str
    params: dict[str, Any]


#: log-space Poisson p-value threshold below which a Calling Cards target counts as
#: "bound", i.e. ``poisson_pval < 1e-4``. Kept in log space because the linear
#: ``poisson_pval`` underflows to exactly 0 for many strongly-bound targets (see
#: ``agreement.py``'s ``AGREEMENT_RANK_OVERRIDES`` note); ``log_poisson_pval`` is the
#: column already used for this dataset's precision concerns. A single named constant,
#: deliberately not a CLI flag: this is a modelling choice (what the authors would have
#: called "bound"), not a per-run parameter -- change this one line to revisit it.
CALLINGCARDS_LOG_POISSON_THRESHOLD: float = math.log(1e-4)

#: A Harbison target counts as "bound" when its p-value is ``<=`` this: the conventional
#: stringent Harbison cutoff. Same status as the Calling Cards constant above.
HARBISON_PVALUE_THRESHOLD: float = 0.001

_CC_BLACKLIST_PARAMS: dict[str, Any] = {
    f"bl_{i}": tag for i, tag in enumerate(CC_TARGET_BLACKLIST)
}
_CC_BLACKLIST_PLACEHOLDERS = ", ".join(f"${k}" for k in _CC_BLACKLIST_PARAMS)

#: The datasets figure 3 needs a chosen threshold for, keyed by binding view.
AUTHORS_BOUND_CONFIGS: dict[str, AuthorsBoundConfig] = {
    "callingcards_500bp": AuthorsBoundConfig(
        binding_view="callingcards_500bp",
        binding_cte_sql=f"""
        SELECT
            CAST(sample_id AS VARCHAR) AS binding_sample_id,
            regulator_locus_tag,
            target_locus_tag,
            log_poisson_pval
        FROM callingcards_500bp
        WHERE target_locus_tag NOT IN ({_CC_BLACKLIST_PLACEHOLDERS})
        """,
        bound_predicate_sql="b.log_poisson_pval < $log_poisson_threshold",
        rank_col_label="log_poisson_pval_threshold",
        params={
            "log_poisson_threshold": CALLINGCARDS_LOG_POISSON_THRESHOLD,
            **_CC_BLACKLIST_PARAMS,
        },
    ),
    "harbison": AuthorsBoundConfig(
        binding_view="harbison",
        binding_cte_sql=HARBISON_DEDUP_CTE,
        bound_predicate_sql="b.pvalue <= $harbison_pvalue_threshold",
        rank_col_label="pvalue_threshold",
        params={"harbison_pvalue_threshold": HARBISON_PVALUE_THRESHOLD},
    ),
}


def authors_bound_select_sql(
    config: AuthorsBoundConfig,
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
    Return a SELECT producing ``topn_results``-shaped rows for one dataset's authors'
    threshold against one perturbation dataset.

    Structurally mirrors ``topn.py::topn_pair_select_sql_v2``: an
    ``intersecting_targets`` restriction (only score a target the perturbation dataset
    also measures), a per-sample summary, and a left join back to the full
    (unthresholded) intersecting-target count -- the same ``n_intersecting_targets``
    semantics every other ``topn_results`` row carries. The only structural difference
    is that "bound" comes from ``config.bound_predicate_sql``, not a rank cutoff.

    :param config: Which dataset, and how its rows become "bound".
    :param binding_hf_repo: HuggingFace repo for the binding dataset.
    :param binding_hf_config: HuggingFace config for the binding dataset.
    :param perturbation_view: Perturbation dataset name (key in
        ``tfbpshiny.datasets.PERTURBATION_DATASET_COLUMNS``).
    :param pert_hf_repo: HuggingFace repo for the perturbation dataset.
    :param pert_hf_config: HuggingFace config for the perturbation dataset.
    :param effect_threshold: Minimum absolute effect size to count as responsive.
    :param pvalue_threshold: Maximum p-value to count as responsive.
    :param round_decimals: Decimal places kept for ``responsive_ratio``.
    :returns: ``(sql, params)``, ready for ``vdb.query(sql, **params)``.

    """
    params: dict[str, Any] = dict(config.params)
    responsive_case = responsive_expr(
        perturbation_view, effect_threshold, pvalue_threshold, "p", params
    )

    b_prefix = f"{binding_hf_repo};{binding_hf_config};".replace("'", "''")
    p_prefix = f"{pert_hf_repo};{pert_hf_config};".replace("'", "''")
    ratio_expr = round_expr(
        "SUM(pert.is_responsive)::DOUBLE / COUNT(*)", round_decimals
    )
    rank_col_label = config.rank_col_label.replace("'", "''")

    sql = f"""
    WITH binding_all AS (
        {config.binding_cte_sql}
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
          AND {config.bound_predicate_sql}
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
        '{rank_col_label}'                          AS rank_col,
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
    "AUTHORS_BOUND_CONFIGS",
    "AuthorsBoundConfig",
    "CALLINGCARDS_LOG_POISSON_THRESHOLD",
    "HARBISON_PVALUE_THRESHOLD",
    "authors_bound_select_sql",
]
