"""
Harbison's authors'-threshold "bound" set, for figure 3 (authors' binding thresholds).

Harbison (2004 ChIP-chip) ships a p-value for every gene, with no binary call, so
"bound" only becomes well-defined once a threshold is chosen -- the same situation as
Calling Cards (see ``callingcards_authors_bound.py``, which this mirrors). This module
applies the conventional Harbison cutoff, ``pvalue <= 0.001``, writing rows into the
existing ``topn_results`` table at the ``TOP_N_ALL`` sentinel, so
``modules/figures/queries.py::fetch_authors_bound`` reads Harbison exactly the way it
reads the other authors'-threshold datasets.

Binding rows come from ``topn.py``'s Harbison dedup CTE (YPD only, minimum p-value per
sample/regulator/target), so the figure agrees with every other Harbison analysis in
the app.

"""

from __future__ import annotations

from typing import Any

from tfbpshiny.materialize.comparison.topn import (
    _HARBISON_DEDUP_CTE,
    TOP_N_ALL,
    responsive_expr,
)
from tfbpshiny.materialize.rounding import DEFAULT_FLOAT_DECIMALS, round_expr

#: Binding dataset this applies to.
HARBISON_BINDING_VIEW = "harbison"

#: A target counts as "bound" when its Harbison p-value is ``<=`` this. A single named
#: constant, deliberately not a CLI flag: this is a modelling choice (the stringent
#: definition of "bound"), not a per-run parameter -- change this one line to revisit
#: it.
HARBISON_PVALUE_THRESHOLD: float = 0.001


def harbison_authors_bound_select_sql(
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
    Return a SELECT producing ``topn_results``-shaped rows for Harbison's authors'
    threshold, for one perturbation dataset.

    Structurally identical to
    ``callingcards_authors_bound.callingcards_authors_bound_select_sql``: an
    ``intersecting_targets`` restriction (only score a target if the perturbation
    dataset also measures it), a per-sample summary, and a left join back to the full
    (unthresholded) intersecting-target count. Only the binding CTE and the "bound"
    predicate differ.

    :param binding_hf_repo: HuggingFace repo for the Harbison binding dataset.
    :param binding_hf_config: HuggingFace config for the Harbison binding dataset.
    :param perturbation_view: Perturbation dataset name (key in
        ``topn.PERTURBATION_DATASET_COLUMNS``).
    :param pert_hf_repo: HuggingFace repo for the perturbation dataset.
    :param pert_hf_config: HuggingFace config for the perturbation dataset.
    :param effect_threshold: Minimum absolute effect size to count as responsive.
    :param pvalue_threshold: Maximum p-value to count as responsive.
    :param round_decimals: Decimal places kept for ``responsive_ratio``.
    :returns: ``(sql, params)``, ready for ``vdb.query(sql, **params)``.

    """
    params: dict[str, Any] = {"harbison_pvalue_threshold": HARBISON_PVALUE_THRESHOLD}
    responsive_case = responsive_expr(
        perturbation_view, effect_threshold, pvalue_threshold, "p", params
    )

    b_prefix = f"{binding_hf_repo};{binding_hf_config};".replace("'", "''")
    p_prefix = f"{pert_hf_repo};{pert_hf_config};".replace("'", "''")
    ratio_expr = round_expr(
        "SUM(pert.is_responsive)::DOUBLE / COUNT(*)", round_decimals
    )

    sql = f"""
    WITH binding_all AS (
        {_HARBISON_DEDUP_CTE}
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
          AND b.pvalue <= $harbison_pvalue_threshold
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
        'pvalue_threshold'                          AS rank_col,
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
    "HARBISON_BINDING_VIEW",
    "HARBISON_PVALUE_THRESHOLD",
    "harbison_authors_bound_select_sql",
]
