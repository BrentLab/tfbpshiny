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
from labretriever import VirtualDB

from tfbpshiny.materialize.comparison.agreement import (
    AGREEMENT_EXCLUDED,
    agreement_pair_select_sql,
    agreement_schema_sql,
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
from tfbpshiny.materialize.comparison.topn import (
    BINDING_TOPN_CONFIGS,
    PEAK_BINDING_DATASETS,
    PERTURBATION_TOPN_DATASETS,
    TOP_N_ALL,
    topn_pair_select_sql,
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


def _topn_variants(
    binding_db: str,
    perturbation_db: str,
    top_n_values: list[int],
    effect_thresholds: list[float],
    pvalue_thresholds: list[float],
    preset_names: list[str] | None = None,
) -> list[tuple[int, float, float]]:
    """
    Enumerate the (top_n, effect, pvalue) variants to materialize for a pair.

    Two things are layered on top of the plain cross product:

    * **Preset thresholds.** Each named preset contributes the *own* ``(effect,
      pvalue)`` pair of this perturbation dataset, rather than cross-producting global
      lists. Relaxed and Stringent together need only 1-2 pairs per dataset, where the
      cross product of their four distinct pairs would materialize eight. Both presets
      are materialized by default so the app's selector can toggle between them --
      a preset with no rows silently shows nothing.
    * **Whole-bound-set rows.** Peak datasets additionally get ``TOP_N_ALL``, where the
      authors' peak call is the threshold and no rank cutoff applies.

    :param binding_db: Binding dataset name.
    :param perturbation_db: Perturbation dataset name.
    :param top_n_values: Rank cutoffs from the CLI.
    :param effect_thresholds: Effect cutoffs from the CLI.
    :param pvalue_thresholds: P-value cutoffs from the CLI.
    :param preset_names: Responsiveness presets whose thresholds to include.
    :returns: Distinct variants, in a stable order.

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

    variants: list[tuple[int, float, float]] = []
    for top_n in cutoffs:
        for eff, pval in threshold_pairs:
            variants.append((top_n, eff, pval))
    return variants


def _regulators_for_binding(vdb: VirtualDB, binding_view: str) -> list[str]:
    """Return distinct regulator locus tags for a binding dataset (sorted)."""
    df = vdb.query(f"SELECT DISTINCT regulator_locus_tag FROM {binding_view}_meta")
    return sorted(t for t in df["regulator_locus_tag"].dropna().tolist())


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

        # ---- topn_results ----
        _exec_static(conn, topn_schema_sql(), "topn_results (schema)")

        if not args.skip_topn:
            binding_views = [db for db in datasets if db in BINDING_TOPN_CONFIGS]
            perturbation_views = [
                db for db in datasets if db in PERTURBATION_TOPN_DATASETS
            ]

            for b_db, p_db in itertools.product(binding_views, perturbation_views):
                b_cfg = BINDING_TOPN_CONFIGS[b_db]
                b_hf_repo, b_hf_config = DATASET_HF_COORDS.get(b_db, ("", ""))
                p_hf_repo, p_hf_config = DATASET_HF_COORDS.get(p_db, ("", ""))

                regulators = _regulators_for_binding(vdb, b_db)
                batches: list[tuple[str, ...]] = [
                    tuple(regulators[i : i + chunk])
                    for i in range(0, len(regulators), chunk)
                ] or [()]

                for top_n, eff_thresh, pval_thresh in _topn_variants(
                    b_db,
                    p_db,
                    top_n_values,
                    effect_thresholds,
                    pvalue_thresholds,
                    preset_names=getattr(args, "presets", None),
                ):
                    pair_label = (
                        f"topn {b_db}×{p_db} n={top_n} " f"({eff_thresh},{pval_thresh})"
                    )
                    pair_rows = 0
                    for batch_idx, batch in enumerate(batches):
                        sql, params = topn_pair_select_sql(
                            binding_view=b_db,
                            binding_hf_repo=b_hf_repo,
                            binding_hf_config=b_hf_config,
                            perturbation_view=p_db,
                            pert_hf_repo=p_hf_repo,
                            pert_hf_config=p_hf_config,
                            binding_sample_col=b_cfg["binding_sample_col"],
                            rank_col=b_cfg["rank_col"],
                            rank_asc=b_cfg["rank_asc"],
                            target_blacklist=b_cfg.get("target_blacklist", ()),
                            binding_dedup_cte=b_cfg.get("binding_dedup_cte", ""),
                            top_n=top_n,
                            effect_threshold=eff_thresh,
                            pvalue_threshold=pval_thresh,
                            regulator_subset=batch,
                            param_prefix=f"bp{batch_idx}",
                        )
                        batch_label = (
                            f"{pair_label} batch {batch_idx + 1}/{len(batches)}"
                        )
                        pair_rows += _vdb_to_table(
                            vdb,
                            conn,
                            sql,
                            params,
                            "topn_results",
                            batch_label,
                            mode="insert",
                        )
                    logger.info("  %-40s  total %d rows", pair_label, pair_rows)
        else:
            logger.info("  topn_results skipped (--skip-topn)")

        # ---- topn_agreement ----
        # Same-datatype top-N set overlap, for the "agreement between datasets"
        # figure. Every dataset pair is materialized, not just the primaries: the
        # figure's dataset selector lets a reader compare promoter sets and calling
        # methods as well as assays, and which slice is interesting is a read-time
        # question. Only AGREEMENT_EXCLUDED is held back -- see its docstring.
        _exec_static(conn, agreement_schema_sql(), "topn_agreement (schema)")

        if not args.skip_topn:
            for ctype, cfg_map in (
                ("binding", BINDING_TOPN_CONFIGS),
                ("perturbation", None),
            ):
                if ctype == "binding":
                    views = sorted(
                        db
                        for db in datasets
                        if db in cfg_map and db not in AGREEMENT_EXCLUDED
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
                        cfg_a, cfg_b = cfg_map[view_a], cfg_map[view_b]
                        col_a, col_b = (
                            cfg_a["binding_sample_col"],
                            cfg_b["binding_sample_col"],
                        )
                        rank_a, asc_a = cfg_a["rank_col"], cfg_a["rank_asc"]
                        rank_b, asc_b = cfg_b["rank_col"], cfg_b["rank_asc"]
                    else:
                        col_a = col_b = "sample_id"
                        rank_a = PERTURBATION_DATASET_COLUMNS[view_a][0]
                        rank_b = PERTURBATION_DATASET_COLUMNS[view_b][0]
                        # Ranked by |effect|, so larger is always "more responsive".
                        asc_a = asc_b = False
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

        logger.info(
            "Materialization complete in %.1fs → %s",
            time.monotonic() - t_total,
            output_path,
        )

    finally:
        conn.close()
