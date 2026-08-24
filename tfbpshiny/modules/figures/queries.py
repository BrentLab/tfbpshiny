# flake8: noqa
"""
Data access for the Figures module.

Every function here reads the materialized DuckDB directly and returns a tidy DataFrame;
no reactive code lives in this file.

"""

from __future__ import annotations

import duckdb
import pandas as pd

from tfbpshiny.materialize.comparison.agreement import AGREEMENT_EXCLUDED
from tfbpshiny.utils.corr_query import get_filtered_sample_ids
from tfbpshiny.utils.vdb_init import DEFAULT_RESPONSIVENESS_PRESETS

#: Binding datasets shown in the figures, in display order. These are the *primary*
#: db_names -- the promoter-set and peak variants are not separate figure series.
BINDING_ORDER: tuple[str, ...] = ("harbison", "callingcards", "rossi", "chec_m2025")

#: Perturbation datasets shown, in display order.
PR_ORDER: tuple[str, ...] = ("kemmeren", "hackett", "degron")

#: Binding datasets that have DTO results. Harbison has **zero** DTO rows -- the
#: upstream analysis covers 22 binding datasets and none of them is ChIP-chip -- so
#: the DTO figures are necessarily three-wide rather than four.
DTO_BINDING_ORDER: tuple[str, ...] = ("callingcards", "rossi", "chec_m2025")

#: Empirical p-value below which a regulator counts as DTO-significant.
DTO_PVALUE_THRESHOLD = 0.01

#: The only ranking variant present for all six perturbation datasets.
DTO_RANKING_COLUMN = "log2fc"

#: Sentinel ``top_n`` meaning "every authors'-bound target, no rank cutoff".
TOP_N_ALL = 0

#: Binding datasets carrying the authors' own binary call. Harbison and Calling Cards
#: have p-value columns but no cutoff documented in any datacard, so they are excluded
#: from the authors'-threshold figure rather than given an invented threshold.
AUTHORS_PEAK_BINDING: tuple[str, ...] = ("rossi_peaks", "chec_m2025_peaks")

#: Gene universe for the random-overlap expectation, matching the materializer.
GENE_UNIVERSE = 6000

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

#: Compact per-dataset label for figure 6, e.g. "2021 ChIP-exo 500 bp peaks".
#:
#: ``base_label`` alone is ambiguous once variants are selectable -- every Rossi
#: variant shares "2021 ChIP-exo", so a promoter-set comparison would read
#: "2021 ChIP-exo vs 2021 ChIP-exo". ``display_name`` is unambiguous but far too long
#: for a legend entry, so the qualifiers are appended directly.
_AGREEMENT_LABEL_SQL = """
        r.base_label
        || COALESCE(' ' || ps.display_name, '')
        || CASE WHEN r.binding_method_id = 'peak_calling' THEN ' peaks' ELSE '' END
"""


#: Above this many dataset pairs the figure's lines and boxes stop being separable.
#: Selecting more is allowed; the UI says what it costs.
AGREEMENT_PAIR_WARN = 12


def _sample_filter_clause(
    conn: duckdb.DuckDBPyConnection,
    db_name: str,
    filters: dict | None,
    column: str,
) -> tuple[str, list]:
    """
    Build a SQL fragment restricting ``column`` to the samples passing ``filters``.

    Without this, a dataset's samples are pooled indiscriminately -- Hackett would
    contribute all 1,543 timepoint samples rather than the 193 at the default 45 min
    timepoint, which materially changes every figure that medians across samples.

    Returns ``("", [])`` when the dataset has no filter, so callers can splice the
    fragment in unconditionally.

    :param conn: Read-only DuckDB connection.
    :param db_name: Dataset whose ``{db_name}_meta`` supplies the sample ids.
    :param filters: Filter spec for this dataset, or ``None``.
    :param column: SQL expression yielding the sample id to constrain.
    :returns: ``(sql_fragment, params)``.

    """
    if not filters:
        return "", []
    ids = get_filtered_sample_ids(conn, db_name, filters)
    if not ids:
        # An empty allow-list means nothing passes; make that explicit rather than
        # silently dropping the restriction.
        return " AND FALSE", []
    return f" AND {column} IN ({', '.join(['?'] * len(ids))})", ids


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

    :param conn: Read-only DuckDB connection.
    :returns: db_name -> base_label.

    """
    df = conn.execute(
        "SELECT db_name, base_label FROM dataset_registry WHERE is_primary"
    ).df()
    return dict(zip(df["db_name"], df["base_label"]))


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

    The x value is ``n``, **not** ``top_n``. The top-N SQL ranks with ``RANK()``, so a
    tie spanning the cutoff lets more than ``top_n`` rows through -- ``n`` is the
    number of targets actually summarised, and is the honest x coordinate.

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
    p_clause, p_params = _sample_filter_clause(
        conn,
        pr_db,
        filters.get(pr_db),
        "split_part(t.perturbation_source_sample, ';', 3)",
    )
    s_clause, s_params = scoring_clause(pr_db, preset_name)
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
    WHERE t.regulator_locus_tag IN ({r_ph}){s_clause}{p_clause}
    GROUP BY b.db_name, t.regulator_locus_tag, t.n
    ORDER BY b.db_name, t.regulator_locus_tag, t.n
    """
    return conn.execute(
        sql, binding_dbs + [pr_db] + regulators + s_params + p_params
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
    p_clause, p_params = _sample_filter_clause(
        conn,
        pr_db,
        filters.get(pr_db),
        "split_part(t.perturbation_source_sample, ';', 3)",
    )
    s_clause, s_params = scoring_clause(pr_db, preset_name)
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
    WHERE t.top_n = ? AND t.regulator_locus_tag IN ({r_ph}){s_clause}{p_clause}
    GROUP BY b.db_name, t.regulator_locus_tag
    """
    return conn.execute(
        sql,
        binding_dbs + [pr_db, top_n] + regulators + s_params + p_params,
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
    "AGREEMENT_DEFAULT_PERTURBATION",
    "AGREEMENT_PAIR_WARN",
    "agreement_dataset_choices",
    "fetch_agreement",
    "fetch_authors_bound",
    "has_top_n",
    "table_exists",
    "weighted_agreement",
    "DTO_BINDING_ORDER",
    "DTO_PVALUE_THRESHOLD",
    "DTO_RANKING_COLUMN",
    "PR_ORDER",
    "dataset_labels",
    "fetch_dto_significance",
    "fetch_dto_significant_sets",
    "fetch_rank_response",
    "fetch_topn_percent_responsive",
    "regulator_intersection",
    "scoring_clause",
]


# ---------------------------------------------------------------------------
# Figures 3 and 6 -- require the Phase 2 materialization
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
    p_clause, p_params = _sample_filter_clause(
        conn,
        pr_db,
        filters.get(pr_db),
        "split_part(t.perturbation_source_sample, ';', 3)",
    )
    s_clause, s_params = scoring_clause(pr_db, preset_name)
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
    WHERE t.top_n = ?{s_clause}{p_clause}
    GROUP BY b.db_name, t.regulator_locus_tag
    """
    return conn.execute(
        sql, binding_dbs + [pr_db, TOP_N_ALL] + s_params + p_params
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
    across sample pairs.

    :param conn: Read-only DuckDB connection.
    :param comparison_type: ``'binding'`` or ``'perturbation'``.
    :param db_names: Datasets to include.
    :returns: Columns ``pair``, ``db_a``, ``db_b``, ``regulator_locus_tag``,
        ``top_n``, ``log2_enrichment``.

    """
    if len(db_names) < 2:
        return pd.DataFrame()
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
    WHERE g.comparison_type = ?
    GROUP BY da.db_name, db.db_name, da.agreement_label, db.agreement_label,
             g.regulator_locus_tag, g.top_n
    ORDER BY pair, g.regulator_locus_tag, g.top_n
    """
    return conn.execute(sql, db_names + [comparison_type]).df()


def weighted_agreement(df: pd.DataFrame) -> pd.DataFrame:
    """
    Collapse each TF's enrichment curve to one number with 1/N weighting.

    Weights are ``1/N`` normalised to sum to 1 over the cutoffs actually present, so
    the top of the ranking dominates without introducing a tuning parameter.

    :param df: Output of :func:`fetch_agreement`.
    :returns: Columns ``pair``, ``regulator_locus_tag``, ``weighted_enrichment``.

    """
    if df.empty:
        return pd.DataFrame()
    w = df.assign(weight=1.0 / df["top_n"])
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
