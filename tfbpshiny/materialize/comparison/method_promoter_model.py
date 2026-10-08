"""
Method x promoter-set model: does peak calling vs. promoter enrichment matter, and
does the answer depend on the promoter definition?

A single pooled OLS per ``(perturbation_db, top_n, criteria)``, with regulator identity
and assay entered as fixed effects (``C(regulator_locus_tag)``, ``C(assay, ...)``)
alongside ``method`` and ``promoter_set``, and cluster-robust standard errors by
regulator. This is a plain fixed-effects linear model, not a mixed model: the fixed
effect for regulator holds each TF's own baseline responsiveness constant while
estimating the method/promoter-set/assay contrasts, and the cluster-robust standard
errors correct for the fact that a regulator's own rows are correlated. A true
crossed-random-effects version (the R/``glmer`` route, drafted separately for
``hf_yeast_explorer``) would let the regulator effect itself vary by method rather than
just shifting the intercept -- future work, not required here.

``tmp/topn_method_regression.ipynb`` calls these functions to reproduce the app's
tables; it is a consumer of this module, not its source.

The panel applies ``DEFAULT_DATASET_FILTERS`` (through ``get_filtered_sample_ids``) so
it respects the same default sample selections every Comparison tab applies at query
time. Materialize runs offline with no live session, so it can only ever bake in the
*default* filters, not a user's live in-session change.

The panel's candidate targets are restricted to the cross-promoter-set intersection
(see :func:`promoter_set_target_universe`) rather than reading the shared
``topn_results`` table as-is: a promoter set's own full target list is a peculiarity
of how that promoter set is defined (a wider window picks up more annotated features),
not a real difference in binding, so comparing raw top-N ranks across promoter sets
without first equalizing the candidate pool would confound the method/promoter-set
contrast with that artifact. The coordinator computes this model's own top-N staging
table (``method_promoter_model_topn``) restricted to that intersection, ranking only
over the 16 cells this model needs -- it deliberately does not touch the shared
``topn_results`` pipeline in ``topn.py``, so every other Comparison tab and Figure
keeps its existing, unrestricted numbers.

"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import statsmodels.formula.api as smf

from tfbpshiny.datasets import METHOD_LEVELS, PROMOTER_SET_LEVELS
from tfbpshiny.utils.corr_query import (
    expand_filters_to_variants,
    get_filtered_sample_ids,
    sample_in_clause,
)
from tfbpshiny.utils.vdb_init import DEFAULT_DATASET_FILTERS

logger = logging.getLogger("shiny")

#: The two assays that have both a promoter-enrichment and a promoter-set-matched
#: peak-calling arm. Calling Cards has no peak-calling arm (excluded: would unbalance
#: the method contrast and contributes nothing to the interaction); Harbison's regions
#: are microarray probes with no re-quantifiable window (`promoter_set_id='array'`).
ASSAY_PRIMARIES: tuple[str, ...] = ("rossi_500bp", "chec_m2025_500bp")

#: Minimum distinct regulators required to fit -- below this a regulator fixed effect
#: and cluster-robust SEs are not meaningful.
MIN_REGULATORS = 2

#: Column order matching each table's DDL, for the coordinator's positional
#: ``INSERT INTO ... SELECT *``.
COEFS_COLUMNS: tuple[str, ...] = (
    "perturbation_db",
    "top_n",
    "criteria",
    "term",
    "estimate",
    "std_error",
    "t_value",
    "p_value",
)
FIT_SUMMARY_COLUMNS: tuple[str, ...] = (
    "perturbation_db",
    "top_n",
    "criteria",
    "n_obs",
    "n_regulators",
    "r_squared",
    "converged",
    "note",
)


def method_promoter_model_target_universe_schema_sql() -> str:
    """
    Return the ``CREATE TABLE`` DDL for the per-assay target-universe size table.

    Populated once per assay by the coordinator alongside
    :func:`method_promoter_model_topn_schema_sql`'s staged fill (see
    :func:`promoter_set_target_universe`), and read by the live app so the Comparison
    module's "Method x Promoter Model" tab can tell a reader how many targets the
    cross-promoter-set intersection actually restricted each assay to -- the live app
    has no ``vdb`` access of its own to recompute it.

    :returns: ``CREATE TABLE method_promoter_model_target_universe (…)`` SQL string.
    :rtype: str

    """
    return """
CREATE TABLE method_promoter_model_target_universe (
    assay_primary  VARCHAR  NOT NULL,
    n_targets      INTEGER  NOT NULL,
    PRIMARY KEY (assay_primary)
);
"""


def method_promoter_model_schema_sql() -> str:
    """
    Return the ``CREATE TABLE`` DDL for the two method x promoter-set model tables.

    :returns: Concatenated ``CREATE TABLE`` SQL string.
    :rtype: str

    """
    return """
CREATE TABLE method_promoter_model_coefs (
    perturbation_db  VARCHAR  NOT NULL,
    top_n            INTEGER  NOT NULL,
    criteria         VARCHAR  NOT NULL,
    term             VARCHAR  NOT NULL,
    estimate         DOUBLE,
    std_error        DOUBLE,
    t_value          DOUBLE,
    p_value          DOUBLE,
    PRIMARY KEY (perturbation_db, top_n, criteria, term)
);

CREATE TABLE method_promoter_model_fit_summary (
    perturbation_db  VARCHAR  NOT NULL,
    top_n            INTEGER  NOT NULL,
    criteria         VARCHAR  NOT NULL,
    n_obs            INTEGER  NOT NULL,
    n_regulators     INTEGER  NOT NULL,
    r_squared        DOUBLE,
    converged        BOOLEAN  NOT NULL,
    note             VARCHAR,
    PRIMARY KEY (perturbation_db, top_n, criteria)
);
"""


def method_promoter_model_topn_schema_sql() -> str:
    """
    Return the ``CREATE TABLE`` DDL for this model's own top-N staging table.

    Same shape as ``topn_results`` (see ``topn.py::topn_schema_sql``), but kept as a
    separate table rather than inserted into ``topn_results`` itself: its rows are
    ranked over a target pool restricted to the cross-promoter-set intersection (see
    :func:`promoter_set_target_universe`), so for the same 16 cells it can disagree
    with ``topn_results``' own unrestricted ``n``/``n_responsive`` at the same
    ``(binding_source_sample, perturbation_source_sample, regulator_locus_tag, top_n,
    rank_col, rank_asc, effect_threshold, pvalue_threshold)`` key -- a primary-key
    collision if the two shared one table. This table feeds only
    :func:`build_method_promoter_panel`; no other consumer reads it.

    :returns: ``CREATE TABLE method_promoter_model_topn (…)`` SQL string.
    :rtype: str

    """
    return """
CREATE TABLE method_promoter_model_topn (
    binding_source_sample       VARCHAR  NOT NULL,
    perturbation_source_sample  VARCHAR  NOT NULL,
    regulator_locus_tag         VARCHAR  NOT NULL,
    top_n                       INTEGER  NOT NULL,
    rank_col                    VARCHAR  NOT NULL,
    rank_asc                    BOOLEAN  NOT NULL,
    effect_threshold            DOUBLE   NOT NULL,
    pvalue_threshold            DOUBLE   NOT NULL,
    n                           INTEGER  NOT NULL,
    n_responsive                INTEGER  NOT NULL,
    responsive_ratio            DOUBLE   NOT NULL,
    n_intersecting_targets      INTEGER  NOT NULL,
    binding_db                  VARCHAR  NOT NULL,
    binding_sample_id           VARCHAR  NOT NULL,
    perturbation_db             VARCHAR  NOT NULL,
    perturbation_sample_id      VARCHAR  NOT NULL,
    PRIMARY KEY (
        binding_source_sample,
        perturbation_source_sample,
        regulator_locus_tag,
        top_n, rank_col, rank_asc,
        effect_threshold, pvalue_threshold
    )
);
"""


def _resolve_cell(
    registry_df: pd.DataFrame, assay_primary: str, promoter_set: str, method: str
) -> str | None:
    """
    Resolve one (assay, promoter_set, method) cell to a concrete ``db_name``.

    Self-contained rather than importing ``BindingIndex`` from
    ``modules/comparison/queries.py`` -- ``materialize/`` keeps its own copies of the
    small pieces of registry logic it needs, same convention as
    ``topn.py``'s module docstring establishes for ``PERTURBATION_DATASET_COLUMNS``.

    :param registry_df: ``dataset_registry`` rows (``db_name``, ``primary_db_name``,
        ``promoter_set_id``, ``binding_method_id``).
    :param assay_primary: Primary ``db_name`` for the assay (e.g. ``'rossi_500bp'``).
    :param promoter_set: Promoter set id, e.g. ``'kang'``.
    :param method: Binding method id, e.g. ``'peak_calling'``.
    :returns: The matching ``db_name``, or ``None``.

    """
    prim = registry_df["primary_db_name"].fillna(registry_df["db_name"])
    match = registry_df[
        (prim == assay_primary)
        & (registry_df["promoter_set_id"] == promoter_set)
        & (registry_df["binding_method_id"] == method)
    ]
    if match.empty:
        return None
    return str(match.iloc[0]["db_name"])


def resolve_panel_cells(
    registry_df: pd.DataFrame,
) -> dict[tuple[str, str, str], str]:
    """
    Resolve every (assay, promoter_set, method) cell of the panel to a ``db_name``.

    Public wrapper around :func:`_resolve_cell` for the 16-cell design used by both
    :func:`build_method_promoter_panel` and the coordinator's staged top-N fill for
    this model -- so the coordinator does not need to reach into a module-private
    helper to enumerate the same cells.

    :param registry_df: ``dataset_registry`` rows.
    :returns: Mapping ``(assay_primary, promoter_set, method) -> db_name``, omitting
        any cell that does not resolve.

    """
    cells: dict[tuple[str, str, str], str] = {}
    for assay_primary in ASSAY_PRIMARIES:
        for method in METHOD_LEVELS:
            for promoter_set in PROMOTER_SET_LEVELS:
                b_db = _resolve_cell(registry_df, assay_primary, promoter_set, method)
                if b_db is not None:
                    cells[(assay_primary, promoter_set, method)] = b_db
    return cells


def promoter_set_target_universe(
    vdb: Any, registry_df: pd.DataFrame, assay_primary: str
) -> frozenset[str]:
    """
    Targets shared by every promoter set of one assay, for both methods.

    Both methods report every promoter of a promoter set for every sample -- promoter
    enrichment scores each annotated feature with a window, and the recalled
    peak-calling datasets list every promoter with a NULL score where no peak
    qualified -- so each of the eight views (4 promoter sets x 2 methods) is a
    complete list of its set's targets. Intersecting them gives one candidate pool
    that every cell of the panel is restricted to before ranking, so the promoter-set
    and method contrasts are not confounded by a wider window simply offering more
    candidates. No view is privileged: enrichment is not treated as the ground truth
    for peak calling.

    A live VirtualDB read (unlike the rest of this module, which reads only the
    materialized output ``conn``); the coordinator runs it once per assay before
    staging.

    :param vdb: VirtualDB instance (data source).
    :param registry_df: ``dataset_registry`` rows.
    :param assay_primary: Primary db_name for the assay (e.g. ``'rossi_500bp'``).
    :returns: Frozenset of ``target_locus_tag`` values present in all eight views.
        Empty if any view does not resolve.

    """
    universes: list[set[str]] = []
    for method in METHOD_LEVELS:
        for promoter_set in PROMOTER_SET_LEVELS:
            b_db = _resolve_cell(registry_df, assay_primary, promoter_set, method)
            if b_db is None:
                return frozenset()
            df = vdb.query(f"SELECT DISTINCT target_locus_tag FROM {b_db}")
            universes.append(set(df["target_locus_tag"].dropna().tolist()))
    return frozenset(set.intersection(*universes)) if universes else frozenset()


def default_filters(conn: Any, registry_df: pd.DataFrame) -> dict[str, Any]:
    """
    The app's default sample filters, expanded to every dataset variant.

    ``DEFAULT_DATASET_FILTERS`` is keyed by *primary* db_name; a variant takes its
    primary's filter via :func:`~tfbpshiny.utils.corr_query.expand_filters_to_variants`,
    the same expansion the live analysis modules apply, so a variant is filtered on the
    same metadata the selection tab shows for its primary. Two catalog queries; compute
    it once per build and pass it to :func:`build_method_promoter_panel`.

    :param conn: Output DuckDB connection (read); needs ``dataset_registry`` and the
        ``{db}_meta`` tables.
    :param registry_df: ``dataset_registry`` rows (``db_name``, ``primary_db_name``).
    :returns: Filter spec keyed by every db_name that has one.

    """
    return expand_filters_to_variants(conn, DEFAULT_DATASET_FILTERS, registry_df)


def _allowed_sample_ids(
    conn: Any, filters: dict[str, Any], db_name: str
) -> list[str] | None:
    """
    Resolve the sample_ids ``filters`` allow for one dataset.

    :param conn: Output DuckDB connection (read); needs the ``{db}_meta`` tables.
    :param filters: Expanded filter spec, from :func:`default_filters`.
    :param db_name: The concrete dataset whose ``{db_name}_meta`` table to query.
    :returns: ``None`` if this dataset has no applicable filter (no restriction), else
        the (possibly empty) list of allowed sample_ids.

    """
    filter_spec = filters.get(db_name)
    if not filter_spec:
        return None
    return get_filtered_sample_ids(conn, db_name, filter_spec)


def _regulator_intersection(conn: Any, perturbation_db: str) -> set[str]:
    """
    Regulators measured in the perturbation dataset AND both binding assays.

    Restricting to this 3-way intersection keeps the regulator population fixed across
    every cell of the design, so `method`/`promoter_set`/`assay` coefficients are not
    estimated over a shifting set of TFs cell to cell (a regulator profiled by only one
    binding assay, say, would otherwise contribute lopsided partial data). Reads the
    ``{db}_meta`` tables of the output database directly.

    :param conn: Output DuckDB connection (read).
    :param perturbation_db: Perturbation dataset db_name.
    :returns: Set of ``regulator_locus_tag`` values present in all three datasets.

    """

    def _regulators_for(db_name: str) -> set[str]:
        df = conn.execute(
            f"SELECT DISTINCT regulator_locus_tag FROM {db_name}_meta"
        ).df()
        return set(df["regulator_locus_tag"].dropna().tolist())

    regs = _regulators_for(perturbation_db)
    for assay_primary in ASSAY_PRIMARIES:
        regs &= _regulators_for(assay_primary)
    return regs


def apply_full_overlap_floor(conn: Any) -> tuple[int, int]:
    """
    The Comparison tab's "Require full overlap" switch, applied to the staged rows.

    Drops every row whose top-N list is short, ``n < top_n``, where ``n`` is the number
    of targets that passed the tie rule (a tie group counts only if its average rank
    is within N). So a regulator with too few scored targets, or a large tie group
    around rank N, loses that row. Run it before
    :func:`build_method_promoter_panel`: nothing is imputed afterwards, so a regulator
    removed here stays removed (the pairing rule then drops it from the other method
    too, within that assay x promoter set).

    The stored ``method_promoter_model_*`` tables do not apply this floor; it is for
    analyses that want complete top-N lists only.

    :param conn: Connection holding ``method_promoter_model_topn``.
    :returns: ``(rows_dropped, regulators_affected)``.

    """
    dropped, regulators = conn.execute(
        "SELECT count(*), count(DISTINCT regulator_locus_tag)"
        " FROM method_promoter_model_topn WHERE n < top_n"
    ).fetchone()
    conn.execute("DELETE FROM method_promoter_model_topn WHERE n < top_n")
    return int(dropped), int(regulators)


def build_method_promoter_panel(
    conn: Any,
    registry_df: pd.DataFrame,
    perturbation_db: str,
    top_n: int,
    preset: dict[str, tuple[float, float]],
    filters: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """
    Assemble the 16-cell (method x promoter_set x assay) panel for one model fit.

    Reads ``method_promoter_model_topn`` directly against the **output** DuckDB
    connection -- all inputs are already materialized locally by this point (the
    coordinator's staged top-N fill for this model has already done the one
    VirtualDB/HuggingFace hop this model needs, to compute
    :func:`promoter_set_target_universe`), so this function itself makes no
    VirtualDB/HuggingFace hop (unlike the DTO import in ``materialize/comparison/
    dto.py``). Unlike the shared ``topn_results`` table, every row here was ranked
    over a target pool already restricted to the cross-promoter-set intersection, so
    a promoter set's own (larger or smaller) full target list never leaks in as an
    uneven candidate pool. Restricted further to: (a) samples allowed by the app's
    default per-dataset filters (:data:`~tfbpshiny.utils.vdb_init.
    DEFAULT_DATASET_FILTERS`), the same way every live Comparison query already
    filters via :func:`~tfbpshiny.utils.corr_query.get_filtered_sample_ids`; and (b)
    regulators in the 3-way intersection of the perturbation dataset and both binding
    assays (see :func:`_regulator_intersection`).

    :param conn: Output DuckDB connection (read).
    :param registry_df: ``dataset_registry`` rows, read once by the caller and passed
        in rather than re-queried per (perturbation_db, top_n) combination.
    :param perturbation_db: Perturbation dataset db_name.
    :param top_n: Materialized cutoff.
    :param preset: Per-dataset responsiveness thresholds; see
        :data:`~tfbpshiny.utils.vdb_init.DEFAULT_RESPONSIVENESS_PRESETS`.
    :param filters: Expanded sample filters from :func:`default_filters`; computed
        here when not given. The coordinator passes one dict to all 60 panels.
    :returns: DataFrame with columns ``regulator_locus_tag``, ``method``,
        ``promoter_set``, ``assay``, ``n``, ``n_responsive``, ``n_non_responsive``,
        ``n_intersecting_targets``, ``responsive_ratio``. Empty if no cells resolve, the
        default filters exclude every sample, or no regulator survives the 3-way
        intersection.

    """
    effect_threshold, pvalue_threshold = preset.get(
        perturbation_db, preset.get("*", (0.0, 0.05))
    )
    if registry_df[registry_df["db_name"] == perturbation_db].empty:
        return pd.DataFrame()

    if filters is None:
        filters = default_filters(conn, registry_df)
    p_ids = _allowed_sample_ids(conn, filters, perturbation_db)
    if p_ids is not None and not p_ids:
        return pd.DataFrame()
    p_clause, p_params = sample_in_clause("perturbation_sample_id", p_ids)

    allowed_regulators = _regulator_intersection(conn, perturbation_db)
    if not allowed_regulators:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for assay_primary in ASSAY_PRIMARIES:
        for method in METHOD_LEVELS:
            for promoter_set in PROMOTER_SET_LEVELS:
                b_db = _resolve_cell(registry_df, assay_primary, promoter_set, method)
                if b_db is None:
                    continue
                b_ids = _allowed_sample_ids(conn, filters, b_db)
                if b_ids is not None and not b_ids:
                    continue
                b_clause, b_params = sample_in_clause("binding_sample_id", b_ids)
                sql = f"""
                SELECT
                    regulator_locus_tag, n, n_responsive, n_intersecting_targets
                FROM method_promoter_model_topn
                WHERE top_n = ?
                  AND effect_threshold = ?
                  AND pvalue_threshold = ?
                  AND binding_db = ?
                  AND perturbation_db = ?
                  {b_clause}
                  {p_clause}
                """
                params: list[Any] = [
                    top_n,
                    effect_threshold,
                    pvalue_threshold,
                    b_db,
                    perturbation_db,
                    *b_params,
                    *p_params,
                ]
                df = conn.execute(sql, params).df()
                if df.empty:
                    continue
                df["method"] = method
                df["promoter_set"] = promoter_set
                df["assay"] = assay_primary
                frames.append(df)

    if not frames:
        return pd.DataFrame()
    panel = pd.concat(frames, ignore_index=True)
    panel = pair_methods_on_regulators(panel, group_cols=["assay", "promoter_set"])
    panel = panel[panel["regulator_locus_tag"].isin(allowed_regulators)].reset_index(
        drop=True
    )
    if panel.empty:
        return panel
    panel["n_non_responsive"] = panel["n"] - panel["n_responsive"]
    panel["responsive_ratio"] = panel["n_responsive"] / panel["n"]
    return panel


def pair_methods_on_regulators(
    df: pd.DataFrame,
    group_cols: list[str],
    *,
    method_col: str = "method",
    regulator_col: str = "regulator_locus_tag",
) -> pd.DataFrame:
    """
    Keep a regulator within a group only where **both** methods have a row.

    The two methods are compared regulator by regulator, so a regulator with a
    promoter-enrichment list but no peak-calling list (it had no usable top-N, or no
    peak data at all) must not be averaged into one method and not the other: that
    would compare two methods over different transcription factors. Such a regulator is
    dropped from the group, in both directions. Nothing is imputed -- a regulator whose
    ratio is undefined is not scored as zero.

    Groups are compared independently (typically one assay x promoter set), so a
    regulator missing a method in one group is unaffected in another.

    Pure function over an in-memory frame -- no database access.

    :param df: Long frame with ``method_col``, ``regulator_col`` and every column in
        ``group_cols``.
    :param group_cols: Columns identifying one comparable cell.
    :param method_col: Column holding ``'promoter_enrichment'`` / ``'peak_calling'``.
    :param regulator_col: Column holding the regulator identity.
    :returns: ``df`` restricted to regulators present under every method within their
        group; column order and dtypes unchanged.

    """
    if df.empty:
        return df
    required = {method_col, regulator_col, *group_cols}
    missing_cols = required - set(df.columns)
    if missing_cols:
        raise KeyError(
            "pair_methods_on_regulators: df is missing column(s) "
            f"{sorted(missing_cols)}"
        )
    methods_present = df.groupby([*group_cols, regulator_col], dropna=False)[
        method_col
    ].transform("nunique")
    return df[methods_present == len(METHOD_LEVELS)].reset_index(drop=True)


def fit_method_promoter_model(
    panel: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Fit the pooled OLS and build the coefficients + fit-summary frames.

    Pure function over an in-memory panel -- no database access -- so it is directly
    unit-testable with synthetic data.

    :param panel: Output of :func:`build_method_promoter_panel`.
    :returns: ``(coefs, fit_summary)``. ``coefs`` has no
        ``perturbation_db``/``top_n``/``criteria`` columns -- the caller stamps those.
        ``fit_summary`` is always exactly one row.

    """
    n_obs = len(panel)
    n_regulators = panel["regulator_locus_tag"].nunique() if n_obs else 0

    def _failed(note: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        return (
            pd.DataFrame(
                columns=["term", "estimate", "std_error", "t_value", "p_value"]
            ),
            pd.DataFrame(
                [
                    {
                        "n_obs": n_obs,
                        "n_regulators": n_regulators,
                        "r_squared": None,
                        "converged": False,
                        "note": note,
                    }
                ]
            ),
        )

    if panel.empty:
        return _failed("empty panel")
    if n_regulators < MIN_REGULATORS:
        return _failed(f"fewer than {MIN_REGULATORS} regulators after filtering")
    if panel["method"].nunique() < 2:
        return _failed("no variation in method")
    if panel["promoter_set"].nunique() < 2:
        return _failed("no variation in promoter_set")

    formula = (
        "responsive_ratio ~ C(method, Treatment('peak_calling'))"
        " + C(promoter_set, Treatment('intergenic'))"
        " + C(assay, Treatment('rossi_500bp'))"
        " + C(regulator_locus_tag)"
    )
    try:
        fit = smf.ols(formula, data=panel).fit(
            cov_type="cluster", cov_kwds={"groups": panel["regulator_locus_tag"]}
        )
    except Exception as exc:  # noqa: BLE001 -- a singular design must not crash the run
        logger.warning("method_promoter_model: OLS fit failed (%s)", exc)
        return _failed(str(exc))

    # The regulator dummy coefficients are what makes the model correct (they hold each
    # TF's own baseline responsiveness constant) but are never displayed -- only the
    # method/promoter_set/assay/intercept rows answer the question this model exists
    # to answer.
    keep = ~fit.params.index.str.startswith("C(regulator_locus_tag")
    coefs = pd.DataFrame(
        {
            "term": fit.params.index[keep],
            "estimate": (fit.params[keep] * 100).to_numpy(),
            "std_error": (fit.bse[keep] * 100).to_numpy(),
            "t_value": (fit.params[keep] / fit.bse[keep]).to_numpy(),
            "p_value": fit.pvalues[keep].to_numpy(),
        }
    )
    fit_summary = pd.DataFrame(
        [
            {
                "n_obs": n_obs,
                "n_regulators": n_regulators,
                "r_squared": float(fit.rsquared),
                "converged": True,
                "note": None,
            }
        ]
    )
    return coefs, fit_summary


__all__ = [
    "ASSAY_PRIMARIES",
    "apply_full_overlap_floor",
    "COEFS_COLUMNS",
    "FIT_SUMMARY_COLUMNS",
    "METHOD_LEVELS",
    "PROMOTER_SET_LEVELS",
    "build_method_promoter_panel",
    "fit_method_promoter_model",
    "pair_methods_on_regulators",
    "method_promoter_model_schema_sql",
    "method_promoter_model_target_universe_schema_sql",
    "method_promoter_model_topn_schema_sql",
    "promoter_set_target_universe",
    "resolve_panel_cells",
]
