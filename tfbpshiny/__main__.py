from __future__ import annotations

import argparse
import os
import sys

from shiny import run_app

from tfbpshiny.configure_logger import LogLevel, configure_logger

_DEFAULT_VIRTUALDB_CONFIG = str(
    __import__("pathlib").Path(__file__).parent / "brentlab_yeast_collection.yaml"
)


def _apply_cache_dir(args: argparse.Namespace) -> None:
    """
    Set ``HF_CACHE_DIR`` from ``--cache-dir`` before any HF imports resolve it.

    Must be called before importing labretriever or huggingface_hub so that
    ``snapshot_download`` and ``VirtualDB`` see the overridden path.

    """
    if args.cache_dir is not None:
        import pathlib

        os.environ["HF_CACHE_DIR"] = str(pathlib.Path(args.cache_dir).resolve())


def run_shiny(args: argparse.Namespace) -> None:
    _apply_cache_dir(args)
    log_level = LogLevel.from_string(args.log_level)

    # Env vars are the only reliable way to pass config to uvicorn reload workers,
    # which re-import app.py in a subprocess and cannot see in-process mutations.
    # The CLI is the sole writer of these vars; app.py reads them.
    os.environ["TFBPSHINY_LOG_LEVEL"] = str(log_level.value)
    os.environ["TFBPSHINY_LOG_HANDLER"] = args.log_handler
    os.environ["VIRTUALDB_CONFIG"] = args.virtualdb_config

    kwargs: dict[str, object] = {"port": args.port, "host": args.host}
    if args.debug:
        kwargs.update({"reload": True, "reload_dirs": ["tfbpshiny/shiny_app"]})
    run_app("tfbpshiny.app:app", **kwargs)  # type: ignore


def run_initialize(args: argparse.Namespace) -> None:
    """Download all dataset files into the local HuggingFace cache."""
    import logging

    _apply_cache_dir(args)

    from tfbpshiny.utils.vdb_init import initialize_data

    log_level = LogLevel.from_string(args.log_level)
    configure_logger("shiny", level=log_level.value, handler_type="console")
    logger = logging.getLogger("shiny")

    cache_msg = os.environ.get("HF_CACHE_DIR", "(huggingface default)")
    hf_token: str | None = os.getenv("HF_TOKEN")
    logger.info("Downloading all datasets into HuggingFace cache: %s", cache_msg)
    try:
        vdb, _ = initialize_data(
            args.virtualdb_config, hf_token, local_files_only=False
        )
    except Exception:
        logger.exception("Cache initialization failed.")
        sys.exit(1)

    # Force each registered view to materialize by scanning all rows. This
    # ensures the parquet files are fully downloaded and readable before we
    # declare success — snapshot_download only fetches metadata otherwise.
    # Query the actual registered views from DuckDB rather than get_datasets(),
    # which returns config names that may differ from the final view names.
    logger.info("Verifying all dataset views are readable...")
    views_df = vdb.query(
        "SELECT view_name FROM duckdb_views()"
        " WHERE schema_name = 'main'"
        "   AND view_name NOT LIKE 'duckdb_%'"
        "   AND view_name NOT LIKE 'sqlite_%'"
        "   AND view_name NOT LIKE 'pragma_%'"
        " ORDER BY view_name"
    )
    view_names = views_df["view_name"].tolist()
    failed: list[str] = []
    for view_name in view_names:
        try:
            df = vdb.query(f'SELECT * FROM "{view_name}" LIMIT 1')
            logger.info("  OK  %-30s  (%d col(s))", view_name, len(df.columns))
        except Exception:
            logger.exception("  FAIL %s", view_name)
            failed.append(view_name)

    if failed:
        logger.error("Verification failed for: %s", ", ".join(failed))
        sys.exit(1)

    logger.info("Cache initialization complete.")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tfbpshiny",
        description=(
            "tfbpshiny is a CLI with multiple utilities "
            "(e.g., shiny). Use --help after any command."
        ),
        epilog="Use 'tfbpshiny <utility> --help' for more info on each utility.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set logging level.",
    )
    parser.add_argument(
        "--log-handler",
        type=str,
        default="console",
        choices=["console", "file"],
        help="Set log handler type.",
    )
    parser.add_argument(
        "--virtualdb-config",
        type=str,
        default=_DEFAULT_VIRTUALDB_CONFIG,
        help="Path to the VirtualDB YAML configuration file.",
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default=None,
        help=(
            "Override the HuggingFace cache directory. "
            "When set, HF_CACHE_DIR is written to this path before any "
            "huggingface_hub calls, so both 'initialize' and 'shiny' read/write "
            "parquet snapshots from the specified location. "
            "Useful for bundling a pre-downloaded cache with the application "
            "(e.g. shinyapps.io deployment)."
        ),
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    shiny_parser = subparsers.add_parser("shiny", help="Run the shiny app.")
    shiny_parser.add_argument(
        "--debug", action="store_true", help="Enable debug mode with auto-reload."
    )
    shiny_parser.add_argument(
        "--port", type=int, default=8000, help="Port to serve the Shiny app on."
    )
    shiny_parser.add_argument(
        "--host", type=str, default="127.0.0.1", help="Host to bind the Shiny app."
    )
    shiny_parser.set_defaults(func=run_shiny)

    init_parser = subparsers.add_parser(
        "initialize",
        help=(
            "Download all dataset files into the local HuggingFace cache. "
            "Must be run before 'shiny' on a fresh instance."
        ),
    )
    init_parser.set_defaults(func=run_initialize)

    return parser


def main() -> None:
    parser = make_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
