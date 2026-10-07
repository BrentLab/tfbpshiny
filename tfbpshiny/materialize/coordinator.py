"""
Materialization coordinator.

Imports SQL generators from the submodules and executes them in dependency
order against both VirtualDB (data source) and the output DuckDB file (target).
Data is transferred as pandas DataFrames via ``vdb.query()`` → output
``conn.register()`` / ``conn.execute()``.

"""

from __future__ import annotations

import argparse
import itertools
import logging
import time
from typing import Any

import duckdb
import pandas as pd
from labretriever import VirtualDB

from tfbpshiny.materialize.comparison.agreement import (
    AGREEMENT_EXCLUDED,
    agreement_pair_select_sql,
    agreement_rank_column,
    agreement_schema_sql,
)
from tfbpshiny.materialize.comparison.callingcards_authors_bound import (
    CALLINGCARDS_BINDING_VIEW,
    callingcards_authors_bound_select_sql,
)
from tfbpshiny.materialize.comparison.correlations import (
    BINDING_DATASET_COLUMNS,
    PERTURBATION_DATASET_COLUMNS,
    correlation_pair_select_sql,
    correlations_schema_sql,
)
from tfbpshiny.materialize.comparison.dto import (
    DTO_INSERT_COLUMNS,
    dto_resolve_regulators_sql,
    dto_schema_sql,
    dto_select_sql,
)
from tfbpshiny.materialize.comparison.harbison_authors_bound import (
    HARBISON_BINDING_VIEW,
    harbison_authors_bound_select_sql,
)
from tfbpshiny.materialize.comparison.method_promoter_model import (
    ASSAY_PRIMARIES,
    COEFS_COLUMNS,
    FIT_SUMMARY_COLUMNS,
    build_method_promoter_panel,
    fit_method_promoter_model,
    method_promoter_model_schema_sql,
    method_promoter_model_target_universe_schema_sql,
    method_promoter_model_topn_schema_sql,
    promoter_set_target_universe,
    resolve_panel_cells,
)
from tfbpshiny.materialize.comparison.target_sets import (
    TARGET_SET_BINDING,
    TARGET_SET_PERTURBATION,
    target_sets_schema_sql,
    target_sets_select_sql,
)

# TOPN_PERTURBATION_COLUMNS is aliased because correlations.py (imported above) defines
# an identical map under the same name. The staged top-N path must follow the top-N
# module's copy rather than silently inherit the other if the two ever diverge.
from tfbpshiny.materialize.comparison.topn import (
    BINDING_TOPN_CONFIGS,
    PEAK_BINDING_DATASETS,
)
from tfbpshiny.materialize.comparison.topn import (
    PERTURBATION_DATASET_COLUMNS as TOPN_PERTURBATION_COLUMNS,
)
from tfbpshiny.materialize.comparison.topn import (
    PERTURBATION_TOPN_DATASETS,
    TOP_N_ALL,
    binding_stage_sql,
    perturbation_stage_sql,
    topn_pair_select_sql_v2,
    topn_schema_sql,
)
from tfbpshiny.materialize.coordinating.sql import (
    DATASET_HF_COORDS,
    binding_methods_sql,
    column_metadata_sql,
    comparative_registry_sql,
    dataset_registry_sql,
    promoter_sets_sql,
    sample_regulator_sql,
)
from tfbpshiny.materialize.metadata.sql import (
    meta_select_sql,
    regulator_display_names_select_sql,
)
from tfbpshiny.materialize.rounding import (
    DEFAULT_FLOAT_DECIMALS,
    NO_ROUNDING,
)
from tfbpshiny.utils.vdb_init import DEFAULT_RESPONSIVENESS_PRESETS

logger = logging.getLogger("shiny")

_DEFAULT_REGULATORS_PER_CHUNK = 400


def _exec_static(conn: duckdb.DuckDBPyConnection, sql: str, label: str) -> None:
    """Execute a SQL block (possibly multi-statement) against the output connection."""
    t0 = time.monotonic()
    conn.execute(sql)
    logger.info("  %-40s  %.2fs", label, time.monotonic() - t0)


def _vdb_to_table(
    vdb: VirtualDB,
    output_conn: duckdb.DuckDBPyConnection,
    select_sql: str,
    params: dict[str, Any],
    target_table: str,
    label: str,
    mode: str = "create",
    columns: list[str] | None = None,
) -> int:
    """
    Execute a SELECT against VirtualDB and write the result to the output connection.

    :param vdb: VirtualDB instance (data source).
    :param output_conn: Output DuckDB connection (target).
    :param select_sql: SELECT SQL to execute against vdb.
    :param params: Named parameters for the SELECT (``$name`` syntax).
    :param target_table: Table name in the output database.
    :param label: Short label used in log messages.
    :param mode: ``'create'`` → ``CREATE TABLE … AS SELECT *``; ``'insert'`` →
        ``INSERT INTO … SELECT *``.
    :param columns: Target column names for ``'insert'`` mode, in SELECT order. Pass
        this only when the target table has columns the SELECT does not supply (e.g.
        ``dto.regulator_locus_tag``, filled afterwards from ``sample_regulator``).
        Leave as ``None`` to insert positionally, which is what every other caller
        wants -- some SELECTs contain unaliased expressions whose DataFrame column
        names are the expression text, not the target column name.
    :returns: Number of rows written.
    :rtype: int

    """
    t0 = time.monotonic()
    df = vdb.query(select_sql, **params)
    # DuckDB corr() can return NaN (a valid IEEE 754 float, not SQL NULL) for
    # zero-variance inputs.  The pandas→Arrow→DuckDB round-trip converts those
    # NaN floats to SQL NULL, which violates NOT NULL constraints.  Drop them
    # here so the SQL-level filter (`NOT isnan`) and this both agree.
    df = df.dropna(how="any")
    row_count = len(df)
    if row_count == 0:
        logger.debug("  %-40s  (0 rows, skipped)", label)
        return 0

    output_conn.register("_tmp_df", df)
    try:
        if mode == "create":
            output_conn.execute(
                f'CREATE TABLE "{target_table}" AS SELECT * FROM _tmp_df'
            )
        elif columns:
            col_list = ", ".join(f'"{c}"' for c in columns)
            output_conn.execute(
                f'INSERT INTO "{target_table}" ({col_list}) SELECT * FROM _tmp_df'
            )
        else:
            output_conn.execute(f'INSERT INTO "{target_table}" SELECT * FROM _tmp_df')
    finally:
        output_conn.unregister("_tmp_df")

    logger.info(
        "  %-40s  %d rows  %.2fs",
        label,
        row_count,
        time.monotonic() - t0,
    )
    return row_count


def _topn_plan(
    binding_db: str,
    perturbation_db: str,
    top_n_values: list[int],
    effect_thresholds: list[float],
    pvalue_thresholds: list[float],
    preset_names: list[str] | None = None,
) -> tuple[tuple[int, ...], tuple[tuple[float, float], ...]]:
    """
    Return the cutoffs and threshold pairs to materialize for one pair, unexpanded.

    The staged path emits every combination from a single query, so it wants the two
    axes rather than their cross product.

    :param binding_db: Binding dataset name.
    :param perturbation_db: Perturbation dataset name.
    :param top_n_values: Rank cutoffs from the CLI.
    :param effect_thresholds: Effect cutoffs from the CLI.
    :param pvalue_thresholds: P-value cutoffs from the CLI.
    :param preset_names: Responsiveness presets whose thresholds to include.
    :returns:``(cutoffs, threshold_pairs)``, each in a stable order.

    """
    threshold_pairs: list[tuple[float, float]] = [
        (e, pv) for e in effect_thresholds for pv in pvalue_thresholds
    ]
    for preset_name in preset_names or []:
        preset = DEFAULT_RESPONSIVENESS_PRESETS.get(preset_name, {})
        pair = preset.get(perturbation_db, preset.get("*"))
        if pair is not None and pair not in threshold_pairs:
            threshold_pairs.append(pair)

    # Peak datasets carry the authors' binding call, so they also get the
    # no-rank-cutoff variant.
    cutoffs = list(top_n_values)
    if binding_db in PEAK_BINDING_DATASETS:
        cutoffs.append(TOP_N_ALL)

    return tuple(cutoffs), tuple(threshold_pairs)


def _regulators_for_binding(vdb: VirtualDB, binding_view: str) -> list[str]:
    """Return distinct regulator locus tags for a binding dataset (sorted)."""
    df = vdb.query(f"SELECT DISTINCT regulator_locus_tag FROM {binding_view}_meta")
    return sorted(t for t in df["regulator_locus_tag"].dropna().tolist())


def _batches(regulators: list[str], chunk: int) -> list[tuple[str, ...]]:
    """Split regulators into chunks, or one empty batch meaning "no restriction"."""
    return [
        tuple(regulators[i : i + chunk]) for i in range(0, len(regulators), chunk)
    ] or [()]


def _topn_staged(
    vdb: VirtualDB,
    conn: duckdb.DuckDBPyConnection,
    binding_views: list[str],
    perturbation_views: list[str],
    top_n_values: list[int],
    effect_thresholds: list[float],
    pvalue_thresholds: list[float],
    preset_names: list[str] | None,
    chunk: int,
    round_decimals: int,
) -> int:
    """
    Fill ``topn_results`` by scanning each source once (stages A, B and C).

    The legacy path rescanned both parquet sources for every ``(top_n, effect,
    pvalue)`` variant -- roughly 1170 full scans for a complete build, with Rossi's
    8.7 M-row config re-read some 60 times. Here each perturbation dataset is
    materialized once up front and each binding dataset once as its loop iteration
    begins, so the per-pair query touches only those two tables.

    Binding is the outer loop so at most one binding intermediate is resident.

    :param vdb: VirtualDB instance (data source; intermediates live on its connection).
    :param conn: Output DuckDB connection.
    :param binding_views: Binding dataset names to process.
    :param perturbation_views: Perturbation dataset names to process.
    :param top_n_values: Rank cutoffs from the CLI.
    :param effect_thresholds: Effect cutoffs from the CLI.
    :param pvalue_thresholds: P-value cutoffs from the CLI.
    :param preset_names: Responsiveness presets whose thresholds to include.
    :param chunk: Regulators per batch.
    :param round_decimals: Decimal places kept for ``responsive_ratio``.
    :returns: Number of query units executed against the intermediates.

    """
    pert_tables: dict[str, str] = {}
    units = 0
    try:
        # Stage B: once per perturbation dataset, reused by every binding dataset.
        for p_db in perturbation_views:
            table = f"_mat_pert_{p_db}"
            p_sql, p_params = perturbation_stage_sql(p_db)
            t0 = time.monotonic()
            vdb._conn.execute(f"CREATE OR REPLACE TABLE {table} AS {p_sql}", p_params)
            pert_tables[p_db] = table
            logger.info("  %-40s  %.2fs", f"stage B {p_db}", time.monotonic() - t0)

        for b_db in binding_views:
            b_cfg = BINDING_TOPN_CONFIGS[b_db]
            b_hf_repo, b_hf_config = DATASET_HF_COORDS.get(b_db, ("", ""))

            # Stage A: once per binding dataset, dropped before the next one.
            b_sql, b_params = binding_stage_sql(
                binding_view=b_db,
                binding_sample_col=b_cfg["binding_sample_col"],
                rank_col=b_cfg["rank_col"],
                target_blacklist=b_cfg.get("target_blacklist", ()),
                binding_dedup_cte=b_cfg.get("binding_dedup_cte", ""),
                no_signal_value=b_cfg.get("no_signal_value"),
            )
            t0 = time.monotonic()
            vdb._conn.execute(
                f"CREATE OR REPLACE TABLE _mat_binding AS {b_sql}", b_params
            )
            logger.info("  %-40s  %.2fs", f"stage A {b_db}", time.monotonic() - t0)

            # Hoisted out of the perturbation loop: it does not depend on p_db.
            batches = _batches(_regulators_for_binding(vdb, b_db), chunk)

            try:
                for p_db in perturbation_views:
                    p_hf_repo, p_hf_config = DATASET_HF_COORDS.get(p_db, ("", ""))
                    cutoffs, pairs = _topn_plan(
                        b_db,
                        p_db,
                        top_n_values,
                        effect_thresholds,
                        pvalue_thresholds,
                        preset_names,
                    )
                    pair_rows = 0
                    for batch_idx, batch in enumerate(batches):
                        sql, params = topn_pair_select_sql_v2(
                            binding_table="_mat_binding",
                            binding_hf_repo=b_hf_repo,
                            binding_hf_config=b_hf_config,
                            perturbation_table=pert_tables[p_db],
                            pert_hf_repo=p_hf_repo,
                            pert_hf_config=p_hf_config,
                            rank_col=b_cfg["rank_col"],
                            rank_asc=b_cfg["rank_asc"],
                            top_n_values=cutoffs,
                            threshold_pairs=pairs,
                            has_pvalue=bool(TOPN_PERTURBATION_COLUMNS[p_db][1]),
                            regulator_subset=batch,
                            param_prefix=f"bp{batch_idx}",
                            round_decimals=round_decimals,
                        )
                        units += 1
                        pair_rows += _vdb_to_table(
                            vdb,
                            conn,
                            sql,
                            params,
                            "topn_results",
                            f"topn {b_db}×{p_db} batch {batch_idx + 1}/{len(batches)}",
                            mode="insert",
                        )
                    logger.info(
                        "  %-40s  total %d rows",
                        f"topn {b_db}×{p_db}",
                        pair_rows,
                    )
            finally:
                vdb._conn.execute("DROP TABLE IF EXISTS _mat_binding")
    finally:
        # Never leave intermediates on the long-lived vdb connection.
        for table in pert_tables.values():
            vdb._conn.execute(f"DROP TABLE IF EXISTS {table}")
        vdb._conn.execute("DROP TABLE IF EXISTS _mat_binding")
    return units


def _method_promoter_topn_staged(
    vdb: VirtualDB,
    conn: duckdb.DuckDBPyConnection,
    registry_df: pd.DataFrame,
    perturbation_views: list[str],
    top_n_values: list[int],
    preset_names: list[str] | None,
    chunk: int,
    round_decimals: int,
) -> int:
    """
    Fill ``method_promoter_model_topn``, ranking each of the 16 cells over its assay's
    cross-promoter-set target intersection rather than its own full target list (see
    ``method_promoter_model.py``'s module docstring for why). Structured exactly like
    :func:`_topn_staged` -- perturbation datasets staged once and reused, one binding
    intermediate resident at a time -- restricted to the 16 (assay, promoter_set,
    method) cells this model needs, and with each binding stage additionally filtered to
    its assay's intersected target universe.

    Also fills ``method_promoter_model_target_universe`` (one row per assay, its
    intersection's size) as a side effect of computing ``universes`` below -- the live
    app has no ``vdb`` of its own to recompute it, so it must be persisted here.

    :param vdb: VirtualDB instance (data source; intermediates live on its
        connection).
    :param conn: Output DuckDB connection.
    :param registry_df: ``dataset_registry`` rows.
    :param perturbation_views: Perturbation dataset names to process.
    :param top_n_values: Rank cutoffs from the CLI.
    :param preset_names: Responsiveness presets whose thresholds to include.
    :param chunk: Regulators per batch.
    :param round_decimals: Decimal places kept for ``responsive_ratio``.
    :returns: Number of query units executed against the intermediates.

    """
    cells = resolve_panel_cells(registry_df)
    universes = {
        assay_primary: promoter_set_target_universe(vdb, registry_df, assay_primary)
        for assay_primary in ASSAY_PRIMARIES
    }

    universe_sizes = pd.DataFrame(
        [
            {"assay_primary": assay_primary, "n_targets": len(universe)}
            for assay_primary, universe in universes.items()
        ]
    )
    conn.register("_tmp_mpm_universe", universe_sizes)
    try:
        conn.execute(
            "INSERT INTO method_promoter_model_target_universe"
            " SELECT * FROM _tmp_mpm_universe"
        )
    finally:
        conn.unregister("_tmp_mpm_universe")

    pert_tables: dict[str, str] = {}
    units = 0
    try:
        for p_db in perturbation_views:
            table = f"_mat_mpm_pert_{p_db}"
            p_sql, p_params = perturbation_stage_sql(p_db)
            t0 = time.monotonic()
            vdb._conn.execute(f"CREATE OR REPLACE TABLE {table} AS {p_sql}", p_params)
            pert_tables[p_db] = table
            logger.info("  %-40s  %.2fs", f"stage B {p_db}", time.monotonic() - t0)

        for (assay_primary, promoter_set, method), b_db in cells.items():
            universe = universes.get(assay_primary, frozenset())
            if not universe:
                logger.warning(
                    "  method_promoter_model_topn: no target universe for %s,"
                    " skipping %s/%s/%s",
                    assay_primary,
                    assay_primary,
                    promoter_set,
                    method,
                )
                continue
            b_cfg = BINDING_TOPN_CONFIGS[b_db]
            b_hf_repo, b_hf_config = DATASET_HF_COORDS.get(b_db, ("", ""))

            b_sql, b_params = binding_stage_sql(
                binding_view=b_db,
                binding_sample_col=b_cfg["binding_sample_col"],
                rank_col=b_cfg["rank_col"],
                target_blacklist=b_cfg.get("target_blacklist", ()),
                binding_dedup_cte=b_cfg.get("binding_dedup_cte", ""),
                target_universe=universe,
                no_signal_value=b_cfg.get("no_signal_value"),
            )
            t0 = time.monotonic()
            vdb._conn.execute(
                f"CREATE OR REPLACE TABLE _mat_mpm_binding AS {b_sql}", b_params
            )
            logger.info("  %-40s  %.2fs", f"stage A {b_db}", time.monotonic() - t0)

            batches = _batches(_regulators_for_binding(vdb, b_db), chunk)

            try:
                for p_db in perturbation_views:
                    p_hf_repo, p_hf_config = DATASET_HF_COORDS.get(p_db, ("", ""))
                    cutoffs, pairs = _topn_plan(
                        b_db, p_db, top_n_values, [], [], preset_names
                    )
                    if not pairs:
                        continue
                    pair_rows = 0
                    for batch_idx, batch in enumerate(batches):
                        sql, params = topn_pair_select_sql_v2(
                            binding_table="_mat_mpm_binding",
                            binding_hf_repo=b_hf_repo,
                            binding_hf_config=b_hf_config,
                            perturbation_table=pert_tables[p_db],
                            pert_hf_repo=p_hf_repo,
                            pert_hf_config=p_hf_config,
                            rank_col=b_cfg["rank_col"],
                            rank_asc=b_cfg["rank_asc"],
                            top_n_values=cutoffs,
                            threshold_pairs=pairs,
                            has_pvalue=bool(TOPN_PERTURBATION_COLUMNS[p_db][1]),
                            regulator_subset=batch,
                            param_prefix=f"mpm{batch_idx}",
                            round_decimals=round_decimals,
                        )
                        units += 1
                        pair_rows += _vdb_to_table(
                            vdb,
                            conn,
                            sql,
                            params,
                            "method_promoter_model_topn",
                            f"mpm topn {b_db}×{p_db} batch {batch_idx + 1}"
                            f"/{len(batches)}",
                            mode="insert",
                        )
                    logger.info(
                        "  %-40s  total %d rows",
                        f"mpm topn {b_db}×{p_db}",
                        pair_rows,
                    )
            finally:
                vdb._conn.execute("DROP TABLE IF EXISTS _mat_mpm_binding")
    finally:
        for table in pert_tables.values():
            vdb._conn.execute(f"DROP TABLE IF EXISTS {table}")
        vdb._conn.execute("DROP TABLE IF EXISTS _mat_mpm_binding")
    return units


def materialize(
    output_path: str,
    vdb: VirtualDB,
    args: argparse.Namespace,
) -> None:
    """
    Run the full materialization pipeline, writing to ``output_path``.

    Execution order:
    1. Coordinating layer (registry tables, column metadata)
    2. Metadata layer (``{db_name}_meta`` tables, regulator display names)
    3. Comparison — HF-sourced (``dto``)
    4. Comparison — computed (``topn_results``, ``correlations``)

    :param output_path: Path to the output ``.duckdb`` file.
    :param vdb: VirtualDB instance (all dataset views registered).
    :param args: Parsed CLI args with fields ``methods``, ``top_n_values``,
        ``effect_thresholds``, ``pvalue_thresholds``, ``skip_topn``,
        ``skip_correlations``.

    """
    conn = duckdb.connect(output_path)
    t_total = time.monotonic()

    try:
        # ------------------------------------------------------------------
        # 1. Coordinating layer
        # ------------------------------------------------------------------
        logger.info("=== Phase 1: Coordinating layer ===")
        _exec_static(conn, promoter_sets_sql(), "promoter_sets")
        _exec_static(conn, binding_methods_sql(), "binding_methods")
        _exec_static(conn, dataset_registry_sql(), "dataset_registry")
        _exec_static(conn, comparative_registry_sql(), "comparative_dataset_registry")

        col_meta_sql = column_metadata_sql(vdb)
        _exec_static(conn, col_meta_sql, "dataset_column_metadata")

        # ------------------------------------------------------------------
        # 2. Metadata layer
        # ------------------------------------------------------------------
        logger.info("=== Phase 2: Metadata layer ===")
        datasets = vdb.get_datasets()
        meta_db_names: list[str] = []

        for db_name in datasets:
            meta_view = f"{db_name}_meta"
            row = vdb._conn.execute(
                "SELECT view_name FROM duckdb_views() WHERE view_name = ?",
                [meta_view],
            ).fetchone()
            if row is None:
                continue
            meta_db_names.append(db_name)
            _vdb_to_table(
                vdb,
                conn,
                meta_select_sql(db_name),
                {},
                meta_view,
                f"{meta_view}",
                mode="create",
            )

        reg_names = [
            db
            for db in meta_db_names
            if "regulator_locus_tag" in vdb.get_fields(f"{db}_meta")
        ]
        _vdb_to_table(
            vdb,
            conn,
            regulator_display_names_select_sql(reg_names),
            {},
            "regulator_display_names",
            "regulator_display_names",
            mode="create",
        )

        # (db_name, sample_id) -> regulator_locus_tag, over every meta table that has
        # a regulator column. Consumed by the DTO phase below (which ships only
        # composite identifiers) and by the Comparison module's DTO denominator.
        _exec_static(conn, sample_regulator_sql(reg_names), "sample_regulator")

        # ------------------------------------------------------------------
        # 3. Comparison — HF-sourced (DTO)
        # ------------------------------------------------------------------
        logger.info("=== Phase 3: HF-sourced comparison (DTO) ===")
        # labretriever registers comparative datasets (those with a `links:` block) as
        # `__dto_parquet` + `dto_expanded` and never creates a bare `dto` view, so this
        # must look for the expanded one. Looking for 'dto' here silently skipped the
        # whole phase on every build.
        dto_view = vdb._conn.execute(
            "SELECT view_name FROM duckdb_views() WHERE view_name = 'dto_expanded'"
        ).fetchone()
        if dto_view is None:
            raise RuntimeError(
                "dto_expanded view not found in VirtualDB. The DTO dataset must be "
                "declared with a `links:` block in the collection YAML for "
                "labretriever to build it."
            )
        _exec_static(conn, dto_schema_sql(), "dto (schema)")
        dto_rows = _vdb_to_table(
            vdb,
            conn,
            dto_select_sql(),
            {},
            "dto",
            "dto",
            mode="insert",
            columns=DTO_INSERT_COLUMNS,
        )
        if dto_rows == 0:
            raise RuntimeError("dto_expanded returned no rows")
        _exec_static(conn, dto_resolve_regulators_sql(), "dto (regulators)")
        unresolved = conn.execute(
            "SELECT count(*) FROM dto WHERE regulator_locus_tag IS NULL"
        ).fetchone()[0]
        if unresolved:
            logger.warning(
                "  dto: %d of %d rows have no regulator "
                "(binding sample absent from sample_regulator)",
                unresolved,
                dto_rows,
            )

        # ------------------------------------------------------------------
        # 4. Comparison — computed
        # ------------------------------------------------------------------
        logger.info("=== Phase 4: Computed comparison tables ===")
        top_n_values: list[int] = args.top_n_values
        effect_thresholds: list[float] = args.effect_thresholds
        pvalue_thresholds: list[float] = args.pvalue_thresholds
        methods: list[str] = [m.strip() for m in args.methods.split(",")]
        chunk = _DEFAULT_REGULATORS_PER_CHUNK
        round_decimals: int = getattr(args, "float_decimals", DEFAULT_FLOAT_DECIMALS)
        logger.info(
            "  computed floats rounded to %s",
            (
                "raw (no rounding)"
                if round_decimals == NO_ROUNDING
                else f"{round_decimals} decimals"
            ),
        )

        # ---- topn_results ----
        _exec_static(conn, topn_schema_sql(), "topn_results (schema)")

        if not args.skip_topn:
            binding_views = [db for db in datasets if db in BINDING_TOPN_CONFIGS]
            perturbation_views = [
                db for db in datasets if db in PERTURBATION_TOPN_DATASETS
            ]
            t_topn = time.monotonic()
            n_units = _topn_staged(
                vdb,
                conn,
                binding_views,
                perturbation_views,
                top_n_values,
                effect_thresholds,
                pvalue_thresholds,
                getattr(args, "presets", None),
                chunk,
                round_decimals,
            )
            logger.info(
                "  topn_results: %d query units in %.1fs",
                n_units,
                time.monotonic() - t_topn,
            )
        else:
            logger.info("  topn_results skipped (--skip-topn)")

        # ---- calling cards authors'-threshold rows (figure 3) ----
        # Adds TOP_N_ALL rows for callingcards_500bp using a Poisson-pvalue threshold
        # instead of a rank cutoff -- see callingcards_authors_bound.py for why this
        # cannot go through the same BINDING_TOPN_CONFIGS path as rossi_peaks/
        # chec_m2025_peaks. Depends only on topn_results existing (schema above), not
        # on the ordinary topn phase having run, but is gated the same way since it
        # is conceptually part of populating that table.
        if not args.skip_topn and CALLINGCARDS_BINDING_VIEW in datasets:
            cc_hf = DATASET_HF_COORDS.get(CALLINGCARDS_BINDING_VIEW, ("", ""))
            preset_names = getattr(args, "presets", None) or ["Relaxed", "Stringent"]
            for perturbation_db in sorted(
                db for db in datasets if db in PERTURBATION_TOPN_DATASETS
            ):
                pert_hf = DATASET_HF_COORDS.get(perturbation_db, ("", ""))
                threshold_pairs: list[tuple[float, float]] = []
                for preset_name in preset_names:
                    preset = DEFAULT_RESPONSIVENESS_PRESETS.get(preset_name, {})
                    pair = preset.get(perturbation_db, preset.get("*"))
                    if pair is not None and pair not in threshold_pairs:
                        threshold_pairs.append(pair)
                for effect_threshold, pvalue_threshold in threshold_pairs:
                    sql, params = callingcards_authors_bound_select_sql(
                        binding_hf_repo=cc_hf[0],
                        binding_hf_config=cc_hf[1],
                        perturbation_view=perturbation_db,
                        pert_hf_repo=pert_hf[0],
                        pert_hf_config=pert_hf[1],
                        effect_threshold=effect_threshold,
                        pvalue_threshold=pvalue_threshold,
                        round_decimals=round_decimals,
                    )
                    _vdb_to_table(
                        vdb,
                        conn,
                        sql,
                        params,
                        "topn_results",
                        f"cc_authors_bound {perturbation_db} "
                        f"({effect_threshold}, {pvalue_threshold})",
                        mode="insert",
                    )

        # ---- harbison authors'-threshold rows (figure 3) ----
        # Same shape as the Calling Cards block above: TOP_N_ALL rows for harbison,
        # "bound" meaning pvalue <= HARBISON_PVALUE_THRESHOLD rather than a rank
        # cutoff. See harbison_authors_bound.py.
        if not args.skip_topn and HARBISON_BINDING_VIEW in datasets:
            hb_hf = DATASET_HF_COORDS.get(HARBISON_BINDING_VIEW, ("", ""))
            preset_names = getattr(args, "presets", None) or ["Relaxed", "Stringent"]
            for perturbation_db in sorted(
                db for db in datasets if db in PERTURBATION_TOPN_DATASETS
            ):
                pert_hf = DATASET_HF_COORDS.get(perturbation_db, ("", ""))
                threshold_pairs = []
                for preset_name in preset_names:
                    preset = DEFAULT_RESPONSIVENESS_PRESETS.get(preset_name, {})
                    pair = preset.get(perturbation_db, preset.get("*"))
                    if pair is not None and pair not in threshold_pairs:
                        threshold_pairs.append(pair)
                for effect_threshold, pvalue_threshold in threshold_pairs:
                    sql, params = harbison_authors_bound_select_sql(
                        binding_hf_repo=hb_hf[0],
                        binding_hf_config=hb_hf[1],
                        perturbation_view=perturbation_db,
                        pert_hf_repo=pert_hf[0],
                        pert_hf_config=pert_hf[1],
                        effect_threshold=effect_threshold,
                        pvalue_threshold=pvalue_threshold,
                        round_decimals=round_decimals,
                    )
                    _vdb_to_table(
                        vdb,
                        conn,
                        sql,
                        params,
                        "topn_results",
                        f"harbison_authors_bound {perturbation_db} "
                        f"({effect_threshold}, {pvalue_threshold})",
                        mode="insert",
                    )

        # ---- topn_agreement ----
        # Same-datatype top-N set overlap, for the "agreement between datasets"
        # figure. Every dataset pair is materialized, not just the primaries: the
        # figure's dataset selector lets a reader compare promoter sets and calling
        # methods as well as assays, and which slice is interesting is a read-time
        # question. Only AGREEMENT_EXCLUDED is held back -- see its docstring.
        _exec_static(conn, agreement_schema_sql(), "topn_agreement (schema)")

        if not args.skip_topn:
            # Iterated by type rather than by (type, config map): the perturbation
            # side has no config map, and carrying a None through the loop made every
            # later use of it an Optional index.
            for ctype in ("binding", "perturbation"):
                if ctype == "binding":
                    views = sorted(
                        db
                        for db in datasets
                        if db in BINDING_TOPN_CONFIGS and db not in AGREEMENT_EXCLUDED
                    )
                else:
                    views = sorted(
                        db for db in datasets if db in PERTURBATION_DATASET_COLUMNS
                    )
                logger.info(
                    "  topn_agreement %s: %d datasets, %d pairs",
                    ctype,
                    len(views),
                    len(views) * (len(views) - 1) // 2,
                )
                for view_a, view_b in itertools.combinations(views, 2):
                    hf_a = DATASET_HF_COORDS.get(view_a, ("", ""))
                    hf_b = DATASET_HF_COORDS.get(view_b, ("", ""))
                    if ctype == "binding":
                        cfg_a = BINDING_TOPN_CONFIGS[view_a]
                        cfg_b = BINDING_TOPN_CONFIGS[view_b]
                        col_a, col_b = (
                            cfg_a["binding_sample_col"],
                            cfg_b["binding_sample_col"],
                        )
                        rank_a, asc_a = agreement_rank_column(
                            view_a, cfg_a["rank_col"], cfg_a["rank_asc"]
                        )
                        rank_b, asc_b = agreement_rank_column(
                            view_b, cfg_b["rank_col"], cfg_b["rank_asc"]
                        )
                    else:
                        col_a = col_b = "sample_id"
                        # Ranked by |effect|, so larger is always "more responsive".
                        rank_a, asc_a = agreement_rank_column(
                            view_a, PERTURBATION_DATASET_COLUMNS[view_a][0], False
                        )
                        rank_b, asc_b = agreement_rank_column(
                            view_b, PERTURBATION_DATASET_COLUMNS[view_b][0], False
                        )
                    sql, params = agreement_pair_select_sql(
                        view_a=view_a,
                        hf_repo_a=hf_a[0],
                        hf_config_a=hf_a[1],
                        sample_col_a=col_a,
                        rank_col_a=rank_a,
                        rank_asc_a=asc_a,
                        view_b=view_b,
                        hf_repo_b=hf_b[0],
                        hf_config_b=hf_b[1],
                        sample_col_b=col_b,
                        rank_col_b=rank_b,
                        rank_asc_b=asc_b,
                        comparison_type=ctype,
                        # The recalled peak calls report every promoter with a NULL
                        # score where there was no peak; only scored rows are ranked.
                        drop_null_scores_a=(
                            ctype == "binding"
                            and BINDING_TOPN_CONFIGS[view_a].get("no_signal_value")
                            is not None
                        ),
                        drop_null_scores_b=(
                            ctype == "binding"
                            and BINDING_TOPN_CONFIGS[view_b].get("no_signal_value")
                            is not None
                        ),
                    )
                    _vdb_to_table(
                        vdb,
                        conn,
                        sql,
                        params,
                        "topn_agreement",
                        f"agreement({ctype}) {view_a}×{view_b}",
                        mode="insert",
                    )
        else:
            logger.info("  topn_agreement skipped (--skip-topn)")

        # ---- topn_target_sets ----
        # The ranked target lists behind figure 10's Venn and its overlap boxes. See
        # target_sets.py for why topn_agreement cannot serve.
        _exec_static(conn, target_sets_schema_sql(), "topn_target_sets (schema)")

        if not args.skip_topn:
            for ctype, set_views in (
                ("binding", TARGET_SET_BINDING),
                ("perturbation", TARGET_SET_PERTURBATION),
            ):
                for view in set_views:
                    if view not in datasets:
                        continue
                    hf = DATASET_HF_COORDS.get(view, ("", ""))
                    if ctype == "binding":
                        cfg = BINDING_TOPN_CONFIGS[view]
                        sample_col = cfg["binding_sample_col"]
                        rank_col, rank_asc = agreement_rank_column(
                            view, cfg["rank_col"], cfg["rank_asc"]
                        )
                    else:
                        sample_col = "sample_id"
                        rank_col, rank_asc = agreement_rank_column(
                            view, PERTURBATION_DATASET_COLUMNS[view][0], False
                        )
                    _vdb_to_table(
                        vdb,
                        conn,
                        target_sets_select_sql(
                            view, hf[0], hf[1], sample_col, rank_col, rank_asc, ctype
                        ),
                        {},
                        "topn_target_sets",
                        f"target_sets({ctype}) {view}",
                        mode="insert",
                    )
        else:
            logger.info("  topn_target_sets skipped (--skip-topn)")

        # ---- correlations ----
        _exec_static(conn, correlations_schema_sql(), "correlations (schema)")

        if not args.skip_correlations:
            # Binding × binding pairs (lexicographic order, each pair once)
            binding_corr_views = [
                db for db in datasets if db in BINDING_DATASET_COLUMNS
            ]
            for view_a, view_b in itertools.combinations(sorted(binding_corr_views), 2):
                effect_a, pvalue_a = BINDING_DATASET_COLUMNS[view_a]
                effect_b, pvalue_b = BINDING_DATASET_COLUMNS[view_b]
                hf_a = DATASET_HF_COORDS.get(view_a, ("", ""))
                hf_b = DATASET_HF_COORDS.get(view_b, ("", ""))
                for method in methods:
                    sql, params = correlation_pair_select_sql(
                        view_a=view_a,
                        hf_repo_a=hf_a[0],
                        hf_config_a=hf_a[1],
                        effect_col_a=effect_a,
                        pvalue_col_a=pvalue_a,
                        view_b=view_b,
                        hf_repo_b=hf_b[0],
                        hf_config_b=hf_b[1],
                        effect_col_b=effect_b,
                        pvalue_col_b=pvalue_b,
                        method=method,
                        comparison_type="binding",
                        round_decimals=round_decimals,
                    )
                    _vdb_to_table(
                        vdb,
                        conn,
                        sql,
                        params,
                        "correlations",
                        f"corr(binding) {view_a}×{view_b} [{method}]",
                        mode="insert",
                    )

            # Perturbation × perturbation pairs
            pert_corr_views = [
                db for db in datasets if db in PERTURBATION_DATASET_COLUMNS
            ]
            for view_a, view_b in itertools.combinations(sorted(pert_corr_views), 2):
                effect_a, pvalue_a = PERTURBATION_DATASET_COLUMNS[view_a]
                effect_b, pvalue_b = PERTURBATION_DATASET_COLUMNS[view_b]
                hf_a = DATASET_HF_COORDS.get(view_a, ("", ""))
                hf_b = DATASET_HF_COORDS.get(view_b, ("", ""))
                for method in methods:
                    sql, params = correlation_pair_select_sql(
                        view_a=view_a,
                        hf_repo_a=hf_a[0],
                        hf_config_a=hf_a[1],
                        effect_col_a=effect_a,
                        pvalue_col_a=pvalue_a,
                        view_b=view_b,
                        hf_repo_b=hf_b[0],
                        hf_config_b=hf_b[1],
                        effect_col_b=effect_b,
                        pvalue_col_b=pvalue_b,
                        method=method,
                        comparison_type="perturbation",
                        round_decimals=round_decimals,
                    )
                    _vdb_to_table(
                        vdb,
                        conn,
                        sql,
                        params,
                        "correlations",
                        f"corr(perturbation) {view_a}×{view_b} [{method}]",
                        mode="insert",
                    )
        else:
            logger.info("  correlations skipped (--skip-correlations)")

        # ------------------------------------------------------------------
        # 5. Method x promoter-set model
        # ------------------------------------------------------------------
        logger.info("=== Phase 5: Method x promoter-set model ===")
        _exec_static(
            conn,
            method_promoter_model_schema_sql(),
            "method_promoter_model (schema)",
        )
        _exec_static(
            conn,
            method_promoter_model_topn_schema_sql(),
            "method_promoter_model_topn (schema)",
        )
        _exec_static(
            conn,
            method_promoter_model_target_universe_schema_sql(),
            "method_promoter_model_target_universe (schema)",
        )

        if not getattr(args, "skip_method_promoter_model", False):
            registry_df = conn.execute(
                "SELECT db_name, hf_repo, hf_config, primary_db_name,"
                " promoter_set_id, binding_method_id FROM dataset_registry"
            ).df()
            perturbation_dbs = sorted(
                db for db in datasets if db in PERTURBATION_TOPN_DATASETS
            )
            preset_names = getattr(args, "presets", None) or [
                "Relaxed",
                "Stringent",
            ]

            t_mpm_topn = time.monotonic()
            n_mpm_units = _method_promoter_topn_staged(
                vdb,
                conn,
                registry_df,
                perturbation_dbs,
                top_n_values,
                preset_names,
                chunk,
                round_decimals,
            )
            logger.info(
                "  method_promoter_model_topn: %d query units in %.1fs",
                n_mpm_units,
                time.monotonic() - t_mpm_topn,
            )

            coefs_all: list[pd.DataFrame] = []
            summary_all: list[pd.DataFrame] = []

            for perturbation_db in perturbation_dbs:
                for top_n in top_n_values:
                    for preset_name in preset_names:
                        preset = DEFAULT_RESPONSIVENESS_PRESETS.get(preset_name, {})
                        t0 = time.monotonic()
                        panel = build_method_promoter_panel(
                            conn, registry_df, perturbation_db, top_n, preset
                        )
                        coefs, summary = fit_method_promoter_model(panel)
                        stamps = {
                            "perturbation_db": perturbation_db,
                            "top_n": top_n,
                            "criteria": preset_name,
                        }
                        for frame in (coefs, summary):
                            for col, val in stamps.items():
                                frame[col] = val
                        coefs_all.append(coefs)
                        summary_all.append(summary)
                        logger.info(
                            "  method_promoter_model %-12s n=%-4d %-10s  %d rows"
                            "  %.2fs",
                            perturbation_db,
                            top_n,
                            preset_name,
                            len(panel),
                            time.monotonic() - t0,
                        )

            for table_name, frames, columns in (
                ("method_promoter_model_coefs", coefs_all, COEFS_COLUMNS),
                (
                    "method_promoter_model_fit_summary",
                    summary_all,
                    FIT_SUMMARY_COLUMNS,
                ),
            ):
                combined = (
                    pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
                )
                if combined.empty:
                    continue
                combined = combined[list(columns)]
                conn.register("_tmp_mpm", combined)
                try:
                    conn.execute(f'INSERT INTO "{table_name}" SELECT * FROM _tmp_mpm')
                finally:
                    conn.unregister("_tmp_mpm")
                logger.info("  %-40s  %d rows", table_name, len(combined))
        else:
            logger.info(
                "  method_promoter_model skipped (--skip-method-promoter-model)"
            )

        logger.info(
            "Materialization complete in %.1fs → %s",
            time.monotonic() - t_total,
            output_path,
        )

    finally:
        conn.close()
