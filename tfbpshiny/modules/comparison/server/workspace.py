"""Workspace server for the Comparison module."""

from __future__ import annotations

import re
from logging import Logger
from typing import Any

import duckdb
import pandas as pd
import plotly.graph_objects as go
from plotly.io import to_html
from shiny import module, reactive, render, ui

from tfbpshiny.components import scroll_row, sidebar_label
from tfbpshiny.datasets import PRESET_NAMES
from tfbpshiny.materialize.comparison.method_promoter_model import (
    pair_methods_on_regulators,
)
from tfbpshiny.modules.comparison.queries import (
    BINDING_METHOD_COLORS,
    BINDING_METHOD_LABELS,
    DEFAULT_DTO_RANKING_COLUMN,
    DEFAULT_TOP_N,
    DTO_PVALUE_THRESHOLD,
    DTO_RANKING_COLUMNS,
    METHOD_LEVELS,
    METRIC_DTO,
    METRIC_TOPN,
    PEAK_CALLER_NOTES,
    PERTURBATION_LABEL_MAP,
    PROMOTER_SET_LABELS,
    PROMOTER_SET_LEVELS,
    TOP_N_CHOICES,
    build_binding_index,
    fetch_dto_results,
    fetch_dto_results_method_intersected,
    fetch_method_promoter_model,
    fetch_method_promoter_target_universe,
    fetch_topn_results,
)
from tfbpshiny.utils.perf import perf, reset_render_counts
from tfbpshiny.utils.topn_matrix import build_topn_matrix_ui
from tfbpshiny.utils.vdb_init import (
    DEFAULT_RESPONSIVENESS_PRESET,
    DEFAULT_RESPONSIVENESS_PRESETS,
    get_regulator_display_name,
    get_responsiveness_label,
)

_BINDING_ORDER = [
    "2004 ChIP-chip",
    "2021 ChIP-exo",
    "2025 ChEC-seq",
    "2026 Calling Cards",
]

#: Tooltip for each responsiveness preset, keyed by name.
_PRESET_HELP: dict[str, str] = {
    "Relaxed": (
        "Applies a uniform pvalue < 0.05 threshold. Hover over"
        " perturbation column headers in Compare Datasets for"
        " per-dataset details."
    ),
    "Stringent": (
        "Uses the original authors' thresholds for each dataset."
        " Hover over perturbation column headers in Compare"
        " Datasets for per-dataset details."
    ),
}

assert set(_PRESET_HELP) == set(PRESET_NAMES)

#: Selector label for each promoter set, keyed by ``promoter_set_id``.
_PROMOTER_SET_ALIAS: dict[str, str] = {
    "kang": "Promoter Set 1 (Kang)",
    "mindel": "Promoter Set 2 (Mindel)",
    "500bp": "Promoter Set 3 (500bp)",
    "intergenic": "Promoter Set 4 (Intergenic)",
}

#: Tooltip text for each promoter set, keyed by ``promoter_set_id``.
_PROMOTER_TOOLTIPS: dict[str, str] = {
    "kang": (
        "700 bp upstream of each start codon, truncated if there exists a feature "
        "within 700 bp of the ORF."
    ),
    "mindel": (
        "Promoter regions defined from the start codon to at least 700 bp upstream "
        "of the TSS defined by Park et al., 2014; Pelechano et al., 2013; Policastro "
        "et al., 2020 (provided in the SGD annotations). If no TSS is defined, the "
        "start codon is used."
    ),
    "500bp": (
        "Promoter regions defined as exactly 500 bp upstream of the start codon. "
        "No truncation or extension; all promoters are the same length."
    ),
    "intergenic": (
        "Promoter regions defined as the full intergenic region upstream of the 5' "
        "end of each feature. Note that approximately 1410 of 6040 features are "
        "divergently transcribed."
    ),
}


def _inputs_ready(input: Any, *names: str) -> bool:
    """
    Whether every named input exists and has a value yet.

    ``tab_specific_controls`` creates the per-tab inputs on demand, so on first
    load and for one flush after a tab switch they are absent. The ``_read_*``
    helpers below fall back to defaults when that happens, which would make a
    live data calc fetch once against the fallbacks and again once the real
    values arrive. Gating on this avoids that double fetch.

    Reading each input registers a reactive dependency, so the calc re-runs as
    soon as the inputs appear.

    :param input: Shiny input object.
    :param names: Input ids that must be present.
    :returns: ``True`` when all are available.

    """
    for name in names:
        try:
            if getattr(input, name)() is None:
                return False
        except Exception:
            return False
    return True


def _read_metric(input: Any) -> str:
    try:
        return str(input.metric())
    except Exception:
        return METRIC_TOPN


def _read_dto_ranking(input: Any) -> str:
    try:
        return str(input.dto_ranking_column())
    except Exception:
        return DEFAULT_DTO_RANKING_COLUMN


def _read_top_n(input: Any) -> int:
    try:
        return int(input.top_n())
    except Exception:
        return DEFAULT_TOP_N


def _read_full_overlap(input: Any) -> bool:
    try:
        return bool(input.require_intersecting_floor())
    except Exception:
        return True


def _read_common_regulators_only(input: Any) -> bool:
    try:
        return bool(input.cm_common_regulators_only())
    except Exception:
        return False


def _read_preset(input: Any) -> dict[str, tuple[float, float]]:
    try:
        name = str(input.responsiveness_preset())
    except Exception:
        name = DEFAULT_RESPONSIVENESS_PRESET
    return DEFAULT_RESPONSIVENESS_PRESETS.get(
        name, DEFAULT_RESPONSIVENESS_PRESETS[DEFAULT_RESPONSIVENESS_PRESET]
    )


def _read_preset_name(input: Any) -> str:
    try:
        return str(input.responsiveness_preset())
    except Exception:
        return DEFAULT_RESPONSIVENESS_PRESET


def _cell_style(val: float) -> str:
    """HSL green scale: 0% -> white, 100% -> full green."""
    clamped = max(0.0, min(100.0, val))
    lightness = 100 - clamped * 0.5
    return (
        f"background-color: hsl(120, 60%, {lightness:.0f}%);"
        " padding: 6px 10px; text-align: right;"
    )


def _mm_term_label(term: str) -> str:
    """
    Shorten a patsy term name for display, e.g. drop the ``C(..., Treatment(...))``
    wrapper down to just the factor and level.

    ``"C(method, Treatment('promoter_enrichment'))[T.peak_calling]"`` becomes
    ``"method[peak_calling]"``; interaction terms keep the ``:`` separator between
    shortened pieces. Falls back to the raw term unchanged if it doesn't match the
    expected patsy shape, so an unrecognized term is still shown, just unprettified.

    :param term: Raw patsy/statsmodels coefficient or test-block name.
    :returns: Shortened label.

    """

    def _shorten_piece(piece: str) -> str:
        m = re.match(r"C\((\w+),\s*Treatment\([^)]*\)\)(?:\[T\.(.+)\])?", piece)
        if not m:
            return piece
        factor, level = m.group(1), m.group(2)
        return f"{factor}[{level}]" if level else factor

    if term == "Intercept":
        return term
    return ":".join(_shorten_piece(p) for p in term.split(":"))


def _summary_table(
    df: pd.DataFrame,
    columns: list[tuple[str, str, str]],
    *,
    label_col: str | None = None,
) -> ui.Tag:
    """
    Render a DataFrame as an R-``summary(lm())``-style HTML table.

    :param df: Rows to render, in the order given.
    :param columns: ``(df_column, header_label, format_spec)`` tuples. ``format_spec``
        is a Python format spec applied via ``f"{value:{format_spec}}"``, or ``""``
        for plain string conversion.
    :param label_col: If given, this column's values are shortened via
        :func:`_mm_term_label` before display (used for term/test-name columns).
    :returns: A ``ui.tags.table``, or an empty-state div if `df` is empty.

    """
    if df.empty:
        return ui.div({"class": "empty-state"}, ui.p("No rows."))
    header_cells = [
        ui.tags.th(label, style="padding: 4px 10px; text-align: right;")
        for _, label, _ in columns
    ]
    data_rows = []
    for _, row in df.iterrows():
        cells = []
        for col, _, fmt in columns:
            val = row[col]
            if col == label_col:
                text = _mm_term_label(str(val))
            elif pd.isna(val):
                text = "—"
            elif fmt:
                text = f"{val:{fmt}}"
            else:
                text = str(val)
            cells.append(
                ui.tags.td(text, style="padding: 4px 10px; text-align: right;")
            )
        data_rows.append(ui.tags.tr(*cells))
    return ui.tags.table(
        {
            "style": "border-collapse: collapse; font-size: 0.85rem; font-family:"
            " ui-monospace, monospace;"
        },
        ui.tags.thead(
            {"style": "background-color: #f5f5f5;"}, ui.tags.tr(*header_cells)
        ),
        ui.tags.tbody(*data_rows),
    )


@module.server
def comparison_workspace_server(
    input: Any,
    output: Any,
    session: Any,
    active_binding_datasets: reactive.Calc_[list[str]],
    active_perturbation_datasets: reactive.Calc_[list[str]],
    dataset_filters: reactive.Value[dict[str, Any]],
    conn: duckdb.DuckDBPyConnection,
    logger: Logger,
) -> None:
    """
    Render the Comparison workspace: topN matrix, distributions, promoter/method tables.

    :param active_binding_datasets: Reactive calc returning active primary binding
        db names.
    :param active_perturbation_datasets: Reactive calc returning active perturbation
        db names.
    :param dataset_filters: Reactive value with per-dataset filter specs.
    :param conn: Read-only DuckDB connection to the materialized database.
    :param logger: Application logger.

    """
    session.on_flush(lambda: reset_render_counts(session.id))

    # Pre-load the registry once. `binding_index` decomposes every binding
    # dataset into promoter set x method, replacing the label dicts this module
    # used to hand-maintain alongside the collection YAML.
    _registry_df = conn.execute(
        "SELECT db_name, data_type, display_name, base_label,"
        " primary_db_name, promoter_set_id, binding_method_id"
        " FROM dataset_registry"
    ).df()
    display_names: dict[str, str] = dict(
        zip(_registry_df["db_name"], _registry_df["display_name"])
    )
    binding_index = build_binding_index(_registry_df)

    # The DTO tables only exist in databases built after DTO materialization was
    # fixed. Detect once so the metric can explain itself rather than rendering a
    # grid of dashes.
    _dto_available = (
        conn.execute(
            "SELECT count(*) FROM information_schema.tables"
            " WHERE table_name IN ('dto', 'sample_regulator')"
        ).fetchone()[0]
        == 2
    )
    if not _dto_available:
        logger.warning(
            "comparison: `dto`/`sample_regulator` tables missing from the database;"
            " the DTO metric will be unavailable until it is re-materialized"
        )

    _reg_df = get_regulator_display_name(conn)
    _reg_labels: dict[str, str] = {}
    for _, row in _reg_df.iterrows():
        tag = str(row["regulator_locus_tag"])
        sym = str(row.get("regulator_symbol", ""))
        if sym and sym != "nan" and sym != tag:
            _reg_labels[tag] = f"{sym} ({tag})"
        else:
            _reg_labels[tag] = tag

    _all_binding_dbs = (
        conn.execute("SELECT db_name FROM dataset_registry WHERE data_type = 'binding'")
        .df()["db_name"]
        .tolist()
    )
    _all_perturbation_dbs = (
        conn.execute(
            "SELECT db_name FROM dataset_registry WHERE data_type = 'perturbation'"
        )
        .df()["db_name"]
        .tolist()
    )

    # ---------------------------------------------------------------------------
    # State
    # ---------------------------------------------------------------------------

    cd_selected_binding: reactive.Value[str | None] = reactive.value(None)
    cd_selected_perturbation: reactive.Value[str | None] = reactive.value(None)

    # ---------------------------------------------------------------------------
    # Inner tab helper
    # ---------------------------------------------------------------------------

    def _inner_tab() -> str:
        try:
            return str(input.comparison_inner_tabs())
        except Exception:
            return "Compare Datasets"

    # ---------------------------------------------------------------------------
    # Binding db resolution helpers
    # ---------------------------------------------------------------------------

    def _cd_binding_dbs() -> list[str]:
        """
        Resolve binding db_names for the Compare Datasets tab.

        Maps primary binding datasets to variant db_names based on the selected Binding
        Method and Promoter Set controls.

        """
        try:
            method = str(input.cd_binding_method())
        except Exception:
            method = "Promoter Enrichment"
        try:
            ps_id = str(input.cd_promoter_set())
        except Exception:
            ps_id = "kang"

        method_id = "peak_calling" if method == "Peaks" else "promoter_enrichment"
        result: list[str] = []
        for b_db in active_binding_datasets():
            # resolve_or_self, not resolve: Harbison's regions are microarray probes,
            # so no promoter set names it and a strict resolve would drop it from
            # every column of this tab.
            db = binding_index.resolve_or_self(b_db, ps_id, method_id)
            if db:
                result.append(db)
        return result

    def _cp_binding_dbs() -> list[str]:
        """
        All binding db_names (primary + variants) for the Compare Promoter tab.

        Builds the set of all active primary datasets plus all their promoter-set
        variant db_names, filtered to only the promoter sets the user has checked in the
        sidebar.

        """
        try:
            included_ps = list(input.cp_included_promoter_sets())
        except Exception:
            included_ps = list(_PROMOTER_SET_ALIAS.keys())

        result: list[str] = []
        for b_db in active_binding_datasets():
            for ps_id in PROMOTER_SET_LEVELS:
                if ps_id not in included_ps:
                    continue
                db = binding_index.resolve(b_db, ps_id, "promoter_enrichment")
                if db:
                    result.append(db)
        return result

    def _cm_selected_binding_db() -> str:
        """
        The primary binding dataset driving the Compare Methods tab.

        Falls back to the first active dataset that has both a promoter-enrichment and a
        peak-calling variant.

        """
        try:
            cm_binding_db = str(input.cm_binding_dataset())
        except Exception:
            cm_binding_db = ""
        active = active_binding_datasets()
        if cm_binding_db in active:
            return cm_binding_db
        eligible = [db for db in active if binding_index.supports_method_comparison(db)]
        return eligible[0] if eligible else ""

    def _cm_binding_dbs() -> list[str]:
        """
        Binding db_names for the Compare Methods tab.

        For the selected dataset, returns both the promoter-enrichment and the peak-
        calling variant of every checked promoter set. The original authors' peaks are
        excluded -- they have no fixed promoter window, so they are not comparable
        across promoter set columns.

        """
        cm_binding_db = _cm_selected_binding_db()
        if not cm_binding_db:
            return []

        try:
            cm_ps = list(input.cm_promoter_set())
        except Exception:
            cm_ps = list(PROMOTER_SET_LEVELS)

        result: list[str] = []
        for ps_id in PROMOTER_SET_LEVELS:
            if ps_id not in cm_ps:
                continue
            for method_id in METHOD_LEVELS:
                db = binding_index.resolve(cm_binding_db, ps_id, method_id)
                if db:
                    result.append(db)
        return result

    # ---------------------------------------------------------------------------
    # Data fetches (triggered by Execute)
    # ---------------------------------------------------------------------------

    def _dto_unavailable() -> ui.Tag | None:
        """
        Empty state shown when the DTO metric is selected but not materialized.

        Returns ``None`` when there is nothing to report, so callers can use it as a
        guard: ``if (msg := _dto_unavailable()) is not None: return msg``.

        """
        if _read_metric(input) != METRIC_DTO or _dto_available:
            return None
        return ui.div(
            {"class": "empty-state"},
            ui.p(
                ui.strong("DTO results are not in this database."),
                " The `dto` and `sample_regulator` tables are missing, which means"
                " the database predates DTO materialization.",
            ),
            ui.p(
                "Rebuild it with ",
                ui.tags.code("tfbpshiny materialize"),
                " to enable this metric, or switch back to Top-N.",
            ),
        )

    def _metric_note(p_db: str) -> str:
        """Tooltip describing how the displayed value was computed, per metric."""
        if _read_metric(input) == METRIC_DTO:
            return (
                f"Percent of shared regulators with DTO empirical p <"
                f" {DTO_PVALUE_THRESHOLD} ({_read_dto_ranking(input)} ranking)."
                " Denominator is every regulator present in both datasets."
            )
        thresh = get_responsiveness_label(_read_preset_name(input), p_db)
        return f"Responsive threshold: {thresh}"

    def _dto_frame(pairs: list[tuple[str, str]]) -> pd.DataFrame:
        """
        Fetch DTO percentages for `pairs` and attach the label columns the tabs need.

        Produces the same key columns the Top-N calcs emit -- ``binding_base_label``,
        ``promoter_set_id``, ``binding_method_id`` -- so the table renderers work
        unchanged. ``n_intersect`` becomes ``n_regulators`` (the metric's denominator)
        and ``n_covered`` is carried through so the tested/shared gap stays visible.

        """
        filters = dataset_filters()
        ranking = _read_dto_ranking(input)
        with perf(session.id, "comparison.workspace", "_dto_fetch", kind="data"):
            try:
                raw = fetch_dto_results(conn, pairs, filters, ranking)
            except Exception:
                logger.exception("dto fetch failed")
                return pd.DataFrame()
        if raw.empty:
            return raw
        raw["binding_label"] = (
            raw["binding_db"].map(binding_index.label).fillna(raw["binding_db"])
        )
        raw["binding_base_label"] = (
            raw["binding_db"].map(binding_index.base_label).fillna(raw["binding_db"])
        )
        raw["promoter_set_id"] = (
            raw["binding_db"].map(binding_index.promoter_set_id).fillna("")
        )
        raw["binding_method_id"] = (
            raw["binding_db"].map(binding_index.method_id).fillna("")
        )
        raw["perturbation_source"] = (
            raw["perturbation_db"]
            .map(PERTURBATION_LABEL_MAP)
            .fillna(raw["perturbation_db"])
        )
        raw["val"] = raw["percent_significant"].round(4)
        raw["n_regulators"] = raw["n_intersect"]
        return raw

    def _cm_dto_frame(pairs: list[tuple[str, str]]) -> pd.DataFrame:
        """
        DTO branch of ``_cm_data`` (Compare Analysis Methods tab).

        Like :func:`_dto_frame`, but this tab always varies method, and DTO
        significance can't be recomputed for a regulator missing from one method's
        binding data -- so instead of each ``(binding_db, perturbation_db)`` pair
        drawing its own pairwise regulator intersection, every sibling
        (promoter_enrichment, peak_calling) pair at the same promoter set shares one
        3-way-intersected universe (see
        ``fetch_dto_results_method_intersected``), so the two bars stay directly
        comparable.

        """
        filters = dataset_filters()
        ranking = _read_dto_ranking(input)
        cells: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for b_db, p_db in pairs:
            primary = binding_index.primary.get(b_db, b_db)
            ps_id = binding_index.promoter_set_id.get(b_db, "")
            key = (primary, ps_id, p_db)
            if key in seen:
                continue
            seen.add(key)
            pe_db = binding_index.resolve(primary, ps_id, "promoter_enrichment")
            pc_db = binding_index.resolve(primary, ps_id, "peak_calling")
            if pe_db and pc_db:
                cells.append((pe_db, pc_db, p_db))
        with perf(session.id, "comparison.workspace", "_cm_dto_fetch", kind="data"):
            try:
                raw = fetch_dto_results_method_intersected(
                    conn, cells, filters, ranking
                )
            except Exception:
                logger.exception("cm dto fetch failed")
                return pd.DataFrame()
        if raw.empty:
            return raw
        raw["binding_label"] = (
            raw["binding_db"].map(binding_index.label).fillna(raw["binding_db"])
        )
        raw["binding_base_label"] = (
            raw["binding_db"].map(binding_index.base_label).fillna(raw["binding_db"])
        )
        raw["promoter_set_id"] = (
            raw["binding_db"].map(binding_index.promoter_set_id).fillna("")
        )
        raw["binding_method_id"] = (
            raw["binding_db"].map(binding_index.method_id).fillna("")
        )
        raw["perturbation_source"] = (
            raw["perturbation_db"]
            .map(PERTURBATION_LABEL_MAP)
            .fillna(raw["perturbation_db"])
        )
        raw["val"] = raw["percent_significant"].round(4)
        raw["n_regulators"] = raw["n_intersect"]
        return raw

    @reactive.calc
    def _cd_data() -> pd.DataFrame:
        """
        TopN data for the Compare Datasets tab.

        :trigger: ``input.cd_binding_method`` / ``input.cd_promoter_set`` — tab
            controls.
        :trigger: ``input.top_n`` / ``input.responsiveness_preset`` /
            ``input.require_intersecting_floor`` — shared sidebar controls.
        :trigger: ``active_binding_datasets`` / ``active_perturbation_datasets`` /
            ``dataset_filters`` — committed dataset selection.

        """
        if not _inputs_ready(input, "cd_binding_method", "cd_promoter_set"):
            return pd.DataFrame()
        b_dbs = _cd_binding_dbs()
        p_dbs = active_perturbation_datasets()
        if not b_dbs or not p_dbs:
            return pd.DataFrame()
        pairs = [(b, p) for b in b_dbs for p in p_dbs]
        if _read_metric(input) == METRIC_DTO:
            raw = _dto_frame(pairs)
            if raw.empty:
                return raw
            # The matrix takes a median per cell; with one row per pair that is the
            # value itself, so the renderer needs no DTO-specific branch.
            raw["percent_responsive"] = raw["val"]
            return raw
        filters = dataset_filters()
        n = _read_top_n(input)
        preset = _read_preset(input)
        floor = _read_full_overlap(input)
        logger.debug("cd_data: %d pairs", len(pairs))
        with perf(session.id, "comparison.workspace", "_cd_data", kind="data"):
            try:
                raw = fetch_topn_results(
                    conn, pairs, filters, n, preset, require_full_overlap=floor
                )
            except Exception:
                logger.exception("cd_data fetch failed")
                return pd.DataFrame()
        if raw.empty:
            return pd.DataFrame()
        raw["binding_label"] = (
            raw["binding_db"].map(binding_index.label).fillna(raw["binding_db"])
        )
        raw["perturbation_source"] = (
            raw["perturbation_db"]
            .map(PERTURBATION_LABEL_MAP)
            .fillna(raw["perturbation_db"])
        )
        raw["regulator_label"] = (
            raw["regulator_locus_tag"]
            .map(_reg_labels)
            .fillna(raw["regulator_locus_tag"])
        )
        raw["percent_responsive"] = raw["responsive_ratio"] * 100
        return raw

    @reactive.calc
    def _cp_data() -> pd.DataFrame:
        """
        TopN data for the Compare Promoter Definitions tab.

        :trigger: ``input.cp_included_promoter_sets`` — tab control.
        :trigger: ``input.top_n`` / ``input.responsiveness_preset`` /
            ``input.require_intersecting_floor`` — shared sidebar controls.
        :trigger: ``active_binding_datasets`` / ``active_perturbation_datasets`` /
            ``dataset_filters`` — committed dataset selection.

        """
        if not _inputs_ready(input, "cp_included_promoter_sets"):
            return pd.DataFrame()
        b_dbs = _cp_binding_dbs()
        p_dbs = active_perturbation_datasets()
        if not b_dbs or not p_dbs:
            return pd.DataFrame()
        pairs = [(b, p) for b in b_dbs for p in p_dbs]
        if _read_metric(input) == METRIC_DTO:
            raw = _dto_frame(pairs)
            if raw.empty:
                return raw
            return raw[
                ["perturbation_db", "binding_base_label", "promoter_set_id", "val"]
            ]
        filters = dataset_filters()
        n = _read_top_n(input)
        preset = _read_preset(input)
        floor = _read_full_overlap(input)
        logger.debug("cp_data: %d pairs", len(pairs))
        with perf(session.id, "comparison.workspace", "_cp_data", kind="data"):
            try:
                raw = fetch_topn_results(
                    conn, pairs, filters, n, preset, require_full_overlap=floor
                )
            except Exception:
                logger.exception("cp_data fetch failed")
                return pd.DataFrame()
        if raw.empty:
            return pd.DataFrame()
        raw["binding_base_label"] = (
            raw["binding_db"].map(binding_index.base_label).fillna(raw["binding_db"])
        )
        # Keyed by raw promoter_set_id (not the display label) so it matches the
        # ids the sidebar checkbox group emits; the render maps to labels.
        raw["promoter_set_id"] = (
            raw["binding_db"].map(binding_index.promoter_set_id).fillna("")
        )
        return duckdb.execute(
            """
            WITH per_reg AS (
                SELECT
                    perturbation_db,
                    binding_base_label,
                    promoter_set_id,
                    regulator_locus_tag,
                    median(responsive_ratio) * 100 AS med_pct
                FROM raw
                GROUP BY perturbation_db, binding_base_label, promoter_set_id,
                    regulator_locus_tag
            )
            SELECT
                perturbation_db,
                binding_base_label,
                promoter_set_id,
                round(median(med_pct), 4) AS val
            FROM per_reg
            GROUP BY perturbation_db, binding_base_label, promoter_set_id
        """
        ).df()

    @reactive.calc
    def _cm_data() -> pd.DataFrame:
        """
        TopN data for the Compare Analysis Methods tab.

        :trigger: ``input.cm_binding_dataset`` / ``input.cm_promoter_set`` /
            ``input.cm_common_regulators_only`` — tab controls.
        :trigger: ``input.top_n`` / ``input.responsiveness_preset`` /
            ``input.require_intersecting_floor`` — shared sidebar controls.
        :trigger: ``active_binding_datasets`` / ``active_perturbation_datasets`` /
            ``dataset_filters`` — committed dataset selection.

        """
        if not _inputs_ready(
            input, "cm_binding_dataset", "cm_promoter_set", "cm_common_regulators_only"
        ):
            return pd.DataFrame()
        b_dbs = _cm_binding_dbs()
        p_dbs = active_perturbation_datasets()
        if not b_dbs or not p_dbs:
            return pd.DataFrame()
        pairs = [(b, p) for b in b_dbs for p in p_dbs]
        if _read_metric(input) == METRIC_DTO:
            raw = _cm_dto_frame(pairs)
            if raw.empty:
                return raw
            return raw[
                [
                    "perturbation_db",
                    "promoter_set_id",
                    "binding_method_id",
                    "val",
                    "n_regulators",
                ]
            ]
        filters = dataset_filters()
        n = _read_top_n(input)
        preset = _read_preset(input)
        floor = _read_full_overlap(input)
        common_only = _read_common_regulators_only(input)
        logger.debug("cm_data: %d pairs (%s × %s)", len(pairs), b_dbs, p_dbs)
        with perf(session.id, "comparison.workspace", "_cm_data", kind="data"):
            try:
                raw = fetch_topn_results(
                    conn, pairs, filters, n, preset, require_full_overlap=floor
                )
            except Exception:
                logger.exception("cm_data fetch failed")
                return pd.DataFrame()
        if raw.empty:
            return pd.DataFrame()
        raw["promoter_set_id"] = (
            raw["binding_db"].map(binding_index.promoter_set_id).fillna("")
        )
        raw["binding_method_id"] = (
            raw["binding_db"].map(binding_index.method_id).fillna("")
        )
        # When common_only, restrict per_reg (per perturbation_db) to regulators
        # present in every promoter-set x method cell, so N is identical across
        # the whole table.
        common_filter = (
            """
            JOIN common_regs cr
                ON  per_reg.perturbation_db     = cr.perturbation_db
                AND per_reg.regulator_locus_tag = cr.regulator_locus_tag
            """
            if common_only
            else ""
        )
        per_reg = duckdb.execute(
            """
            SELECT
                perturbation_db,
                promoter_set_id,
                binding_method_id,
                regulator_locus_tag,
                median(responsive_ratio) * 100 AS med_pct
            FROM raw
            GROUP BY perturbation_db, promoter_set_id, binding_method_id,
                regulator_locus_tag
            """
        ).df()
        # Compare the two methods over the same regulators: keep a regulator within a
        # (perturbation_db, promoter_set_id) cell only where promoter enrichment AND
        # peak calling both have a row. A regulator with no usable peak-calling list is
        # dropped, not scored as zero. Grouped so promoter sets do not cross-contaminate
        # each other's regulator universe.
        per_reg = pair_methods_on_regulators(
            per_reg,
            group_cols=["perturbation_db", "promoter_set_id"],
            method_col="binding_method_id",
        )
        if per_reg.empty:
            return pd.DataFrame()

        return duckdb.execute(
            f"""
            WITH reg_cell_counts AS (
                SELECT
                    perturbation_db,
                    regulator_locus_tag,
                    COUNT(*) AS n_covered
                FROM per_reg
                GROUP BY perturbation_db, regulator_locus_tag
            ),
            cell_totals AS (
                SELECT
                    perturbation_db,
                    COUNT(DISTINCT (promoter_set_id, binding_method_id)) AS n_total
                FROM per_reg
                GROUP BY perturbation_db
            ),
            common_regs AS (
                SELECT rcc.perturbation_db, rcc.regulator_locus_tag
                FROM reg_cell_counts rcc
                JOIN cell_totals ct ON rcc.perturbation_db = ct.perturbation_db
                WHERE rcc.n_covered = ct.n_total
            )
            SELECT
                per_reg.perturbation_db,
                per_reg.promoter_set_id,
                per_reg.binding_method_id,
                round(median(per_reg.med_pct), 4) AS val,
                COUNT(DISTINCT per_reg.regulator_locus_tag) AS n_regulators
            FROM per_reg
            {common_filter}
            GROUP BY per_reg.perturbation_db, per_reg.promoter_set_id,
                per_reg.binding_method_id
        """
        ).df()

    # ---------------------------------------------------------------------------
    # Renders
    # ---------------------------------------------------------------------------

    @render.ui
    def metric_controls() -> ui.Tag:
        """
        Sidebar controls belonging to the selected metric.

        Top-N and DTO share no parameters, so rather than showing both sets and
        ignoring half, only the relevant ones are rendered.

        :trigger: ``input.metric`` — re-renders when the metric changes.

        """
        if _read_metric(input) == METRIC_DTO:
            return ui.div(
                sidebar_label("Perturbation Ranking"),
                ui.input_radio_buttons(
                    "dto_ranking_column",
                    label=None,
                    choices={
                        c: ui.tooltip(
                            ui.span(c),
                            "Which perturbation ranking the DTO run used. Only"
                            " log2fc exists for Overexpression and both Hughes"
                            " sets; TFKO, Hu and Degron carry both.",
                            placement="right",
                        )
                        for c in DTO_RANKING_COLUMNS
                    },
                    selected=DEFAULT_DTO_RANKING_COLUMN,
                    inline=True,
                ),
            )
        return ui.div(
            sidebar_label("Top N"),
            ui.input_radio_buttons(
                "top_n",
                label=None,
                choices={str(n): str(n) for n in TOP_N_CHOICES},
                selected=str(DEFAULT_TOP_N),
                inline=True,
            ),
            ui.input_switch(
                "require_intersecting_floor",
                ui.tooltip(
                    ui.span("Require full overlap"),
                    "When on, only shows regulator/sample pairs whose top-N list is"
                    " complete: at least the selected Top N targets remain after"
                    " ties are resolved (a tie group counts only if its average rank"
                    " is within N). A regulator with too few scored targets, or a"
                    " large tie group around rank N, is excluded. Turn off to keep"
                    " shorter lists.",
                    placement="right",
                ),
                value=True,
            ),
            sidebar_label("Responsiveness"),
            ui.input_radio_buttons(
                "responsiveness_preset",
                label=None,
                choices={
                    name: ui.tooltip(
                        ui.span(name), _PRESET_HELP[name], placement="right"
                    )
                    for name in PRESET_NAMES
                },
                selected=DEFAULT_RESPONSIVENESS_PRESET,
                inline=True,
            ),
        )

    @render.ui
    def tab_specific_controls() -> ui.Tag:
        """
        Sidebar controls specific to the active inner tab.

        :trigger: ``input.comparison_inner_tabs`` — re-renders when tab changes.

        """
        tab = _inner_tab()
        active = active_binding_datasets()

        if tab == "Compare Datasets":
            return ui.div(
                sidebar_label("Binding Method"),
                ui.input_select(
                    "cd_binding_method",
                    label=None,
                    choices={
                        "Promoter Enrichment": "Promoter Enrichment",
                        "Peaks": "Peaks",
                    },
                    selected="Promoter Enrichment",
                ),
                sidebar_label("Promoter Set"),
                ui.input_select(
                    "cd_promoter_set",
                    label=None,
                    choices={k: _PROMOTER_SET_ALIAS[k] for k in _PROMOTER_SET_ALIAS},
                    selected="kang",
                ),
            )

        if tab == "Compare Promoter Definitions":
            return ui.div(
                sidebar_label("Promoter Sets"),
                ui.input_checkbox_group(
                    "cp_included_promoter_sets",
                    label=None,
                    choices={
                        ps: ui.tooltip(
                            ui.span(_PROMOTER_SET_ALIAS[ps]),
                            _PROMOTER_TOOLTIPS[ps],
                            placement="right",
                        )
                        for ps in _PROMOTER_SET_ALIAS
                    },
                    selected=list(_PROMOTER_SET_ALIAS.keys()),
                ),
            )

        if tab == "Compare Analysis Methods":
            eligible = [
                db for db in active if binding_index.supports_method_comparison(db)
            ]
            method_choices = {
                db: binding_index.base_label.get(db, db) for db in eligible
            }
            return ui.div(
                sidebar_label("Binding Dataset"),
                ui.input_select(
                    "cm_binding_dataset",
                    label=None,
                    choices=method_choices,
                    selected=next(iter(method_choices), None),
                ),
                sidebar_label("Promoter Set"),
                ui.input_checkbox_group(
                    "cm_promoter_set",
                    label=None,
                    choices={k: _PROMOTER_SET_ALIAS[k] for k in _PROMOTER_SET_ALIAS},
                    selected=list(PROMOTER_SET_LEVELS),
                ),
                ui.input_switch(
                    "cm_common_regulators_only",
                    ui.tooltip(
                        ui.span("Common regulators only"),
                        "When on, each perturbation table is restricted to"
                        " regulators present in every promoter set x method cell,"
                        " computed separately per perturbation dataset -- so"
                        " percentages across the table are always comparable"
                        " apples-to-apples instead of over different N.",
                        placement="right",
                    ),
                    value=False,
                ),
            )

        return ui.span()

    @render.ui
    def analysis_status() -> ui.Tag:
        """
        Status message when dataset selection is incomplete.

        :trigger: ``active_binding_datasets`` / ``active_perturbation_datasets``.

        """
        if not active_binding_datasets() or not active_perturbation_datasets():
            return ui.div(
                {"class": "empty-state"},
                ui.p("Select at least one binding and one perturbation dataset."),
            )
        return ui.span()

    # ---------------------------------------------------------------------------
    # Tab 1: Compare Datasets — matrix + distribution
    # ---------------------------------------------------------------------------

    def _make_cd_row_effect(b_db: str) -> None:
        @reactive.effect
        @reactive.event(input[f"topnrow_{b_db}"])
        def _on_row() -> None:
            cd_selected_binding.set(b_db)
            cd_selected_perturbation.set(None)

    def _make_cd_col_effect(p_db: str) -> None:
        @reactive.effect
        @reactive.event(input[f"topncol_{p_db}"])
        def _on_col() -> None:
            cd_selected_perturbation.set(p_db)
            cd_selected_binding.set(None)

    for _b in _all_binding_dbs:
        _make_cd_row_effect(_b)
    for _p in _all_perturbation_dbs:
        _make_cd_col_effect(_p)

    @render.ui
    def cd_matrix_container() -> ui.Tag:
        """
        Binding × perturbation top-N responsive ratio matrix.

        :trigger: ``_cd_data`` — re-renders when data changes.
        :trigger: ``cd_selected_binding`` / ``cd_selected_perturbation`` — highlights.

        """
        if (msg := _dto_unavailable()) is not None:
            return msg
        with perf(session.id, "comparison.workspace", "cd_matrix_container"):
            df = _cd_data()
            b_dbs = _cd_binding_dbs()
            p_dbs = active_perturbation_datasets()
            if not b_dbs or not p_dbs:
                return ui.div(
                    {"class": "empty-state"},
                    ui.p("No datasets selected."),
                )

            topn_medians: dict[tuple[str, str], float | None] = {}
            if not df.empty:
                med_df = duckdb.execute(
                    """
                    SELECT binding_db, perturbation_db,
                        median(percent_responsive) AS med
                    FROM df
                    GROUP BY binding_db, perturbation_db
                """
                ).df()
                topn_medians = {
                    (row.binding_db, row.perturbation_db): (
                        float(row.med) if pd.notna(row.med) else None
                    )
                    for row in med_df.itertuples(index=False)
                }

            def _col_tooltip(p_db: str) -> str:
                note = _metric_note(p_db)
                return (
                    f"{note}. "
                    "Click to view distributions for this perturbation dataset."
                )

            return build_topn_matrix_ui(
                binding_datasets=b_dbs,
                perturbation_datasets=p_dbs,
                topn_medians=topn_medians,
                display_names={
                    **display_names,
                    **binding_index.label,
                    **PERTURBATION_LABEL_MAP,
                },
                selected_binding=cd_selected_binding(),
                selected_perturbation=cd_selected_perturbation(),
                ns=session.ns,
                col_tooltip=_col_tooltip,
            )

    @render.ui
    def cd_distribution_container() -> ui.Tag:
        """
        Box plots for the selected matrix row or column.

        :trigger: ``_cd_data`` — re-renders when data changes.
        :trigger: ``cd_selected_binding`` / ``cd_selected_perturbation`` — selection.

        """
        if (msg := _dto_unavailable()) is not None:
            return msg
        if _read_metric(input) == METRIC_DTO:
            # DTO yields one percentage per dataset pair, not a per-regulator spread,
            # so there is no distribution to draw.
            return ui.div(
                {"class": "empty-state"},
                ui.p(
                    "Distributions are only available for the Top-N metric. DTO"
                    " produces a single percentage per dataset pair rather than a"
                    " per-regulator value."
                ),
            )
        with perf(session.id, "comparison.workspace", "cd_distribution_container"):
            df = _cd_data()
            if df.empty:
                return ui.span()

            b_sel = cd_selected_binding()
            p_sel = cd_selected_perturbation()

            if b_sel is None and p_sel is None:
                return ui.div(
                    {"class": "empty-state"},
                    ui.p(
                        "Click a row header to view distributions for a binding"
                        " dataset, or a column header to view distributions for a"
                        " perturbation dataset."
                    ),
                )

            if b_sel is not None:
                sub = df[df["binding_db"] == b_sel]
                x_col = "perturbation_source"
            else:
                sub = df[df["perturbation_db"] == p_sel]
                x_col = "binding_label"

            if sub.empty:
                return ui.div(
                    {"class": "empty-state"},
                    ui.p("No data for the selected datasets."),
                )

            fig = go.Figure()
            x_vals = sorted(sub[x_col].dropna().unique(), key=lambda v: str(v))
            for x_val in x_vals:
                grp = sub[sub[x_col] == x_val]
                mask = grp["percent_responsive"].notna()
                fig.add_trace(
                    go.Box(
                        x=grp.loc[mask, x_col].values,
                        y=grp.loc[mask, "percent_responsive"].values,
                        name=str(x_val),
                        text=grp.loc[mask, "regulator_label"].values,
                        hovertemplate="%{text}<br>%{y:.1f}%<extra></extra>",
                        hoveron="points",
                        boxpoints="all",
                        jitter=0.4,
                        pointpos=0,
                        marker=dict(size=4, opacity=0.5),
                        line=dict(width=1.5),
                        showlegend=False,
                    )
                )

            if not fig.data:
                return ui.span()

            y_title = (
                "% regulators with DTO p < 0.01"
                if _read_metric(input) == METRIC_DTO
                else "% responsive in top N"
            )
            fig.update_yaxes(title_text=y_title, range=[0, 100])
            fig.update_layout(margin=dict(l=50, r=20, t=40, b=80))
            return ui.div(
                {"style": "margin-top: 1.5rem;"},
                ui.HTML(to_html(fig, include_plotlyjs=False, full_html=False)),
            )

    # ---------------------------------------------------------------------------
    # Tab 2: Compare Promoter Definitions
    # ---------------------------------------------------------------------------

    @render.ui
    def cp_promoter_table() -> ui.Tag:
        """
        Per-perturbation table comparing top-N % responsive across promoter sets.

        :trigger: ``_cp_data`` — re-renders when data changes.

        """
        if (msg := _dto_unavailable()) is not None:
            return msg
        with perf(session.id, "comparison.workspace", "cp_promoter_table"):
            agg = _cp_data()
            p_dbs = active_perturbation_datasets()
            if not p_dbs:
                return ui.div(
                    {"class": "empty-state"},
                    ui.p("No perturbation datasets selected."),
                )
            if agg.empty:
                return ui.div(
                    {"class": "empty-state"},
                    ui.p("No data for the selected datasets."),
                )

            try:
                selected_ps = set(input.cp_included_promoter_sets())
            except Exception:
                selected_ps = set(_PROMOTER_SET_ALIAS)
            # Keep the canonical column order regardless of checkbox click order.
            included_ps = [ps for ps in PROMOTER_SET_LEVELS if ps in selected_ps]

            _th_style = "padding: 6px 10px; text-align: right;"

            lookup: dict[tuple[str, str, str], float] = {
                (
                    row.perturbation_db,
                    row.binding_base_label,
                    row.promoter_set_id,
                ): row.val
                for row in agg.itertuples(index=False)
            }

            cards: list[ui.Tag] = []
            for p_db in p_dbs:
                p_label = PERTURBATION_LABEL_MAP.get(p_db, p_db)
                sub_agg = agg[agg["perturbation_db"] == p_db]
                if sub_agg.empty:
                    continue

                binding_base_labels = [
                    b for b in _BINDING_ORDER if b in set(sub_agg["binding_base_label"])
                ]

                header_cells = [
                    ui.tags.th(
                        "Binding Dataset",
                        style="padding: 6px 10px; text-align: left;",
                    )
                ]
                for ps in included_ps:
                    header_cells.append(
                        ui.tags.th(
                            ui.tooltip(
                                ui.span(PROMOTER_SET_LABELS.get(ps, ps)),
                                _PROMOTER_TOOLTIPS.get(ps, ""),
                            ),
                            style=_th_style,
                        )
                    )

                data_rows: list[ui.Tag] = []
                for base_label in binding_base_labels:
                    row_cells = [
                        ui.tags.td(
                            base_label,
                            style=(
                                "padding: 6px 10px; text-align: left; "
                                "white-space: nowrap;"
                            ),
                        )
                    ]
                    for ps in included_ps:
                        val = lookup.get((p_db, base_label, ps))
                        if val is not None and pd.notna(val):
                            row_cells.append(
                                ui.tags.td(f"{val:.1f}%", style=_cell_style(val))
                            )
                        else:
                            row_cells.append(
                                ui.tags.td(
                                    "-", style="padding: 6px 10px; text-align: right;"
                                )
                            )
                    data_rows.append(ui.tags.tr(*row_cells))

                if not data_rows:
                    continue

                cards.append(
                    ui.div(
                        {
                            "style": (
                                "flex: 0 0 auto; min-width: 260px;"
                                " border: 1px solid #ddd;"
                                " border-radius: 4px; overflow: hidden;"
                            )
                        },
                        ui.div(
                            {
                                "style": (
                                    "padding: 6px 10px; font-weight: 600;"
                                    " font-size: 0.9rem; background-color: #f5f5f5;"
                                    " border-bottom: 1px solid #ddd;"
                                )
                            },
                            ui.tooltip(
                                ui.span(p_label),
                                _metric_note(p_db),
                            ),
                        ),
                        ui.tags.table(
                            {
                                "style": (
                                    "border-collapse: collapse;"
                                    " font-size: 0.9rem; width: 100%;"
                                )
                            },
                            ui.tags.thead(
                                {"style": "background-color: #f5f5f5;"},
                                ui.tags.tr(*header_cells),
                            ),
                            ui.tags.tbody(*data_rows),
                        ),
                    )
                )

            if not cards:
                return ui.div(
                    {"class": "empty-state"},
                    ui.p("No data for the selected combination."),
                )

            return ui.div(
                {"style": "margin-top: 0.5rem;"}, scroll_row(*cards, gap="lg")
            )

    # ---------------------------------------------------------------------------
    # Tab 3: Compare Analysis Methods
    # ---------------------------------------------------------------------------

    @render.ui
    def cm_method_table() -> ui.Tag:
        """
        Per-perturbation table comparing promoter enrichment against peak calling.

        One card per perturbation dataset. Columns are the checked promoter
        definitions; rows are the two binding methods, with a shared regulator
        count footer. The original authors' peaks are excluded -- they have no
        fixed promoter window, so they do not belong to any column.

        :trigger: ``_cm_data`` — re-renders when data changes.

        """
        if (msg := _dto_unavailable()) is not None:
            return msg
        with perf(session.id, "comparison.workspace", "cm_method_table"):
            agg = _cm_data()
            p_dbs = active_perturbation_datasets()
            if not p_dbs:
                return ui.div(
                    {"class": "empty-state"},
                    ui.p("No perturbation datasets selected."),
                )
            if agg.empty:
                return ui.div(
                    {"class": "empty-state"},
                    ui.p("No data for the selected combination."),
                )

            binding_db = _cm_selected_binding_db()
            binding_label = binding_index.base_label.get(binding_db, binding_db)
            peak_note = PEAK_CALLER_NOTES.get(
                binding_db,
                "Peaks called over the same promoter definition used by the"
                " promoter-enrichment row.",
            )
            _th_style = "padding: 6px 10px; text-align: right;"
            _row_label_style = (
                "padding: 6px 10px; text-align: left; white-space: nowrap;"
            )

            ps_present = [
                ps for ps in PROMOTER_SET_LEVELS if ps in set(agg["promoter_set_id"])
            ]
            methods_present = [
                m for m in METHOD_LEVELS if m in set(agg["binding_method_id"])
            ]
            if not ps_present or not methods_present:
                return ui.span()

            lookup: dict[tuple[str, str, str], float] = {}
            n_reg_lookup: dict[tuple[str, str, str], int] = {}
            for row in agg.itertuples(index=False):
                key = (
                    row.perturbation_db,
                    row.promoter_set_id,
                    row.binding_method_id,
                )
                lookup[key] = row.val
                n_reg_lookup[key] = row.n_regulators

            cards: list[ui.Tag] = []
            for p_db in p_dbs:
                p_label = PERTURBATION_LABEL_MAP.get(p_db, p_db)
                sub_agg = agg[agg["perturbation_db"] == p_db]
                if sub_agg.empty:
                    continue

                header_cells = [
                    ui.tags.th(
                        "Method",
                        style="padding: 6px 10px; text-align: left;",
                    )
                ]
                for ps in ps_present:
                    header_cells.append(
                        ui.tags.th(
                            ui.tooltip(
                                ui.span(PROMOTER_SET_LABELS.get(ps, ps)),
                                _PROMOTER_TOOLTIPS.get(ps, ""),
                            ),
                            style=f"{_th_style} font-weight: 600;",
                        )
                    )

                data_rows_cm: list[ui.Tag] = []
                for method_id in methods_present:
                    method_label = BINDING_METHOD_LABELS.get(method_id, method_id)
                    color = BINDING_METHOD_COLORS.get(method_id, "#888888")
                    if method_id == "peak_calling":
                        label_tag: Any = ui.tooltip(
                            ui.span(method_label), peak_note, placement="right"
                        )
                    else:
                        label_tag = ui.span(method_label)
                    row_cells = [
                        ui.tags.td(
                            label_tag,
                            style=(
                                f"{_row_label_style} color: {color};"
                                " font-weight: 600;"
                            ),
                        )
                    ]
                    for ps in ps_present:
                        val = lookup.get((p_db, ps, method_id))
                        if val is not None and pd.notna(val):
                            row_cells.append(
                                ui.tags.td(f"{val:.1f}%", style=_cell_style(val))
                            )
                        else:
                            row_cells.append(ui.tags.td("-", style=_th_style))
                    data_rows_cm.append(ui.tags.tr(*row_cells))

                if not data_rows_cm:
                    continue

                # Footer: regulator count per column. Identical across methods when
                # "Common regulators only" is on; otherwise show the range.
                n_footer_cells = [
                    ui.tags.td(
                        (
                            "N Shared Regulators"
                            if _read_metric(input) == METRIC_DTO
                            else "N Regulators"
                        ),
                        style=(
                            "padding: 4px 10px; text-align: left;"
                            " font-size: 0.8rem; color: #666;"
                        ),
                    )
                ]
                for ps in ps_present:
                    counts = [
                        n_reg_lookup[(p_db, ps, m)]
                        for m in methods_present
                        if (p_db, ps, m) in n_reg_lookup
                    ]
                    if not counts:
                        text = "-"
                    elif min(counts) == max(counts):
                        text = str(min(counts))
                    else:
                        text = f"{min(counts)}-{max(counts)}"
                    n_footer_cells.append(
                        ui.tags.td(
                            text,
                            style=(
                                "padding: 4px 10px; text-align: right;"
                                " font-size: 0.8rem; color: #666;"
                            ),
                        )
                    )
                data_rows_cm.append(ui.tags.tr(*n_footer_cells))

                cards.append(
                    ui.div(
                        {
                            "style": (
                                "flex: 0 0 auto; min-width: 260px;"
                                " border: 1px solid #ddd;"
                                " border-radius: 4px; overflow: hidden;"
                            )
                        },
                        ui.div(
                            {
                                "style": (
                                    "padding: 6px 10px; font-weight: 600;"
                                    " font-size: 0.9rem; background-color: #f5f5f5;"
                                    " border-bottom: 1px solid #ddd;"
                                )
                            },
                            ui.tooltip(
                                ui.span(f"{p_label} — {binding_label}"),
                                _metric_note(p_db),
                            ),
                        ),
                        ui.tags.table(
                            {
                                "style": (
                                    "border-collapse: collapse;"
                                    " font-size: 0.9rem; width: 100%;"
                                )
                            },
                            ui.tags.thead(
                                {"style": "background-color: #f5f5f5;"},
                                ui.tags.tr(*header_cells),
                            ),
                            ui.tags.tbody(*data_rows_cm),
                        ),
                    )
                )

            if not cards:
                return ui.div(
                    {"class": "empty-state"},
                    ui.p("No data for the selected combination."),
                )

            return ui.div(
                {
                    "style": (
                        "margin-top: 0.5rem; display: flex;"
                        " flex-direction: column; gap: 1.5rem;"
                    )
                },
                *cards,
            )

    # ---------------------------------------------------------------------------
    # Tab 4: Method x Promoter Model
    # ---------------------------------------------------------------------------

    @reactive.calc
    def _mm_data() -> dict[str, tuple[pd.DataFrame, pd.DataFrame]]:
        """
        Precomputed method x promoter-set model results, one entry per active
        perturbation dataset.

        Reads only -- the model itself is fit once, offline, by
        ``tfbpshiny materialize`` (see ``materialize/comparison/
        method_promoter_model.py``). No fitting happens in the app.

        :trigger: ``input.top_n`` / ``input.responsiveness_preset`` — shared sidebar
            controls.
        :trigger: ``active_perturbation_datasets`` — committed dataset selection.

        """
        n = _read_top_n(input)
        preset_name = _read_preset_name(input)
        out: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
        with perf(session.id, "comparison.workspace", "_mm_data", kind="data"):
            for p_db in active_perturbation_datasets():
                try:
                    out[p_db] = fetch_method_promoter_model(conn, p_db, n, preset_name)
                except Exception:
                    logger.exception("mm_data fetch failed for %s", p_db)
        return out

    @reactive.calc
    def _mm_target_universe() -> pd.DataFrame:
        """
        Per-assay size of the cross-promoter-set target intersection.

        Materialized once, offline (see ``materialize/comparison/
        method_promoter_model.py::promoter_set_target_universe``); does not depend on
        the selected perturbation dataset, top-N, or preset, so this is read once and
        reused across every panel :func:`mm_model_tables` draws.

        :trigger: None -- this table has exactly one row per assay, always.

        """
        with perf(
            session.id, "comparison.workspace", "_mm_target_universe", kind="data"
        ):
            try:
                return fetch_method_promoter_target_universe(conn)
            except Exception:
                logger.exception("mm_target_universe fetch failed")
                return pd.DataFrame(
                    columns=["assay_primary", "display_name", "n_targets"]
                )

    @render.ui
    def mm_model_tables() -> ui.Tag:
        """
        Method x promoter-set model: target-universe sizes, fit summary and
        coefficients.

        One panel per active perturbation dataset, matching every other tab in this
        module. The model itself is precomputed (see ``_mm_data``); this only formats
        it. A fixed-effects OLS (regulator + assay as covariates), not a mixed model --
        cluster-robust standard errors by regulator, not a variance-component
        decomposition. Baselines are ``peak_calling`` and ``intergenic``, so every
        displayed method/promoter-set coefficient reads as a contrast against those.

        :trigger: ``_mm_data``, ``_mm_target_universe``.

        """
        with perf(session.id, "comparison.workspace", "mm_model_tables"):
            data = _mm_data()
            p_dbs = active_perturbation_datasets()
            if not p_dbs:
                return ui.div(
                    {"class": "empty-state"},
                    ui.p("No perturbation datasets selected."),
                )
            universe_df = _mm_target_universe()
            panels: list[Any] = []
            if not universe_df.empty:
                n_targets_values = universe_df["n_targets"].unique()
                if len(n_targets_values) == 1:
                    # The intersection is a property of genome annotation (which
                    # genes have a defined promoter window in all four promoter
                    # sets), not of the assay, so every assay lands on the same
                    # number -- confirmed live against both Rossi and ChEC-seq.
                    caption = (
                        "The regression is performed over the"
                        f" {int(n_targets_values[0])} targets in the intersect"
                        " between all four promoter set definitions."
                    )
                else:
                    items = ", ".join(
                        f"{row['display_name']}: {int(row['n_targets'])} targets"
                        for _, row in universe_df.iterrows()
                    )
                    caption = (
                        "Every cell below is ranked over the intersection of"
                        " targets present in all four promoter sets' promoter-"
                        f" enrichment data, per assay -- {items}."
                    )
                panels.append(ui.p(ui.tags.em(caption), style="margin-bottom: 1rem;"))
            for p_db in p_dbs:
                bundle = data.get(p_db)
                p_label = PERTURBATION_LABEL_MAP.get(p_db, p_db)
                if bundle is None or bundle[1].empty:
                    panels.append(
                        ui.div(
                            {"class": "empty-state"},
                            ui.p(
                                f"{p_label}: no model results for this cutoff/preset."
                                " Rebuild with ",
                                ui.tags.code("tfbpshiny materialize"),
                                " to compute the method x promoter-set model.",
                            ),
                        )
                    )
                    continue

                coefs, fit_summary = bundle
                summ = fit_summary.iloc[0]
                if not summ["converged"]:
                    panels.append(
                        ui.div(
                            {"class": "empty-state"},
                            ui.p(
                                ui.strong(f"{p_label}: model did not converge."),
                                f" {summ['note'] or ''}",
                            ),
                        )
                    )
                    continue

                summary_text = (
                    f"{int(summ['n_obs'])} observations,"
                    f" {int(summ['n_regulators'])} regulators, R² ="
                    f" {summ['r_squared']:.2f}."
                )
                panels.append(
                    ui.div(
                        {
                            "style": (
                                "border: 1px solid #ddd; border-radius: 4px;"
                                " padding: 12px; margin-bottom: 1.5rem;"
                            )
                        },
                        ui.h4(p_label, style="margin-top: 0;"),
                        ui.p(ui.tags.em(summary_text)),
                        _summary_table(
                            coefs,
                            [
                                ("term", "term", ""),
                                ("estimate", "Estimate (pp)", ".3f"),
                                ("std_error", "Std. Error (pp)", ".3f"),
                                ("t_value", "t value", ".2f"),
                                ("p_value", "Pr(>|t|)", ".3g"),
                            ],
                            label_col="term",
                        ),
                    )
                )
            return ui.div(*panels)


__all__ = ["comparison_workspace_server"]
