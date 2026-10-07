# flake8: noqa
"""SQL queries for the Comparison (DTO / Top-N by Binding) module."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import duckdb
import pandas as pd

from tfbpshiny.datasets import (
    DEFAULT_TOP_N,
    DTO_PVALUE_THRESHOLD,
    METHOD_LEVELS,
    PROMOTER_SET_LEVELS,
    TOP_N_CHOICES,
)
from tfbpshiny.utils.corr_query import get_filtered_sample_ids

_perf_logger = logging.getLogger("shiny.perf")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Display label for each ``promoter_sets.promoter_set_id``.
PROMOTER_SET_LABELS: dict[str, str] = {
    "kang": "Kang",
    "mindel": "Mindel",
    "500bp": "500bp",
    "intergenic": "Intergenic",
    "peaks": "Peaks",
    "array": "Array Probes",
}

#: Display label for each ``binding_methods.binding_method_id``.
BINDING_METHOD_LABELS: dict[str, str] = {
    "promoter_enrichment": "Promoter Enrichment",
    "peak_calling": "Peak Calling",
}

#: Color per binding method, used for column/row headers.
BINDING_METHOD_COLORS: dict[str, str] = {
    "promoter_enrichment": "#4DBBD5",
    "peak_calling": "#E64B35",
}

#: Peak caller used for each primary binding dataset's promoter-set-matched peak
#: calls, surfaced as a tooltip on the "Peak Calling" row of the Method
#: Comparison tab.
PEAK_CALLER_NOTES: dict[str, str] = {
    "rossi": (
        "Peaks called with MACS, then intersected with each promoter set."
        " Targets are ranked by the maximum -log10(q) of the peaks falling in"
        " the promoter."
    ),
    "chec_m2025": (
        "Peaks called with HOMER, replicating the peak-calling method used in"
        " the reference publication, then intersected with each promoter set."
        " A peak is kept when it appears in at least two replicates; targets"
        " are ranked by the maximum peak score in the promoter."
    ),
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
# Binding dataset index (derived from dataset_registry)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BindingIndex:
    """
    Lookup tables decomposing every binding dataset into promoter set x method.

    Built from ``dataset_registry`` rather than hand-maintained dicts so the app
    cannot drift out of sync with the collection YAML. Every field is keyed by
    ``db_name`` except :attr:`by_cell`, which is the reverse lookup the Method
    Comparison tab needs.

    """

    #: db_name -> full display name, e.g. "2021 ChIP-exo (Rossi, Mindel)".
    label: dict[str, str]
    #: db_name -> base label shared by all variants, e.g. "2021 ChIP-exo".
    base_label: dict[str, str]
    #: db_name -> promoter set display label, e.g. "Mindel".
    promoter_set: dict[str, str]
    #: db_name -> raw promoter_set_id, e.g. "mindel".
    promoter_set_id: dict[str, str]
    #: db_name -> binding method display label, e.g. "Promoter Enrichment".
    method: dict[str, str]
    #: db_name -> raw binding_method_id, e.g. "promoter_enrichment".
    method_id: dict[str, str]
    #: db_name -> its primary db_name (a primary dataset maps to itself).
    primary: dict[str, str]
    #: (primary, promoter_set_id, method_id) -> db_name.
    by_cell: dict[tuple[str, str, str], str]

    def resolve(self, primary: str, promoter_set_id: str, method_id: str) -> str | None:
        """
        Return the db_name for one promoter-set x method cell, if it exists.

        :param primary: Primary binding db_name, e.g. ``"rossi"``.
        :param promoter_set_id: Raw promoter set id, e.g. ``"mindel"``.
        :param method_id: Raw binding method id, e.g. ``"peak_calling"``.
        :returns: The matching db_name, or ``None`` when that combination was
            not materialized.

        """
        return self.by_cell.get((primary, promoter_set_id, method_id))

    def has_promoter_variants(self, primary: str) -> bool:
        """
        Whether a dataset's regions are a selectable promoter definition.

        ``False`` for datasets whose regions are fixed by the assay platform --
        Harbison's microarray probes, or a publication's own peak regions. Those have
        no promoter-set variants and cannot acquire any, so the promoter-set selector
        does not apply to them and must not filter them away.

        :param primary: Primary binding db_name.
        :returns: ``True`` when the dataset sits on a real promoter definition.

        """
        return self.promoter_set_id.get(primary, "") in PROMOTER_SET_LEVELS

    def resolve_or_self(
        self, primary: str, promoter_set_id: str, method_id: str
    ) -> str | None:
        """
        Resolve a cell, falling back to the dataset itself when no promoter applies.

        Used where the promoter-set selector filters a list of datasets. A
        platform-fixed dataset matches every promoter set, since the choice is not
        one it can express -- but only for its own method, so asking for peaks still
        excludes a dataset that has none.

        :param primary: Primary binding db_name.
        :param promoter_set_id: Raw promoter set id.
        :param method_id: Raw binding method id.
        :returns: The matching db_name, or ``None``.

        """
        db = self.resolve(primary, promoter_set_id, method_id)
        if db:
            return db
        if not self.has_promoter_variants(primary) and (
            self.method_id.get(primary) == method_id
        ):
            return primary
        return None

    def promoter_sets_with_both_methods(self, primary: str) -> list[str]:
        """
        Return promoter set ids having both a promoter-enrichment and a peak dataset.

        :param primary: Primary binding db_name.
        :returns: Promoter set ids in :data:`PROMOTER_SET_LEVELS` order.

        """
        return [
            ps
            for ps in PROMOTER_SET_LEVELS
            if all(self.resolve(primary, ps, m) for m in METHOD_LEVELS)
        ]

    def supports_method_comparison(self, primary: str) -> bool:
        """
        Whether a dataset can appear in the Method Comparison tab.

        :param primary: Primary binding db_name.
        :returns: ``True`` when at least one promoter set has both methods.

        """
        return bool(self.promoter_sets_with_both_methods(primary))


def build_binding_index(registry_df: pd.DataFrame) -> BindingIndex:
    """
    Build a :class:`BindingIndex` from ``dataset_registry`` rows.

    Takes a DataFrame rather than a connection so it can be unit tested without
    a database. Rows whose ``data_type`` is not ``binding`` are ignored.

    :param registry_df: ``dataset_registry`` rows with columns ``db_name``,
        ``data_type``, ``display_name``, ``base_label``, ``primary_db_name``,
        ``promoter_set_id`` and ``binding_method_id``.
    :returns: Populated index.

    """
    label: dict[str, str] = {}
    base_label: dict[str, str] = {}
    promoter_set: dict[str, str] = {}
    promoter_set_id: dict[str, str] = {}
    method: dict[str, str] = {}
    method_id: dict[str, str] = {}
    primary: dict[str, str] = {}
    by_cell: dict[tuple[str, str, str], str] = {}

    binding = registry_df[registry_df["data_type"] == "binding"]
    for row in binding.itertuples(index=False):
        db = str(row.db_name)
        ps_id = "" if pd.isna(row.promoter_set_id) else str(row.promoter_set_id)
        m_id = "" if pd.isna(row.binding_method_id) else str(row.binding_method_id)
        prim = db if pd.isna(row.primary_db_name) else str(row.primary_db_name)

        label[db] = str(row.display_name) if pd.notna(row.display_name) else db
        base_label[db] = str(row.base_label) if pd.notna(row.base_label) else db
        promoter_set_id[db] = ps_id
        promoter_set[db] = PROMOTER_SET_LABELS.get(ps_id, ps_id)
        method_id[db] = m_id
        method[db] = BINDING_METHOD_LABELS.get(m_id, m_id)
        primary[db] = prim

        if ps_id and m_id:
            by_cell[(prim, ps_id, m_id)] = db

    return BindingIndex(
        label=label,
        base_label=base_label,
        promoter_set=promoter_set,
        promoter_set_id=promoter_set_id,
        method=method,
        method_id=method_id,
        primary=primary,
        by_cell=by_cell,
    )


# ---------------------------------------------------------------------------
# DuckDB-based top-N fetch
# ---------------------------------------------------------------------------


def fetch_topn_results(
    conn: duckdb.DuckDBPyConnection,
    pairs: list[tuple[str, str]],
    filters: dict[str, Any],
    top_n: int,
    preset: dict[str, tuple[float, float]],
    require_full_overlap: bool = True,
) -> pd.DataFrame:
    """
    Fetch pre-computed topn_results for all (binding, perturbation) pairs.

    Reads from the pre-materialized ``topn_results`` table, filtering by the
    materialized top_n, effect_threshold, pvalue_threshold, and sample IDs derived
    from dataset-level filters via ``{db_name}_meta`` subqueries.

    :param conn: Read-only DuckDB connection.
    :param pairs: List of (binding_db, perturbation_db) tuples.
    :param filters: Active filter dict keyed by dataset name.
    :param top_n: Number of top binding targets per binding sample (must match
        what was materialized).
    :param preset: Per-dataset responsiveness thresholds; see
        :data:`~tfbpshiny.utils.vdb_init.DEFAULT_RESPONSIVENESS_PRESETS`.
    :param require_full_overlap: When True (default), only include rows whose top-N
        list is complete, ``n >= top_n``. ``n`` is the number of targets that passed the
        tie rule (a tie group counts only if its *average* rank is within N), so this
        removes a regulator whose list is short -- too few scored targets, or a large
        tie group around rank N that the rule excluded. Turn it off to keep short
        lists, which are then scored over the ``n`` they have.
    :returns: DataFrame with columns from topn_results plus ``pair_key``
        (``"{b_db}__{p_db}"``).

    """
    if not pairs:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for b_db, p_db in pairs:
        t_pair = time.perf_counter()
        effect_threshold, pvalue_threshold = preset.get(
            p_db, preset.get("*", (0.0, 0.05))
        )
        try:
            row_b = (
                conn.execute(
                    "SELECT hf_repo, hf_config FROM dataset_registry WHERE db_name = ?",
                    [b_db],
                )
                .df()
                .iloc[0]
            )
            row_p = (
                conn.execute(
                    "SELECT hf_repo, hf_config FROM dataset_registry WHERE db_name = ?",
                    [p_db],
                )
                .df()
                .iloc[0]
            )
        except (IndexError, Exception):
            continue
        b_prefix = f"{row_b['hf_repo']};{row_b['hf_config']};"
        p_prefix = f"{row_p['hf_repo']};{row_p['hf_config']};"

        b_ids = get_filtered_sample_ids(conn, b_db, filters.get(b_db))
        p_ids = get_filtered_sample_ids(conn, p_db, filters.get(p_db))

        if not b_ids or not p_ids:
            continue

        phs_b = ", ".join(["?"] * len(b_ids))
        phs_p = ", ".join(["?"] * len(p_ids))
        floor_clause = "AND n >= ?" if require_full_overlap else ""
        sql = f"""
        SELECT
            regulator_locus_tag,
            split_part(binding_source_sample, ';', 3) AS binding_sample_id,
            split_part(perturbation_source_sample, ';', 3) AS perturbation_sample_id,
            n, n_responsive, responsive_ratio, n_intersecting_targets
        FROM topn_results
        WHERE top_n = ?
          AND effect_threshold = ?
          AND pvalue_threshold = ?
          AND binding_source_sample LIKE ?
          AND perturbation_source_sample LIKE ?
          AND split_part(binding_source_sample, ';', 3) IN ({phs_b})
          AND split_part(perturbation_source_sample, ';', 3) IN ({phs_p})
          {floor_clause}
        """
        params: list[Any] = (
            [top_n, effect_threshold, pvalue_threshold, b_prefix + "%", p_prefix + "%"]
            + b_ids
            + p_ids
            + ([top_n] if require_full_overlap else [])
        )
        try:
            df = conn.execute(sql, params).df()
            if not df.empty:
                df["binding_db"] = b_db
                df["perturbation_db"] = p_db
                frames.append(df)
        except Exception:
            pass
        elapsed = round((time.perf_counter() - t_pair) * 1000, 2)
        _perf_logger.info(
            json.dumps(
                {
                    "module": "comparison.queries",
                    "label": "fetch_topn_pair",
                    "kind": "data",
                    "b_db": b_db,
                    "p_db": p_db,
                    "n_b_ids": len(b_ids),
                    "n_p_ids": len(p_ids),
                    "elapsed_ms": elapsed,
                }
            )
        )

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ---------------------------------------------------------------------------
# DTO (direct target overlap)
# ---------------------------------------------------------------------------

#: Metric identifiers for the Comparison sidebar selector.
METRIC_TOPN = "topn"
METRIC_DTO = "dto"

#: Labels for the metric selector.
METRIC_LABELS: dict[str, str] = {
    METRIC_TOPN: "Top-N % responsive",
    METRIC_DTO: "DTO % significant",
}

#: Which perturbation ranking the DTO run used. Coverage is uneven: Hackett and both
#: Hughes sets exist only as `log2fc`, while Kemmeren, Hu and Degron carry both.
DTO_RANKING_COLUMNS: tuple[str, ...] = ("log2fc", "pvalue")
DEFAULT_DTO_RANKING_COLUMN = "log2fc"


def fetch_dto_results(
    conn: duckdb.DuckDBPyConnection,
    pairs: list[tuple[str, str]],
    filters: dict[str, Any],
    pr_ranking_column: str = DEFAULT_DTO_RANKING_COLUMN,
    pvalue_threshold: float = DTO_PVALUE_THRESHOLD,
) -> pd.DataFrame:
    """
    Fetch the DTO significance rate for each (binding, perturbation) pair.

    The metric is::

        100 * (regulators with dto_empirical_pvalue < threshold)
            / (regulators present in BOTH datasets)

    The denominator is the **full metadata-level intersect**, taken from
    ``sample_regulator`` and restricted to the samples surviving ``filters`` -- not
    DTO's own coverage. DTO does not test every regulator in the intersect (e.g.
    414 of 446 for ``rossi_peaks_kang`` x ``kemmeren``), so untested regulators count
    as non-significant. ``n_covered`` is returned alongside so that gap stays visible.

    A regulator counts once: significant if **any** of its rows clears the threshold.
    That matters mostly for Hackett, which contributes several rows per regulator
    (one per timepoint); under ``log2fc`` most pairs have ~1 row per regulator.

    :param conn: Read-only DuckDB connection.
    :param pairs: List of (binding_db, perturbation_db) tuples.
    :param filters: Active filter dict keyed by dataset name.
    :param pr_ranking_column: Which DTO ranking variant to read.
    :param pvalue_threshold: Empirical p-value cutoff.
    :returns: One row per pair with ``binding_db``, ``perturbation_db``,
        ``n_significant``, ``n_covered``, ``n_intersect`` and ``percent_significant``.
        Pairs with an empty intersect are omitted.

    """
    if not pairs:
        return pd.DataFrame()

    frames: list[dict[str, Any]] = []
    for b_db, p_db in pairs:
        t_pair = time.perf_counter()
        b_ids = get_filtered_sample_ids(conn, b_db, filters.get(b_db))
        p_ids = get_filtered_sample_ids(conn, p_db, filters.get(p_db))
        if not b_ids or not p_ids:
            continue

        phs_b = ", ".join(["?"] * len(b_ids))
        phs_p = ", ".join(["?"] * len(p_ids))
        sql = f"""
        WITH b_reg AS (
            SELECT DISTINCT regulator_locus_tag
            FROM sample_regulator
            WHERE db_name = ? AND sample_id IN ({phs_b})
        ),
        p_reg AS (
            SELECT DISTINCT regulator_locus_tag
            FROM sample_regulator
            WHERE db_name = ? AND sample_id IN ({phs_p})
        ),
        shared AS (
            SELECT regulator_locus_tag FROM b_reg
            INTERSECT
            SELECT regulator_locus_tag FROM p_reg
        ),
        tested AS (
            SELECT regulator_locus_tag,
                   min(dto_empirical_pvalue) AS best_pvalue
            FROM dto
            WHERE binding_db = ? AND perturbation_db = ?
              AND pr_ranking_column = ?
              AND binding_sample_id IN ({phs_b})
              AND perturbation_sample_id IN ({phs_p})
            GROUP BY regulator_locus_tag
        )
        SELECT
            (SELECT count(*) FROM shared)                                AS n_intersect,
            (SELECT count(*) FROM tested
              WHERE regulator_locus_tag IN (SELECT regulator_locus_tag FROM shared))
                                                                         AS n_covered,
            (SELECT count(*) FROM tested
              WHERE best_pvalue < ?
                AND regulator_locus_tag IN (SELECT regulator_locus_tag FROM shared))
                                                                         AS n_significant
        """
        params: list[Any] = (
            [b_db]
            + b_ids
            + [p_db]
            + p_ids
            + [b_db, p_db, pr_ranking_column]
            + b_ids
            + p_ids
            + [pvalue_threshold]
        )
        try:
            row = conn.execute(sql, params).df().iloc[0]
        except Exception:
            continue

        n_intersect = int(row["n_intersect"])
        if n_intersect == 0:
            continue
        n_significant = int(row["n_significant"])
        frames.append(
            {
                "binding_db": b_db,
                "perturbation_db": p_db,
                "n_significant": n_significant,
                "n_covered": int(row["n_covered"]),
                "n_intersect": n_intersect,
                "percent_significant": 100.0 * n_significant / n_intersect,
            }
        )
        _perf_logger.info(
            json.dumps(
                {
                    "module": "comparison.queries",
                    "label": "fetch_dto_pair",
                    "binding_db": b_db,
                    "perturbation_db": p_db,
                    "elapsed_ms": round((time.perf_counter() - t_pair) * 1000, 2),
                }
            )
        )

    return pd.DataFrame(frames)


def fetch_dto_results_method_intersected(
    conn: duckdb.DuckDBPyConnection,
    cells: list[tuple[str, str, str]],
    filters: dict[str, Any],
    pr_ranking_column: str = DEFAULT_DTO_RANKING_COLUMN,
    pvalue_threshold: float = DTO_PVALUE_THRESHOLD,
) -> pd.DataFrame:
    """
    Like :func:`fetch_dto_results`, but for the Compare Analysis Methods tab: DTO
    significance is pre-computed entirely externally, so a regulator peak_calling never
    called a peak for can never get a real empirical p-value. As in the top-N tables,
    such a regulator is left out rather than scored as zero: each sibling
    ``(promoter_enrichment, peak_calling)`` pair at the same promoter set shares one
    3-way-intersected regulator universe (promoter_enrichment regs x peak_calling regs x
    perturbation regs) as their common denominator, so the two bars stay directly
    comparable rather than each drawing its own, unevenly-sized, pairwise intersection
    with the perturbation dataset.

    :param conn: Read-only DuckDB connection.
    :param cells: ``(pe_db, pc_db, p_db)`` triples -- both binding variants must be
        resolved by the caller; there is no fallback to a plain pairwise intersection
        here (see :func:`fetch_dto_results` for that).
    :param filters: Active filter dict keyed by dataset name.
    :param pr_ranking_column: Which DTO ranking variant to read.
    :param pvalue_threshold: Empirical p-value cutoff.
    :returns: Two rows per cell (one per method) with ``binding_db``,
        ``perturbation_db``, ``n_significant``, ``n_covered``, ``n_intersect`` and
        ``percent_significant``. Cells with an empty 3-way intersect are omitted.

    """
    if not cells:
        return pd.DataFrame()

    frames: list[dict[str, Any]] = []
    for pe_db, pc_db, p_db in cells:
        pe_ids = get_filtered_sample_ids(conn, pe_db, filters.get(pe_db))
        pc_ids = get_filtered_sample_ids(conn, pc_db, filters.get(pc_db))
        p_ids = get_filtered_sample_ids(conn, p_db, filters.get(p_db))
        if not pe_ids or not pc_ids or not p_ids:
            continue

        phs_pe = ", ".join(["?"] * len(pe_ids))
        phs_pc = ", ".join(["?"] * len(pc_ids))
        phs_p = ", ".join(["?"] * len(p_ids))
        universe_df = conn.execute(
            f"""
            WITH pe_reg AS (
                SELECT DISTINCT regulator_locus_tag FROM sample_regulator
                WHERE db_name = ? AND sample_id IN ({phs_pe})
            ),
            pc_reg AS (
                SELECT DISTINCT regulator_locus_tag FROM sample_regulator
                WHERE db_name = ? AND sample_id IN ({phs_pc})
            ),
            p_reg AS (
                SELECT DISTINCT regulator_locus_tag FROM sample_regulator
                WHERE db_name = ? AND sample_id IN ({phs_p})
            )
            SELECT regulator_locus_tag FROM pe_reg
            INTERSECT SELECT regulator_locus_tag FROM pc_reg
            INTERSECT SELECT regulator_locus_tag FROM p_reg
            """,
            [pe_db, *pe_ids, pc_db, *pc_ids, p_db, *p_ids],
        ).df()
        universe = universe_df["regulator_locus_tag"].tolist()
        n_intersect = len(universe)
        if n_intersect == 0:
            continue
        phs_u = ", ".join(["?"] * n_intersect)

        for b_db, b_ids in ((pe_db, pe_ids), (pc_db, pc_ids)):
            phs_b = ", ".join(["?"] * len(b_ids))
            sql = f"""
            WITH tested AS (
                SELECT regulator_locus_tag, min(dto_empirical_pvalue) AS best_pvalue
                FROM dto
                WHERE binding_db = ? AND perturbation_db = ?
                  AND pr_ranking_column = ?
                  AND binding_sample_id IN ({phs_b})
                  AND perturbation_sample_id IN ({phs_p})
                  AND regulator_locus_tag IN ({phs_u})
                GROUP BY regulator_locus_tag
            )
            SELECT
                count(*) AS n_covered,
                count(*) FILTER (WHERE best_pvalue < ?) AS n_significant
            FROM tested
            """
            params: list[Any] = (
                [b_db, p_db, pr_ranking_column]
                + b_ids
                + p_ids
                + universe
                + [pvalue_threshold]
            )
            try:
                row = conn.execute(sql, params).df().iloc[0]
            except Exception:
                continue
            n_significant = int(row["n_significant"])
            frames.append(
                {
                    "binding_db": b_db,
                    "perturbation_db": p_db,
                    "n_significant": n_significant,
                    "n_covered": int(row["n_covered"]),
                    "n_intersect": n_intersect,
                    "percent_significant": 100.0 * n_significant / n_intersect,
                }
            )
    return pd.DataFrame(frames)


# ---------------------------------------------------------------------------
# Method x promoter-set model (materialized by materialize/comparison/
# method_promoter_model.py -- this module only reads the precomputed tables)
# ---------------------------------------------------------------------------


def fetch_method_promoter_target_universe(
    conn: duckdb.DuckDBPyConnection,
) -> pd.DataFrame:
    """
    Read the per-assay target-universe sizes the model's panel is restricted to.

    Populated once, offline, by ``tfbpshiny materialize`` (see
    ``materialize/comparison/method_promoter_model.py::promoter_set_target_universe``)
    -- the intersection, across all four promoter sets' promoter-enrichment views, of
    each assay's target list. Every cell of the panel (both methods, all four promoter
    sets) is ranked over this same restricted pool, so a reader needs to see how large
    it actually is per assay to judge how much each promoter set's own full target list
    was cut down.

    :param conn: Read-only DuckDB connection.
    :returns: Columns ``assay_primary``, ``display_name``, ``n_targets``, one row per
        assay, ``display_name`` falling back to ``assay_primary`` when the registry
        has none.

    """
    return conn.execute(
        "SELECT u.assay_primary,"
        " COALESCE(r.display_name, u.assay_primary) AS display_name,"
        " u.n_targets"
        " FROM method_promoter_model_target_universe u"
        " LEFT JOIN dataset_registry r ON r.db_name = u.assay_primary"
        " ORDER BY u.assay_primary"
    ).df()


def fetch_method_promoter_model(
    conn: duckdb.DuckDBPyConnection,
    perturbation_db: str,
    top_n: int,
    preset_name: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Read the precomputed method x promoter-set model for one (dataset, N, preset).

    The model itself is fit once, offline, by ``tfbpshiny materialize`` -- see
    ``materialize/comparison/method_promoter_model.py`` for the design (a pooled OLS
    with regulator and assay fixed effects, cluster-robust standard errors by
    regulator). This is a plain filtered read against the two resulting tables; no
    fitting happens here.

    :param conn: Read-only DuckDB connection.
    :param perturbation_db: Perturbation dataset db_name.
    :param top_n: Materialized cutoff.
    :param preset_name: Responsiveness preset name (``'Relaxed'`` or ``'Stringent'``).
    :returns: ``(coefs, fit_summary)``, each filtered to this one
        (perturbation_db, top_n, preset_name).

    """
    params = [perturbation_db, top_n, preset_name]
    coefs = conn.execute(
        "SELECT term, estimate, std_error, t_value, p_value"
        " FROM method_promoter_model_coefs"
        " WHERE perturbation_db = ? AND top_n = ? AND criteria = ?",
        params,
    ).df()
    fit_summary = conn.execute(
        "SELECT n_obs, n_regulators, r_squared, converged, note"
        " FROM method_promoter_model_fit_summary"
        " WHERE perturbation_db = ? AND top_n = ? AND criteria = ?",
        params,
    ).df()
    return coefs, fit_summary
