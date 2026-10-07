# flake8: noqa
"""
Data access for the Figures module.

Every function here reads the materialized DuckDB directly and returns a tidy DataFrame;
no reactive code lives in this file.

"""

from __future__ import annotations

import itertools

import duckdb
import numpy as np
import pandas as pd

from tfbpshiny.datasets import (
    DTO_PVALUE_THRESHOLD,
    GENE_UNIVERSE,
    METHOD_LEVELS,
    PROMOTER_SET_LEVELS,
    TOP_N_ALL,
)
from tfbpshiny.materialize.comparison.agreement import AGREEMENT_EXCLUDED
from tfbpshiny.utils.corr_query import (
    get_filtered_sample_ids,
    per_dataset_sample_clause,
    sample_filter_clause,
)
from tfbpshiny.utils.vdb_init import DEFAULT_RESPONSIVENESS_PRESETS

#: Binding datasets shown in the figures, in display order. These are the *primary*
#: db_names -- the promoter-set and peak variants are not separate figure series.
BINDING_ORDER: tuple[str, ...] = (
    "harbison",
    "callingcards_500bp",
    "rossi_500bp",
    "chec_m2025_500bp",
)

#: Perturbation datasets shown, in display order.
PR_ORDER: tuple[str, ...] = ("kemmeren", "hackett", "degron")

#: Binding datasets that have DTO results. Harbison has **zero** DTO rows -- the
#: upstream analysis covers 22 binding datasets and none of them is ChIP-chip -- so
#: the DTO figures are necessarily three-wide rather than four.
DTO_BINDING_ORDER: tuple[str, ...] = (
    "callingcards_500bp",
    "rossi_500bp",
    "chec_m2025_500bp",
)

#: The only ranking variant present for all six perturbation datasets.
DTO_RANKING_COLUMN = "log2fc"

#: Binding datasets shown in the authors'-threshold figure, in display order. Rossi and
#: ChEC-seq carry the authors' own peak calls. Harbison (p <= 0.001) and Calling Cards
#: (Poisson p < 1e-4) have only a per-target p-value, so each is given an explicit,
#: named threshold -- see ``materialize/comparison/authors_bound.py``. Materialize
#: writes all of them into
#: ``topn_results`` at the same ``TOP_N_ALL`` sentinel, so they read through one query.
AUTHORS_PEAK_BINDING: tuple[str, ...] = (
    "harbison",
    "rossi_peaks",
    "chec_m2025_peaks",
    "callingcards_500bp",
)

#: Datasets figure 6 compares by default: promoter enrichment over the 500 bp
#: start-codon window, so the assays are compared on one promoter definition rather
#: than on whichever one happens to be each dataset's primary.
#:
#: Harbison is absent, and cannot be added to a promoter-matched comparison at all:
#: its regions are microarray probes fixed by the platform, so it has no 500 bp
#: variant and no way to acquire one. It remains selectable -- figure 6 intersects
#: *target sets*, not genomic regions, so the overlap is still well defined -- but a
#: pair involving it compares one assay's promoter-window ranking against another's
#: probe-level ranking, and the promoter definition is not held fixed.
AGREEMENT_DEFAULT_BINDING: tuple[str, ...] = (
    "callingcards_500bp",
    "rossi_500bp",
    "chec_m2025_500bp",
)

#: Perturbation datasets figure 6 compares by default. These have no promoter
#: variants, so the default is simply the three headline datasets.
AGREEMENT_DEFAULT_PERTURBATION: tuple[str, ...] = PR_ORDER

#: Compact per-dataset label for figure 6, e.g. "2021 ChIP-exo Kang peaks".
#:
#: ``base_label`` alone is ambiguous once variants are selectable -- every Rossi
#: variant shares "2021 ChIP-exo", so a promoter-set comparison would read
#: "2021 ChIP-exo vs 2021 ChIP-exo". ``display_name`` is unambiguous but far too long
#: for a legend entry, so the qualifier is appended directly -- except for the 500bp
#: promoter set, which every default selection uses: naming it on every single series
#: would just be noise for the common case, so it's the one promoter set left
#: unstated (documented in the figure's description instead). A non-default promoter
#: set (Kang, Mindel, Intergenic) still needs to appear, or two variants of the same
#: assay would render as identical, indistinguishable legend entries.
_AGREEMENT_LABEL_SQL = """
        r.base_label
        || CASE
             WHEN r.promoter_set_id = '500bp' THEN ''
             ELSE COALESCE(' ' || ps.display_name, '')
           END
        || CASE WHEN r.binding_method_id = 'peak_calling' THEN ' peaks' ELSE '' END
"""


#: Default, minimum, maximum and step for figure 6's weighting half-life, in units of
#: N. The grid runs 10-200 (``AGREEMENT_TOP_N``), so the slider spans "only the very
#: top of the ranking matters" to "weight the whole grid almost evenly".
#:
#: The default of 10 concentrates roughly half the weight on N=10. For reference, a
#: half-life of 20 reproduces the balance of the ``1/N`` weighting this replaced
#: (29.3% of the mass on N=10, against 1/N's 27.8%).
AGREEMENT_HALF_LIFE_DEFAULT = 10
AGREEMENT_HALF_LIFE_MIN = 10
AGREEMENT_HALF_LIFE_MAX = 200
AGREEMENT_HALF_LIFE_STEP = 10

#: Above this many dataset pairs the figure's lines and boxes stop being separable.
#: Selecting more is allowed; the UI says what it costs.
AGREEMENT_PAIR_WARN = 12

#: Binding primaries with a peak-calling arm at every promoter set, for figure 9.
#: Calling Cards has none (confirmed: no `callingcards_*_peaks` registry rows), so it
#: is excluded here rather than shown as an empty row.
METHOD_COMPARISON_BINDING: tuple[str, ...] = ("rossi_500bp", "chec_m2025_500bp")


def scoring_clause(
    pr_db: str,
    preset_name: str = "Relaxed",
    alias: str = "t",
) -> tuple[str, list]:
    """
    Build the SQL restricting ``topn_results`` to one scoring definition.

    **This is not optional.** ``topn_results`` holds one row per threshold pair per
    (binding sample, perturbation sample, regulator, top_n), and both presets are
    materialized by default, so a query that does not pin the pair medians across two
    incompatible definitions of responsive.

    Thresholds resolve per perturbation dataset, so the pair pinned for ``kemmeren``
    differs from the one pinned for ``degron`` under the same preset name.

    :param pr_db: Perturbation dataset, whose own preset thresholds are used.
    :param preset_name: Responsiveness preset (``Relaxed`` or ``Stringent``, the
        latter being each dataset's published criteria).
    :param alias: Table alias used in the calling query.
    :returns: ``(sql_fragment, params)``.

    """
    preset = DEFAULT_RESPONSIVENESS_PRESETS.get(preset_name, {})
    effect, pvalue = preset.get(pr_db, preset.get("*", (0.0, 0.05)))
    return (
        f" AND {alias}.effect_threshold = ?" f" AND {alias}.pvalue_threshold = ?",
        [effect, pvalue],
    )


def dataset_labels(conn: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """
    Map ``db_name`` to its short ``base_label`` (e.g. ``rossi`` -> ``2021 ChIP-exo``).

    Covers every dataset, not only the primaries. Figure 6's picker can select any
    promoter or peak variant, and a figure constant can legitimately name a
    non-primary. Filtering on ``is_primary`` left those unlabelled, which made the
    ``BINDING_COLORS`` lookup -- keyed by ``base_label`` -- return ``None``, and plotly
    rejects a null colour outright rather than degrading. Variants share their
    primary's ``base_label``, so widening the query gives them the right colour too.

    :param conn: Read-only DuckDB connection.
    :returns: db_name -> base_label.

    """
    df = conn.execute("SELECT db_name, base_label FROM dataset_registry").df()
    return dict(zip(df["db_name"], df["base_label"]))


def resolve_promoter_variant(
    conn: duckdb.DuckDBPyConnection, primary: str, promoter_set_id: str, method_id: str
) -> str | None:
    """
    Resolve one (assay primary, promoter set, method) cell to a concrete ``db_name``.

    A local, self-contained resolver rather than an import of ``BindingIndex`` from
    ``modules/comparison/queries.py`` -- this app keeps sibling ``modules/`` isolated
    from each other (mirrors ``materialize/comparison/method_promoter_model.py``'s own
    local ``_resolve_cell``, kept local for the same reason).

    :param conn: Read-only DuckDB connection.
    :param primary: Primary binding db_name (e.g. ``'rossi_500bp'``).
    :param promoter_set_id: Promoter set id, e.g. ``'kang'``.
    :param method_id: Binding method id, e.g. ``'peak_calling'``.
    :returns: The matching ``db_name``, or ``None`` if this assay has no such variant.

    """
    df = conn.execute(
        "SELECT db_name FROM dataset_registry"
        " WHERE COALESCE(primary_db_name, db_name) = ?"
        "   AND promoter_set_id = ? AND binding_method_id = ?",
        [primary, promoter_set_id, method_id],
    ).df()
    return str(df.iloc[0]["db_name"]) if not df.empty else None


def sort_regulators_by_symbol(tags: list[str], symbols: dict[str, str]) -> list[str]:
    """
    Order regulators alphabetically by gene symbol, ignoring case.

    A regulator with no symbol sorts by its locus tag instead, so it lands among the
    named ones rather than being pushed to either end.

    :param tags: Regulator locus tags.
    :param symbols: locus tag -> gene symbol, for the regulators that have one.
    :returns: ``tags`` reordered; ties break on the locus tag.

    """
    return sorted(tags, key=lambda t: (symbols.get(t, t).casefold(), t))


def regulator_intersection(
    conn: duckdb.DuckDBPyConnection, db_names: list[str]
) -> list[str]:
    """
    Regulators present in every one of ``db_names``.

    Reads ``sample_regulator``, which covers every dataset whose metadata carries a
    regulator column.

    :param conn: Read-only DuckDB connection.
    :param db_names: Datasets to intersect.
    :returns: Sorted locus tags.

    """
    if not db_names:
        return []
    parts = " INTERSECT ".join(
        "SELECT regulator_locus_tag FROM sample_regulator WHERE db_name = ?"
        for _ in db_names
    )
    df = conn.execute(f"{parts} ORDER BY 1", db_names).df()
    return df["regulator_locus_tag"].tolist()


def fetch_rank_response(
    conn: duckdb.DuckDBPyConnection,
    binding_dbs: list[str],
    pr_db: str,
    regulators: list[str],
    filters: dict | None = None,
    preset_name: str = "Relaxed",
) -> pd.DataFrame:
    """
    Response rate as a function of binding rank, for figure 1.

    ``topn_results`` is materialized at five cutoffs, giving a five-point cumulative
    curve per (binding dataset, regulator).

    The x value is ``n``, **not** ``top_n``. A tie group is in the top N only when its
    average rank is within N, so ``n`` can fall below or above ``top_n`` -- ``n`` is
    the number of targets actually summarised, and is the honest x coordinate.

    Where a regulator has several binding or perturbation samples, the median across
    them is taken so each (binding dataset, regulator, n) yields one point.

    :param conn: Read-only DuckDB connection.
    :param binding_dbs: Primary binding db_names to include as series.
    :param pr_db: Perturbation db_name.
    :param regulators: Regulators to include.
    :param filters: Per-dataset sample filters, keyed by db_name.
    :returns: Columns ``binding_db``, ``regulator_locus_tag``, ``n``,
        ``percent_responsive``.

    """
    if not binding_dbs or not regulators:
        return pd.DataFrame()
    filters = filters or {}
    p_clause, p_params = sample_filter_clause(
        conn,
        pr_db,
        filters.get(pr_db),
        "split_part(t.perturbation_source_sample, ';', 3)",
    )
    s_clause, s_params = scoring_clause(pr_db, preset_name)
    b_clause, b_params = per_dataset_sample_clause(
        conn,
        binding_dbs,
        filters,
        "b.db_name",
        "split_part(t.binding_source_sample, ';', 3)",
    )
    b_ph = ", ".join(["?"] * len(binding_dbs))
    r_ph = ", ".join(["?"] * len(regulators))
    sql = f"""
    WITH b AS (
        SELECT db_name, hf_repo || ';' || hf_config || ';' AS prefix
        FROM dataset_registry WHERE db_name IN ({b_ph})
    ),
    p AS (
        SELECT hf_repo || ';' || hf_config || ';' AS prefix
        FROM dataset_registry WHERE db_name = ?
    )
    SELECT b.db_name                            AS binding_db,
           t.regulator_locus_tag,
           t.n,
           median(t.responsive_ratio) * 100     AS percent_responsive
    FROM topn_results t
    JOIN b ON t.binding_source_sample LIKE b.prefix || '%'
    JOIN p ON t.perturbation_source_sample LIKE p.prefix || '%'
    WHERE t.regulator_locus_tag IN ({r_ph}){s_clause}{p_clause}{b_clause}
    GROUP BY b.db_name, t.regulator_locus_tag, t.n
    ORDER BY b.db_name, t.regulator_locus_tag, t.n
    """
    return conn.execute(
        sql, binding_dbs + [pr_db] + regulators + s_params + p_params + b_params
    ).df()


def fetch_topn_percent_responsive(
    conn: duckdb.DuckDBPyConnection,
    binding_dbs: list[str],
    pr_db: str,
    regulators: list[str],
    top_n: int = 25,
    filters: dict | None = None,
    preset_name: str = "Relaxed",
) -> pd.DataFrame:
    """
    Per-regulator percent responsive at a single top-N cutoff, for figure 2.

    :param conn: Read-only DuckDB connection.
    :param binding_dbs: Primary binding db_names, one box each.
    :param pr_db: Perturbation db_name.
    :param regulators: Regulators to include.
    :param top_n: Materialized cutoff to read.
    :param filters: Per-dataset sample filters, keyed by db_name.
    :param preset_name: Responsiveness preset whose per-dataset thresholds to pin.
    :returns: Columns ``binding_db``, ``regulator_locus_tag``, ``percent_responsive``.

    """
    if not binding_dbs or not regulators:
        return pd.DataFrame()
    filters = filters or {}
    p_clause, p_params = sample_filter_clause(
        conn,
        pr_db,
        filters.get(pr_db),
        "split_part(t.perturbation_source_sample, ';', 3)",
    )
    s_clause, s_params = scoring_clause(pr_db, preset_name)
    b_clause, b_params = per_dataset_sample_clause(
        conn,
        binding_dbs,
        filters,
        "b.db_name",
        "split_part(t.binding_source_sample, ';', 3)",
    )
    b_ph = ", ".join(["?"] * len(binding_dbs))
    r_ph = ", ".join(["?"] * len(regulators))
    sql = f"""
    WITH b AS (
        SELECT db_name, hf_repo || ';' || hf_config || ';' AS prefix
        FROM dataset_registry WHERE db_name IN ({b_ph})
    ),
    p AS (
        SELECT hf_repo || ';' || hf_config || ';' AS prefix
        FROM dataset_registry WHERE db_name = ?
    )
    SELECT b.db_name                        AS binding_db,
           t.regulator_locus_tag,
           median(t.responsive_ratio) * 100 AS percent_responsive
    FROM topn_results t
    JOIN b ON t.binding_source_sample LIKE b.prefix || '%'
    JOIN p ON t.perturbation_source_sample LIKE p.prefix || '%'
    WHERE t.top_n = ? AND t.regulator_locus_tag IN ({r_ph}){s_clause}{p_clause}{b_clause}
    GROUP BY b.db_name, t.regulator_locus_tag
    """
    return conn.execute(
        sql,
        binding_dbs + [pr_db, top_n] + regulators + s_params + p_params + b_params,
    ).df()


def fetch_dto_significance(
    conn: duckdb.DuckDBPyConnection,
    binding_dbs: list[str],
    pr_dbs: list[str],
    pvalue_threshold: float = DTO_PVALUE_THRESHOLD,
    pr_ranking_column: str = DTO_RANKING_COLUMN,
) -> pd.DataFrame:
    """
    DTO-significant regulator counts and fractions per dataset pair, for figure 4.

    The denominator is the number of regulators shared by the two datasets, taken from
    ``sample_regulator`` -- the full metadata intersect, not DTO's own coverage. DTO
    does not test every shared regulator, so ``n_covered`` is returned alongside to
    keep that gap visible.

    :param conn: Read-only DuckDB connection.
    :param binding_dbs: Binding db_names.
    :param pr_dbs: Perturbation db_names.
    :param pvalue_threshold: Empirical p-value cutoff.
    :param pr_ranking_column: DTO ranking variant.
    :returns: One row per pair with ``n_significant``, ``n_covered``, ``n_shared`` and
        ``fraction_significant``.

    """
    rows: list[dict] = []
    for b_db in binding_dbs:
        for p_db in pr_dbs:
            res = conn.execute(
                """
                WITH shared AS (
                    SELECT regulator_locus_tag FROM sample_regulator WHERE db_name = ?
                    INTERSECT
                    SELECT regulator_locus_tag FROM sample_regulator WHERE db_name = ?
                ),
                tested AS (
                    SELECT regulator_locus_tag, min(dto_empirical_pvalue) AS best_p
                    FROM dto
                    WHERE binding_db = ? AND perturbation_db = ?
                      AND pr_ranking_column = ?
                    GROUP BY regulator_locus_tag
                )
                SELECT
                    (SELECT count(*) FROM shared) AS n_shared,
                    (SELECT count(*) FROM tested
                      WHERE regulator_locus_tag IN (SELECT * FROM shared))
                        AS n_covered,
                    (SELECT count(*) FROM tested
                      WHERE best_p < ?
                        AND regulator_locus_tag IN (SELECT * FROM shared))
                        AS n_significant
                """,
                [b_db, p_db, b_db, p_db, pr_ranking_column, pvalue_threshold],
            ).df()
            r = res.iloc[0]
            n_shared = int(r["n_shared"])
            if n_shared == 0:
                continue
            n_sig = int(r["n_significant"])
            rows.append(
                {
                    "binding_db": b_db,
                    "perturbation_db": p_db,
                    "n_significant": n_sig,
                    "n_covered": int(r["n_covered"]),
                    "n_shared": n_shared,
                    "fraction_significant": n_sig / n_shared,
                }
            )
    return pd.DataFrame(rows)


def fetch_dto_significance_for_universe(
    conn: duckdb.DuckDBPyConnection,
    binding_db: str,
    pr_db: str,
    universe: set[str] | frozenset[str],
    pvalue_threshold: float = DTO_PVALUE_THRESHOLD,
    pr_ranking_column: str = DTO_RANKING_COLUMN,
) -> dict[str, int]:
    """
    DTO-significant/covered counts for one (binding, perturbation) pair, restricted to
    an explicit regulator universe rather than :func:`fetch_dto_significance`'s own
    pairwise ``sample_regulator`` intersect.

    For figure 9's bottom grid: DTO significance is pre-computed entirely externally
    (no local statistics to rerun), so a regulator peak_calling never called a peak
    for has no empirical p-value and no value to report; it is left out. Instead,
    a sibling promoter_enrichment/peak_calling pair shares one 3-way-intersected
    universe (see :func:`regulator_intersection`) as their common denominator, so the
    two bars are directly comparable instead of each drawing its own, unevenly-sized,
    pairwise intersection with the perturbation dataset.

    :param conn: Read-only DuckDB connection.
    :param binding_db: Binding db_name.
    :param pr_db: Perturbation db_name.
    :param universe: Regulator locus tags to restrict to (the caller's precomputed
        3-way intersection).
    :param pvalue_threshold: Empirical p-value cutoff.
    :param pr_ranking_column: DTO ranking variant.
    :returns: ``{"n_significant": int, "n_covered": int}`` within ``universe``.

    """
    if not universe:
        return {"n_significant": 0, "n_covered": 0}
    df = conn.execute(
        """
        SELECT regulator_locus_tag, min(dto_empirical_pvalue) AS best_p
        FROM dto
        WHERE binding_db = ? AND perturbation_db = ? AND pr_ranking_column = ?
        GROUP BY regulator_locus_tag
        """,
        [binding_db, pr_db, pr_ranking_column],
    ).df()
    if df.empty:
        return {"n_significant": 0, "n_covered": 0}
    df = df[df["regulator_locus_tag"].isin(universe)]
    n_covered = len(df)
    n_significant = int((df["best_p"] < pvalue_threshold).sum())
    return {"n_significant": n_significant, "n_covered": n_covered}


def fetch_dto_significant_sets(
    conn: duckdb.DuckDBPyConnection,
    binding_dbs: list[str],
    pr_db: str,
    pvalue_threshold: float = DTO_PVALUE_THRESHOLD,
    pr_ranking_column: str = DTO_RANKING_COLUMN,
) -> dict[str, set[str]]:
    """
    The set of DTO-significant regulators per binding dataset, for figure 5's Venn.

    Restricted to regulators shared by all of ``binding_dbs`` and ``pr_db``, so the
    Venn's universe is a single well-defined regulator set and the outside-all-circles
    region is meaningful.

    :param conn: Read-only DuckDB connection.
    :param binding_dbs: Binding db_names, one circle each.
    :param pr_db: Perturbation db_name.
    :param pvalue_threshold: Empirical p-value cutoff.
    :param pr_ranking_column: DTO ranking variant.
    :returns: binding db_name -> set of significant locus tags.

    """
    universe = set(regulator_intersection(conn, list(binding_dbs) + [pr_db]))
    if not universe:
        return {b: set() for b in binding_dbs}

    out: dict[str, set[str]] = {}
    for b_db in binding_dbs:
        df = conn.execute(
            """
            SELECT regulator_locus_tag, min(dto_empirical_pvalue) AS best_p
            FROM dto
            WHERE binding_db = ? AND perturbation_db = ? AND pr_ranking_column = ?
            GROUP BY regulator_locus_tag
            HAVING min(dto_empirical_pvalue) < ?
            """,
            [b_db, pr_db, pr_ranking_column, pvalue_threshold],
        ).df()
        out[b_db] = set(df["regulator_locus_tag"]) & universe
    return out


__all__ = [
    "AUTHORS_PEAK_BINDING",
    "BINDING_ORDER",
    "GENE_UNIVERSE",
    "TOP_N_ALL",
    "AGREEMENT_DEFAULT_BINDING",
    "AGREEMENT_HALF_LIFE_DEFAULT",
    "AGREEMENT_HALF_LIFE_MAX",
    "AGREEMENT_HALF_LIFE_MIN",
    "AGREEMENT_HALF_LIFE_STEP",
    "AGREEMENT_DEFAULT_PERTURBATION",
    "AGREEMENT_PAIR_WARN",
    "agreement_dataset_choices",
    "fetch_agreement",
    "fetch_authors_bound",
    "fetch_shared_targets",
    "fetch_target_sets",
    "has_top_n",
    "sort_regulators_by_symbol",
    "table_exists",
    "weighted_agreement",
    "DTO_BINDING_ORDER",
    "DTO_PVALUE_THRESHOLD",
    "DTO_RANKING_COLUMN",
    "METHOD_COMPARISON_BINDING",
    "METHOD_LEVELS",
    "PROMOTER_SET_LEVELS",
    "PR_ORDER",
    "dataset_labels",
    "fetch_dto_significance",
    "fetch_dto_significance_for_universe",
    "fetch_dto_significant_sets",
    "fetch_rank_response",
    "fetch_topn_percent_responsive",
    "regulator_intersection",
    "resolve_promoter_variant",
    "scoring_clause",
]


# ---------------------------------------------------------------------------
# Startup probes: is the table / cutoff a figure needs present in this database?
# ---------------------------------------------------------------------------


def table_exists(conn: duckdb.DuckDBPyConnection, name: str) -> bool:
    """
    Whether a table is present in the database.

    :param conn: Read-only DuckDB connection.
    :param name: Table name.
    :returns: ``True`` when present.

    """
    return bool(
        conn.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
            [name],
        ).fetchone()[0]
    )


def has_top_n(conn: duckdb.DuckDBPyConnection, top_n: int) -> bool:
    """
    Whether ``topn_results`` carries rows at a given cutoff.

    Guards figure 3, whose ``TOP_N_ALL`` rows only exist in databases built since that
    cutoff was added.

    :param conn: Read-only DuckDB connection.
    :param top_n: Cutoff to look for.
    :returns: ``True`` when such rows exist.

    """
    return bool(
        conn.execute(
            "SELECT count(*) FROM (SELECT 1 FROM topn_results WHERE top_n = ? LIMIT 1)",
            [top_n],
        ).fetchone()[0]
    )


def fetch_authors_bound(
    conn: duckdb.DuckDBPyConnection,
    binding_dbs: list[str],
    pr_db: str,
    filters: dict | None = None,
    preset_name: str = "Relaxed",
) -> pd.DataFrame:
    """
    Response rate and bound-set size over the authors' bound targets, for figure 3.

    Reads the ``top_n = TOP_N_ALL`` rows, where no rank cutoff was applied because the
    peak call *is* the authors' threshold. ``n`` is therefore the number of targets the
    authors called bound for that TF. Only the *binding* side is the authors' here;
    responsiveness is scored by the selected preset, as in every other figure.

    :param conn: Read-only DuckDB connection.
    :param binding_dbs: Peak binding db_names.
    :param pr_db: Perturbation db_name.
    :param filters: Per-dataset sample filters, keyed by db_name.
    :param preset_name: Responsiveness preset whose per-dataset thresholds to pin.
    :returns: Columns ``binding_db``, ``regulator_locus_tag``, ``percent_responsive``,
        ``n_bound``.

    """
    if not binding_dbs:
        return pd.DataFrame()
    filters = filters or {}
    p_clause, p_params = sample_filter_clause(
        conn,
        pr_db,
        filters.get(pr_db),
        "split_part(t.perturbation_source_sample, ';', 3)",
    )
    s_clause, s_params = scoring_clause(pr_db, preset_name)
    b_clause, b_params = per_dataset_sample_clause(
        conn,
        binding_dbs,
        filters,
        "b.db_name",
        "split_part(t.binding_source_sample, ';', 3)",
    )
    b_ph = ", ".join(["?"] * len(binding_dbs))
    sql = f"""
    WITH b AS (
        SELECT db_name, hf_repo || ';' || hf_config || ';' AS prefix
        FROM dataset_registry WHERE db_name IN ({b_ph})
    ),
    p AS (
        SELECT hf_repo || ';' || hf_config || ';' AS prefix
        FROM dataset_registry WHERE db_name = ?
    )
    SELECT b.db_name                        AS binding_db,
           t.regulator_locus_tag,
           median(t.responsive_ratio) * 100 AS percent_responsive,
           median(t.n)                      AS n_bound
    FROM topn_results t
    JOIN b ON t.binding_source_sample LIKE b.prefix || '%'
    JOIN p ON t.perturbation_source_sample LIKE p.prefix || '%'
    WHERE t.top_n = ?{s_clause}{p_clause}{b_clause}
    GROUP BY b.db_name, t.regulator_locus_tag
    """
    return conn.execute(
        sql, binding_dbs + [pr_db, TOP_N_ALL] + s_params + p_params + b_params
    ).df()


def agreement_dataset_choices(
    conn: duckdb.DuckDBPyConnection, comparison_type: str
) -> dict[str, str]:
    """
    Selectable datasets for figure 6, in a stable display order.

    Ordered assay, then method (promoter enrichment before peak calling), then
    promoter set, so the variants of one experiment sit together and a reader
    scanning for "the 500 bp row" finds it in the same place under each assay.

    Datasets in :data:`~tfbpshiny.materialize.comparison.agreement.AGREEMENT_EXCLUDED`
    are omitted -- ``topn_agreement`` holds no rows for them.

    :param conn: Read-only DuckDB connection.
    :param comparison_type: ``'binding'`` or ``'perturbation'``.
    :returns: db_name -> label, in display order.

    """
    ph = ", ".join(["?"] * len(AGREEMENT_EXCLUDED))
    sql = f"""
    SELECT r.db_name,
           {_AGREEMENT_LABEL_SQL} AS agreement_label
    FROM dataset_registry r
    LEFT JOIN promoter_sets ps ON r.promoter_set_id = ps.promoter_set_id
    WHERE r.data_type = ?
      AND r.db_name NOT IN ({ph})
    ORDER BY COALESCE(r.primary_db_name, r.db_name),
             CASE WHEN r.binding_method_id = 'peak_calling' THEN 1 ELSE 0 END,
             CASE r.promoter_set_id
                 WHEN 'kang' THEN 0 WHEN 'mindel' THEN 1
                 WHEN '500bp' THEN 2 WHEN 'intergenic' THEN 3 ELSE 4 END,
             r.db_name
    """
    df = conn.execute(sql, [comparison_type] + sorted(AGREEMENT_EXCLUDED)).df()
    return dict(zip(df["db_name"], df["agreement_label"]))


def fetch_agreement(
    conn: duckdb.DuckDBPyConnection,
    comparison_type: str,
    db_names: list[str],
    filters: dict | None = None,
) -> pd.DataFrame:
    """
    Top-N overlap enrichment between same-type datasets, for figure 6.

    Enrichment is ``log2(n_intersect * GENE_UNIVERSE / (n_a * n_b))``: the observed
    overlap over the ``(n_a / #genes) * n_b`` expected by chance. A half-count
    pseudo-count stands in for a zero overlap, which would otherwise be ``-inf``.

    The expectation uses the *observed* set sizes rather than ``top_n^2``. They differ
    whenever a dataset has fewer than ``top_n`` targets for a regulator -- rarely for
    promoter enrichment, routinely for peak calling, where the set size is whatever the
    caller returned. Dividing a 30-target peak set by ``500^2`` would understate its
    enrichment roughly 16-fold, and worsen with N, which is exactly where the curve is
    read.

    Each unordered dataset pair appears once, and per-regulator values are the median
    across sample pairs. Both sides are restricted to each dataset's filtered samples, so
    a regulator's default sample -- not its heat-shock or non-standard-condition repeats
    -- is what is compared.

    :param conn: Read-only DuckDB connection.
    :param comparison_type: ``'binding'`` or ``'perturbation'``.
    :param db_names: Datasets to include.
    :param filters: Per-dataset sample filters, keyed by db_name.
    :returns: Columns ``pair``, ``db_a``, ``db_b``, ``regulator_locus_tag``,
        ``top_n``, ``log2_enrichment``.

    """
    if len(db_names) < 2:
        return pd.DataFrame()
    filters = filters or {}
    a_clause, a_params = per_dataset_sample_clause(
        conn, db_names, filters, "da.db_name", "split_part(g.source_sample_a, ';', 3)"
    )
    b_clause, b_params = per_dataset_sample_clause(
        conn, db_names, filters, "db.db_name", "split_part(g.source_sample_b, ';', 3)"
    )
    ph = ", ".join(["?"] * len(db_names))
    sql = f"""
    WITH d AS (
        SELECT r.db_name,
               {_AGREEMENT_LABEL_SQL} AS agreement_label,
               r.hf_repo || ';' || r.hf_config || ';' AS prefix
        FROM dataset_registry r
        LEFT JOIN promoter_sets ps ON r.promoter_set_id = ps.promoter_set_id
        WHERE r.db_name IN ({ph})
    )
    SELECT da.db_name AS db_a,
           db.db_name AS db_b,
           da.agreement_label || ' vs ' || db.agreement_label AS pair,
           g.regulator_locus_tag,
           g.top_n,
           median(
               log2(
                   (GREATEST(g.n_intersect, 0.5) * {GENE_UNIVERSE})
                   / (GREATEST(g.n_a, 1)::DOUBLE * GREATEST(g.n_b, 1))
               )
           ) AS log2_enrichment
    FROM topn_agreement g
    JOIN d da ON g.source_sample_a LIKE da.prefix || '%'
    JOIN d db ON g.source_sample_b LIKE db.prefix || '%'
    WHERE g.comparison_type = ?{a_clause}{b_clause}
    GROUP BY da.db_name, db.db_name, da.agreement_label, db.agreement_label,
             g.regulator_locus_tag, g.top_n
    ORDER BY pair, g.regulator_locus_tag, g.top_n
    """
    return conn.execute(sql, db_names + [comparison_type] + a_params + b_params).df()


def _target_set_prefix(conn: duckdb.DuckDBPyConnection, db_name: str) -> str:
    """
    The ``source_sample`` prefix (``repo;config;``) identifying one dataset.

    :param conn: Read-only DuckDB connection.
    :param db_name: Dataset db_name.
    :returns: The prefix, or ``""`` when the dataset is not in the registry.

    """
    row = conn.execute(
        "SELECT hf_repo || ';' || hf_config || ';' FROM dataset_registry"
        " WHERE db_name = ?",
        [db_name],
    ).fetchone()
    return str(row[0]) if row else ""


def fetch_shared_targets(
    conn: duckdb.DuckDBPyConnection,
    comparison_type: str,
    db_names: list[str],
    top_n: int,
    filters: dict | None = None,
) -> pd.DataFrame:
    """
    Targets shared within the top N, for every dataset pair, per TF, for figure 10.

    Computed from ``topn_target_sets`` at the requested ``top_n`` rather than read from
    ``topn_agreement``, whose fixed 10-200 grid lacks the sidebar's 25 and 75 -- and
    which would let figure 10's boxes and its Venn disagree. A TF whose two top-N sets
    are disjoint counts as 0, not as missing. Where a TF has several samples in a
    dataset, the median across sample pairs is taken; under the default filters it is
    one sample each.

    Pairs are named, and oriented in sorted ``db_name`` order, exactly as figure 6 names
    them, so a pair has the same label -- and the same colour -- in both figures.

    :param conn: Read-only DuckDB connection.
    :param comparison_type: ``'binding'`` or ``'perturbation'``.
    :param db_names: Datasets to include; every unordered pair among them is returned.
    :param top_n: Rank cutoff, at most the table's stored depth.
    :param filters: Per-dataset sample filters, keyed by db_name.
    :returns: Columns ``pair``, ``regulator_locus_tag``, ``n_shared``.

    """
    if len(db_names) < 2:
        return pd.DataFrame()
    filters = filters or {}
    labels = agreement_dataset_choices(conn, comparison_type)
    frames: list[pd.DataFrame] = []
    for db_a, db_b in itertools.combinations(sorted(db_names), 2):
        if db_a not in labels or db_b not in labels:
            continue
        fa, pa = sample_filter_clause(
            conn, db_a, filters.get(db_a), "split_part(source_sample, ';', 3)"
        )
        fb, pb = sample_filter_clause(
            conn, db_b, filters.get(db_b), "split_part(source_sample, ';', 3)"
        )
        sql = f"""
        WITH a AS (
            SELECT source_sample, regulator_locus_tag, target_locus_tag
            FROM topn_target_sets
            WHERE source_sample LIKE ? || '%' AND rnk <= ?{fa}
        ),
        b AS (
            SELECT source_sample, regulator_locus_tag, target_locus_tag
            FROM topn_target_sets
            WHERE source_sample LIKE ? || '%' AND rnk <= ?{fb}
        ),
        sa AS (SELECT DISTINCT source_sample, regulator_locus_tag FROM a),
        sb AS (SELECT DISTINCT source_sample, regulator_locus_tag FROM b),
        inter AS (
            SELECT a.source_sample AS sample_a, b.source_sample AS sample_b,
                   a.regulator_locus_tag, count(*) AS n
            FROM a JOIN b
              ON  b.regulator_locus_tag = a.regulator_locus_tag
              AND b.target_locus_tag    = a.target_locus_tag
            GROUP BY a.source_sample, b.source_sample, a.regulator_locus_tag
        )
        SELECT sa.regulator_locus_tag,
               median(COALESCE(i.n, 0)) AS n_shared
        FROM sa
        JOIN sb ON sb.regulator_locus_tag = sa.regulator_locus_tag
        LEFT JOIN inter i
          ON  i.sample_a = sa.source_sample
          AND i.sample_b = sb.source_sample
          AND i.regulator_locus_tag = sa.regulator_locus_tag
        GROUP BY sa.regulator_locus_tag
        ORDER BY sa.regulator_locus_tag
        """
        df = conn.execute(
            sql,
            [_target_set_prefix(conn, db_a), top_n]
            + pa
            + [_target_set_prefix(conn, db_b), top_n]
            + pb,
        ).df()
        df.insert(0, "pair", f"{labels[db_a]} vs {labels[db_b]}")
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def fetch_target_sets(
    conn: duckdb.DuckDBPyConnection,
    db_names: list[str],
    regulator: str,
    top_n: int,
    filters: dict | None = None,
) -> dict[str, set[str]]:
    """
    One regulator's top-N target set in each dataset, for figure 10's Venn.

    Under the default filters each dataset has exactly one sample per regulator. If the
    filters leave several, the lowest ``source_sample`` is used, so the circle is still
    a single real top-N list of ``top_n`` targets rather than a union that overshoots.

    :param conn: Read-only DuckDB connection.
    :param db_names: Datasets to read.
    :param regulator: Regulator locus tag.
    :param top_n: Rank cutoff.
    :param filters: Per-dataset sample filters, keyed by db_name.
    :returns: db_name -> target locus tags; empty when the regulator is absent.

    """
    filters = filters or {}
    out: dict[str, set[str]] = {}
    for db in db_names:
        clause, params = sample_filter_clause(
            conn, db, filters.get(db), "split_part(source_sample, ';', 3)"
        )
        prefix = _target_set_prefix(conn, db)
        rows = conn.execute(
            f"""
            WITH s AS (
                SELECT source_sample, target_locus_tag, rnk
                FROM topn_target_sets
                WHERE source_sample LIKE ? || '%' AND regulator_locus_tag = ?{clause}
            )
            SELECT target_locus_tag FROM s
            WHERE source_sample = (SELECT min(source_sample) FROM s) AND rnk <= ?
            """,
            [prefix, regulator] + params + [top_n],
        ).fetchall()
        out[db] = {r[0] for r in rows}
    return out


def weighted_agreement(
    df: pd.DataFrame, half_life: int = AGREEMENT_HALF_LIFE_DEFAULT
) -> pd.DataFrame:
    """
    Collapse each TF's enrichment curve to one number with exponential weighting.

    Each cutoff is weighted ``2 ** (-N / half_life)``, so ``half_life`` is the increase
    in N over which a cutoff's influence halves, expressed in the same units as N. The
    weights are then normalised to sum to 1 **within each (pair, regulator) group** --
    one dataset pair's enrichment curve for one TF, e.g. Calling Cards vs ChEC-seq for
    CBF1 -- so the result is a weighted *mean* on the same scale as ``log2_enrichment``
    rather than a weighted sum that shrinks or grows with ``half_life`` for reasons
    unrelated to agreement. Every group in the current cutoff grid (10-200 by 10) has
    all 20 cutoffs, so in practice this normalises identically across groups; per-group
    normalisation is kept regardless because it costs nothing and stays correct if a
    group is ever missing cutoffs (e.g. a sparser grid, or a regulator absent from one
    side of the LEFT JOIN in ``topn_agreement``).

    This replaces a ``1/N`` weighting, whose decay was fixed by the choice of units and
    could not be tuned. Exponential decay makes the emphasis an explicit parameter: at
    ``half_life = 10`` the smallest cutoff carries about half the mass, while at 200 the
    weighting is nearly flat across the 10-200 grid.

    :param df: Output of :func:`fetch_agreement`.
    :param half_life: Increase in N over which a cutoff's weight halves. Must be
        positive.
    :returns: Columns ``pair``, ``regulator_locus_tag``, ``weighted_enrichment``.
    :raises ValueError: If ``half_life`` is not positive.

    """
    if half_life <= 0:
        raise ValueError(f"half_life must be positive, got {half_life}")
    if df.empty:
        return pd.DataFrame()
    w = df.assign(weight=np.exp2(-df["top_n"] / float(half_life)))
    grouped = w.groupby(["pair", "regulator_locus_tag"], as_index=False).apply(
        lambda g: pd.Series(
            {
                "weighted_enrichment": (
                    (g["log2_enrichment"] * g["weight"]).sum() / g["weight"].sum()
                )
            }
        ),
        include_groups=False,
    )
    return grouped.reset_index(drop=True)
