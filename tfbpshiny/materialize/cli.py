"""
CLI handler for the ``tfbpshiny materialize`` subcommand.

Registers the subparser and implements ``run_materialize``, which loads
VirtualDB from the YAML config and calls :func:`~.coordinator.materialize`.

"""

from __future__ import annotations

import argparse
import logging
import os
import pathlib
import sys
from typing import Literal, cast

from tfbpshiny.configure_logger import LogLevel, configure_logger
from tfbpshiny.materialize.rounding import DEFAULT_FLOAT_DECIMALS


def run_materialize(args: argparse.Namespace) -> None:
    """
    Entry point for the ``tfbpshiny materialize`` subcommand.

    Downloads or opens the VirtualDB from the YAML config, then runs the full
    materialization pipeline, writing the output ``.duckdb`` file.

    :param args: Parsed CLI namespace from :func:`register_subparser`.

    """
    from labretriever import VirtualDB

    from tfbpshiny.materialize.coordinator import materialize

    log_level = LogLevel.from_string(args.log_level)
    configure_logger(
        "shiny",
        level=log_level.value,
        handler_type=cast(Literal["console", "file"], args.log_handler),
    )
    logger = logging.getLogger("shiny")

    hf_token: str | None = args.token or os.getenv("HF_TOKEN")

    output_path = pathlib.Path(args.output)
    if output_path.exists():
        try:
            answer = (
                input(f"\n'{output_path}' already exists. Overwrite? [y/N] ")
                .strip()
                .lower()
            )
        except EOFError:
            answer = ""
        if answer in ("y", "yes"):
            output_path.unlink()
            logger.info("Deleted existing file: %s", output_path)
        else:
            print(
                f"Aborted. Rename or move '{output_path}' out of the current "
                "directory and re-run to create a fresh database."
            )
            sys.exit(0)

    logger.info("Initializing VirtualDB from %s …", args.config)
    try:
        vdb = VirtualDB(args.config, token=hf_token, local_files_only=False)
    except Exception:
        logger.exception("Failed to initialize VirtualDB.")
        sys.exit(1)

    logger.info("Writing materialized database to %s …", args.output)
    try:
        materialize(args.output, vdb, args)
    except Exception:
        logger.exception("Materialization failed.")
        sys.exit(1)


def register_subparser(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
) -> None:
    """
    Register the ``materialize`` subcommand on the parent parser's subparsers.

    :param subparsers: The ``subparsers`` action from the parent
        ``argparse.ArgumentParser``.

    """
    p = subparsers.add_parser(
        "materialize",
        help=(
            "Materialize all dataset views into a persistent DuckDB file.  "
            "Run once offline; the resulting .duckdb file is used by the app."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--config",
        type=str,
        required=True,
        help="Path to the VirtualDB YAML configuration file.",
    )
    p.add_argument(
        "--output",
        type=str,
        default="brentlab_yeast.duckdb",
        help="Output path for the materialized .duckdb file.",
    )
    p.add_argument(
        "--methods",
        type=str,
        default="pearson,spearman",
        help="Comma-separated correlation methods to compute.",
    )
    p.add_argument(
        "--top-n",
        dest="top_n_values",
        type=int,
        action="append",
        default=None,
        metavar="N",
        help=(
            "Top-N cutoff for the top-N responsive-ratio analysis "
            "(repeatable; e.g. --top-n 25 --top-n 50)."
        ),
    )
    p.add_argument(
        "--preset",
        dest="presets",
        type=str,
        action="append",
        default=None,
        choices=["Relaxed", "Stringent"],
        help=(
            "Materialize the (effect, pvalue) pair each perturbation dataset uses "
            "under this responsiveness preset, so the app's preset selector can "
            "toggle between them. Stringent holds each dataset's published "
            "criteria. Repeatable; defaults to both Relaxed and Stringent. "
            "Thresholds resolve per dataset, so the two presets together "
            "need only 1-2 pairs per dataset rather than the 8 a global cross "
            "product of --effect-threshold x --pvalue-threshold would produce."
        ),
    )
    p.add_argument(
        "--effect-threshold",
        dest="effect_thresholds",
        type=float,
        action="append",
        default=None,
        metavar="THRESHOLD",
        help=(
            "Effect-size threshold for responsiveness "
            "(repeatable; e.g. --effect-threshold 0.0 --effect-threshold 1.0)."
        ),
    )
    p.add_argument(
        "--pvalue-threshold",
        dest="pvalue_thresholds",
        type=float,
        action="append",
        default=None,
        metavar="THRESHOLD",
        help=(
            "Adjusted p-value threshold for responsiveness "
            "(repeatable; e.g. --pvalue-threshold 0.05 --pvalue-threshold 0.1)."
        ),
    )
    p.add_argument(
        "--float-decimals",
        dest="float_decimals",
        type=int,
        default=DEFAULT_FLOAT_DECIMALS,
        metavar="N",
        help=(
            "Decimal places kept for computed floating-point columns "
            "(correlations.correlation, topn_results.responsive_ratio). DuckDB's "
            "parallel aggregation sums in a nondeterministic order, so two builds of "
            "the same data can differ in the last bits; rounding removes that so "
            "builds can be diffed. Pass -1 to store raw values. Default: "
            f"{DEFAULT_FLOAT_DECIMALS} (~1e-9), three to four orders above the "
            "observed ~1e-13 noise. Values read from the source parquet, such as the "
            "DTO p-values, are never rounded."
        ),
    )
    p.add_argument(
        "--legacy-topn",
        action="store_true",
        default=False,
        help=(
            "Compute topn_results one (top_n, effect, pvalue) variant at a time, as "
            "builds did before the scan was hoisted out of the variant loop. Far "
            "slower; kept only so a build from this commit can be diffed against the "
            "staged one to prove they agree."
        ),
    )
    p.add_argument(
        "--skip-correlations",
        action="store_true",
        default=False,
        help="Skip the pairwise correlation computation.",
    )
    p.add_argument(
        "--skip-topn",
        action="store_true",
        default=False,
        help="Skip the top-N responsive-ratio computation.",
    )
    p.add_argument(
        "--skip-method-promoter-model",
        action="store_true",
        default=False,
        help=(
            "Skip the method x promoter-set pooled OLS model (peak calling vs. "
            "promoter enrichment, crossed with promoter definition), over Rossi and "
            "ChEC-seq. Also skips this model's own top-N staging fill, which ranks "
            "each of its 16 cells over the cross-promoter-set target intersection "
            "(a VirtualDB hop of its own, separate from --skip-topn)."
        ),
    )
    p.add_argument(
        "--token",
        type=str,
        default=None,
        help="HuggingFace token for private repos (falls back to HF_TOKEN env var).",
    )
    p.set_defaults(func=_run_with_defaults)


def _run_with_defaults(args: argparse.Namespace) -> None:
    """Apply list-argument defaults then delegate to :func:`run_materialize`."""
    from tfbpshiny.materialize.comparison.topn import TOP_N_CHOICES

    if args.top_n_values is None:
        args.top_n_values = list(TOP_N_CHOICES)
    if args.effect_thresholds is None:
        args.effect_thresholds = [0.0]
    if args.pvalue_thresholds is None:
        args.pvalue_thresholds = [0.05]
    if args.presets is None:
        # Both by default: the Comparison page offers a Relaxed/Stringent toggle, and
        # a preset that was never materialized silently returns no rows.
        args.presets = ["Relaxed", "Stringent"]
    run_materialize(args)
