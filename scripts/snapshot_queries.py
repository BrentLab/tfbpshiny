"""
Snapshot the output of every read-side query function under the app's default inputs.

This is the regression oracle for refactoring: run it before a change and after, then
``diff -r`` the two output directories. Every DataFrame is sorted by all of its columns
before writing, so physical row order never shows up as a difference. A ``manifest.json``
holds row counts and sha256 digests for a quick first look.

Usage::

    poetry run python scripts/snapshot_queries.py brentlab_yeast.duckdb /tmp/baseline/queries
    poetry run python scripts/snapshot_queries.py brentlab_yeast.duckdb /tmp/after/queries
    diff -r /tmp/baseline/queries /tmp/after/queries

Adding a query is one entry in :data:`SNAPSHOTS`: ``(name, callable(ctx) -> frame_or_object)``.

"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import itertools
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from tfbpshiny.datasets import PRESET_NAMES, TOP_N_CHOICES
from tfbpshiny.modules.comparison import queries as cq
from tfbpshiny.modules.figures import queries as fq
from tfbpshiny.utils.corr_query import expand_filters_to_variants, fetch_corr_pairs
from tfbpshiny.utils.vdb_init import (
    DEFAULT_DATASET_FILTERS,
    DEFAULT_RESPONSIVENESS_PRESETS,
    get_regulator_display_name,
    load_app_datasets,
)

PRESETS = PRESET_NAMES
TOP_NS = TOP_N_CHOICES
FEATURED_TF = "YJL110C"  # the Figures tab's default featured TF (GZF3)


@dataclasses.dataclass
class Ctx:
    """Everything the snapshot callables need, computed once."""

    conn: duckdb.DuckDBPyConnection
    filters: dict[str, Any]
    registry: pd.DataFrame
    active_binding: list[str]
    active_perturbation: list[str]
    tf_sets: dict[str, list[str]]
    fig7_tf_sets: dict[str, list[str]]
    fig9_tf_sets: dict[str, list[str]]


def _ctx(db_path: str) -> Ctx:
    conn = duckdb.connect(db_path, read_only=True)
    registry = conn.execute("SELECT * FROM dataset_registry").df()
    active = conn.execute(
        "SELECT data_type, db_name FROM dataset_registry WHERE is_active_default"
        " ORDER BY db_name"
    ).df()
    return Ctx(
        conn=conn,
        filters=expand_filters_to_variants(conn, DEFAULT_DATASET_FILTERS),
        registry=registry,
        active_binding=active[active.data_type == "binding"].db_name.tolist(),
        active_perturbation=active[active.data_type == "perturbation"].db_name.tolist(),
        tf_sets={
            p: fq.regulator_intersection(conn, list(fq.BINDING_ORDER) + [p])
            for p in fq.PR_ORDER
        },
        fig7_tf_sets={
            p: fq.regulator_intersection(conn, list(fq.DTO_BINDING_ORDER) + [p])
            for p in fq.PR_ORDER
        },
        fig9_tf_sets={
            p: fq.regulator_intersection(conn, list(fq.METHOD_COMPARISON_BINDING) + [p])
            for p in fq.PR_ORDER
        },
    )


# ---------------------------------------------------------------------------
# The query grid. Each entry: (name, callable(ctx) -> DataFrame | JSON-able object)
# ---------------------------------------------------------------------------

SNAPSHOTS: list[tuple[str, Callable[[Ctx], Any]]] = []


def snap(name: str) -> Callable[[Callable[[Ctx], Any]], Callable[[Ctx], Any]]:
    def register(fn: Callable[[Ctx], Any]) -> Callable[[Ctx], Any]:
        SNAPSHOTS.append((name, fn))
        return fn

    return register


# --- shared / registry ------------------------------------------------------------


@snap("registry__dataset_labels")
def _labels(c: Ctx) -> Any:
    return fq.dataset_labels(c.conn)


@snap("registry__app_datasets")
def _app_datasets(c: Ctx) -> Any:
    return dataclasses.asdict(load_app_datasets(c.conn))


@snap("registry__regulator_display_names")
def _reg_names(c: Ctx) -> Any:
    return get_regulator_display_name(c.conn)


@snap("registry__binding_index_cells")
def _binding_index(c: Ctx) -> Any:
    idx = cq.build_binding_index(c.registry)
    cells = {}
    for primary in sorted(set(idx.primary.values())):
        for ps in fq.PROMOTER_SET_LEVELS:
            for m in fq.METHOD_LEVELS:
                cells[f"{primary}|{ps}|{m}"] = idx.resolve(primary, ps, m)
    return cells


@snap("figures__tf_sets")
def _tf_sets(c: Ctx) -> Any:
    return {
        "tf_sets": c.tf_sets,
        "fig7": c.fig7_tf_sets,
        "fig9": c.fig9_tf_sets,
        "featured": fq.regulator_intersection(
            c.conn, list(fq.BINDING_ORDER) + list(fq.PR_ORDER)
        ),
    }


@snap("figures__featured_sorted")
def _featured_sorted(c: Ctx) -> Any:
    featured = fq.regulator_intersection(
        c.conn, list(fq.BINDING_ORDER) + list(fq.PR_ORDER)
    )
    names = get_regulator_display_name(c.conn)
    symbols = {
        str(r.regulator_locus_tag): str(r.regulator_symbol)
        for r in names.itertuples()
        if str(r.regulator_symbol) not in ("nan", "", str(r.regulator_locus_tag))
    }
    return fq.sort_regulators_by_symbol(featured, symbols)


# --- figures 1-3 --------------------------------------------------------------------


def _figures_1_to_3() -> None:
    for p in fq.PR_ORDER:
        for preset in PRESETS:

            @snap(f"fig1__rank_response__{p}__{preset}")
            def _f1(c: Ctx, p: str = p, preset: str = preset) -> Any:
                return fq.fetch_rank_response(
                    c.conn, list(fq.BINDING_ORDER), p, c.tf_sets[p], c.filters, preset
                )

            @snap(f"fig3__authors_bound__{p}__{preset}")
            def _f3(c: Ctx, p: str = p, preset: str = preset) -> Any:
                return fq.fetch_authors_bound(
                    c.conn, list(fq.AUTHORS_PEAK_BINDING), p, c.filters, preset
                )

            for n in TOP_NS:

                @snap(f"fig2__topn_percent__{p}__{preset}__top{n}")
                def _f2(c: Ctx, p: str = p, preset: str = preset, n: int = n) -> Any:
                    return fq.fetch_topn_percent_responsive(
                        c.conn,
                        list(fq.BINDING_ORDER),
                        p,
                        c.tf_sets[p],
                        n,
                        c.filters,
                        preset,
                    )


_figures_1_to_3()


# --- figures 4-5 (DTO) --------------------------------------------------------------


@snap("fig4__dto_significance")
def _f4(c: Ctx) -> Any:
    return fq.fetch_dto_significance(
        c.conn, list(fq.DTO_BINDING_ORDER), list(fq.PR_ORDER)
    )


def _figure_5() -> None:
    for p in fq.PR_ORDER:

        @snap(f"fig5__dto_significant_sets__{p}")
        def _f5(c: Ctx, p: str = p) -> Any:
            sets = fq.fetch_dto_significant_sets(c.conn, list(fq.DTO_BINDING_ORDER), p)
            return {k: sorted(v) for k, v in sets.items()}


_figure_5()


# --- figure 6 and 10 ----------------------------------------------------------------


def _figures_6_and_10() -> None:
    defaults = {
        "binding": list(fq.AGREEMENT_DEFAULT_BINDING),
        "perturbation": list(fq.AGREEMENT_DEFAULT_PERTURBATION),
    }
    for ctype, dbs in defaults.items():

        @snap(f"fig6__agreement_choices__{ctype}")
        def _choices(c: Ctx, ctype: str = ctype) -> Any:
            return fq.agreement_dataset_choices(c.conn, ctype)

        @snap(f"fig6__agreement__{ctype}")
        def _f6(c: Ctx, ctype: str = ctype, dbs: list[str] = dbs) -> Any:
            return fq.fetch_agreement(c.conn, ctype, dbs, c.filters)

        for n in TOP_NS:

            @snap(f"fig10__shared_targets__{ctype}__top{n}")
            def _f10a(
                c: Ctx, ctype: str = ctype, dbs: list[str] = dbs, n: int = n
            ) -> Any:
                return fq.fetch_shared_targets(c.conn, ctype, dbs, n, c.filters)

            @snap(f"fig10__target_sets__{ctype}__top{n}")
            def _f10b(c: Ctx, dbs: list[str] = dbs, n: int = n) -> Any:
                sets = fq.fetch_target_sets(c.conn, dbs, FEATURED_TF, n, c.filters)
                return {k: sorted(v) for k, v in sets.items()}


_figures_6_and_10()


# --- figures 7-9 (promoter-set / method grids) ---------------------------------------


def _variant_cells(
    c: Ctx, primaries: tuple[str, ...], combos: list[tuple[str, str]]
) -> dict:
    out = {}
    for b in primaries:
        for ps, m in combos:
            v = fq.resolve_promoter_variant(c.conn, b, ps, m)
            if v:
                out[v] = (b, ps, m)
    return out


PS_COMBOS = [(ps, "promoter_enrichment") for ps in fq.PROMOTER_SET_LEVELS]
METHOD_COMBOS = [("500bp", m) for m in fq.METHOD_LEVELS]


@snap("fig789__variant_cells")
def _cells(c: Ctx) -> Any:
    return {
        "fig7_8": _variant_cells(c, fq.DTO_BINDING_ORDER, PS_COMBOS),
        "fig9": _variant_cells(c, fq.METHOD_COMPARISON_BINDING, METHOD_COMBOS),
    }


def _figures_7_to_9() -> None:
    for p in fq.PR_ORDER:
        for preset in PRESETS:
            for n in TOP_NS:

                @snap(f"fig7__topn_percent_variants__{p}__{preset}__top{n}")
                def _f7(c: Ctx, p: str = p, preset: str = preset, n: int = n) -> Any:
                    variants = list(_variant_cells(c, fq.DTO_BINDING_ORDER, PS_COMBOS))
                    return fq.fetch_topn_percent_responsive(
                        c.conn, variants, p, c.fig7_tf_sets[p], n, c.filters, preset
                    )

                @snap(f"fig9__topn_percent_methods__{p}__{preset}__top{n}")
                def _f9(c: Ctx, p: str = p, preset: str = preset, n: int = n) -> Any:
                    variants = list(
                        _variant_cells(c, fq.METHOD_COMPARISON_BINDING, METHOD_COMBOS)
                    )
                    return fq.fetch_topn_percent_responsive(
                        c.conn, variants, p, c.fig9_tf_sets[p], n, c.filters, preset
                    )

        @snap(f"fig9__dto_for_universe__{p}")
        def _f9dto(c: Ctx, p: str = p) -> Any:
            rows = []
            cells = _variant_cells(c, fq.METHOD_COMPARISON_BINDING, METHOD_COMBOS)
            by_primary: dict[str, dict[str, str]] = {}
            for v, (b, _ps, m) in cells.items():
                by_primary.setdefault(b, {})[m] = v
            for b, methods in sorted(by_primary.items()):
                pe, pc = methods.get("promoter_enrichment"), methods.get("peak_calling")
                if not pe or not pc:
                    continue
                universe = set(fq.regulator_intersection(c.conn, [pe, pc, p]))
                for m, v in (("promoter_enrichment", pe), ("peak_calling", pc)):
                    stats = fq.fetch_dto_significance_for_universe(
                        c.conn, v, p, universe
                    )
                    rows.append(
                        {
                            "binding_primary": b,
                            "method": m,
                            "n_shared": len(universe),
                            **stats,
                        }
                    )
            return pd.DataFrame(rows)


_figures_7_to_9()


# --- comparison tab -----------------------------------------------------------------


def _comparison() -> None:
    @snap("comparison__dto_results")
    def _cd_dto(c: Ctx) -> Any:
        pairs = [(b, p) for b in c.active_binding for p in c.active_perturbation]
        return cq.fetch_dto_results(c.conn, pairs, c.filters)

    @snap("comparison__dto_results_method_intersected")
    def _cm_dto(c: Ctx) -> Any:
        idx = cq.build_binding_index(c.registry)
        cells: list[tuple[str, str, str]] = []
        for b in c.active_binding:
            primary = idx.primary.get(b, b)
            ps = idx.promoter_set_id.get(b, "")
            pe = idx.resolve(primary, ps, "promoter_enrichment")
            pc = idx.resolve(primary, ps, "peak_calling")
            if pe and pc:
                cells.extend((pe, pc, p) for p in c.active_perturbation)
        return cq.fetch_dto_results_method_intersected(c.conn, cells, c.filters)

    @snap("comparison__method_promoter_target_universe")
    def _mm_universe(c: Ctx) -> Any:
        return cq.fetch_method_promoter_target_universe(c.conn)

    for preset in PRESETS:
        for n in TOP_NS:
            for floor in (True, False):

                @snap(f"comparison__topn_results__{preset}__top{n}__floor{int(floor)}")
                def _cd_topn(
                    c: Ctx, preset: str = preset, n: int = n, floor: bool = floor
                ) -> Any:
                    pairs = [
                        (b, p) for b in c.active_binding for p in c.active_perturbation
                    ]
                    return cq.fetch_topn_results(
                        c.conn,
                        pairs,
                        c.filters,
                        n,
                        DEFAULT_RESPONSIVENESS_PRESETS[preset],
                        require_full_overlap=floor,
                    )

            for p in fq.PR_ORDER:

                @snap(f"comparison__method_promoter_model__{p}__{preset}__top{n}")
                def _mm(c: Ctx, p: str = p, preset: str = preset, n: int = n) -> Any:
                    return cq.fetch_method_promoter_model(c.conn, p, n, preset)


_comparison()


# --- binding / perturbation correlation tabs -----------------------------------------


@snap("binding__corr_pairs__spearman__log10pval")
def _binding_corr(c: Ctx) -> Any:
    pairs = list(itertools.combinations(sorted(c.active_binding), 2))
    out = fetch_corr_pairs(
        c.conn, pairs, c.filters, "spearman", "log10pval", comparison_type="binding"
    )
    return (
        {f"{a}__{b}": df for (a, b), df in out.items()}
        if isinstance(out, dict)
        else out
    )


@snap("perturbation__corr_pairs__pearson__effect")
def _pert_corr(c: Ctx) -> Any:
    pairs = list(itertools.combinations(sorted(c.active_perturbation), 2))
    out = fetch_corr_pairs(
        c.conn, pairs, c.filters, "pearson", "effect", comparison_type="perturbation"
    )
    return (
        {f"{a}__{b}": df for (a, b), df in out.items()}
        if isinstance(out, dict)
        else out
    )


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _canonical_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    cols = list(df.columns)
    return df.sort_values(cols, kind="mergesort").reset_index(drop=True)


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    if isinstance(obj, dict):
        return {
            str(k): _jsonable(v)
            for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if hasattr(obj, "item"):  # numpy scalar
        return obj.item()
    return obj


def write_one(out_dir: Path, name: str, value: Any) -> dict:
    """Write one snapshot; return its manifest entry."""
    if (
        isinstance(value, dict)
        and value
        and all(isinstance(v, pd.DataFrame) for v in value.values())
    ):
        # A dict of frames (correlation pairs): one CSV per key, manifest over all.
        entries = {k: write_one(out_dir, f"{name}__{k}", v) for k, v in value.items()}
        return {"kind": "frames", "parts": entries}
    if isinstance(value, pd.DataFrame):
        df = _canonical_frame(value)
        path = out_dir / f"{name}.csv"
        df.to_csv(path, index=False, float_format="%.10g")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return {"kind": "frame", "rows": int(len(df)), "sha256": digest}
    text = json.dumps(_jsonable(value), indent=1, sort_keys=True, default=str)
    path = out_dir / f"{name}.json"
    path.write_text(text + "\n")
    return {"kind": "json", "sha256": hashlib.sha256(text.encode()).hexdigest()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("db_path")
    parser.add_argument("out_dir")
    parser.add_argument(
        "--only", default=None, help="Substring filter on snapshot names."
    )
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx = _ctx(args.db_path)
    manifest: dict[str, Any] = {}
    failures = 0
    for name, fn in SNAPSHOTS:
        if args.only and args.only not in name:
            continue
        try:
            manifest[name] = write_one(out_dir, name, fn(ctx))
        except Exception as exc:  # a failing query is itself a finding; keep going
            failures += 1
            manifest[name] = {"kind": "error", "error": f"{type(exc).__name__}: {exc}"}
            print(f"FAILED {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=1, sort_keys=True) + "\n"
    )
    print(f"{len(manifest)} snapshots written to {out_dir} ({failures} failed)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
