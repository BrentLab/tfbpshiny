from __future__ import annotations

import argparse
import os
import sys

from shiny import run_app

from configure_logger import LogLevel, configure_logger

_DEFAULT_VIRTUALDB_CONFIG = str(
    __import__("pathlib").Path(__file__).parent / "brentlab_yeast_collection.yaml"
)


def run_shiny(args: argparse.Namespace) -> None:
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

    from tfbpshiny.utils.vdb_init import initialize_data

    log_level = LogLevel.from_string(args.log_level)
    configure_logger("shiny", level=log_level.value, handler_type="console")
    logger = logging.getLogger("shiny")

    hf_token: str | None = os.getenv("HF_TOKEN")
    logger.info("Downloading all datasets into local HuggingFace cache.")
    try:
        initialize_data(args.virtualdb_config, hf_token)
        logger.info("Cache initialization complete.")
    except Exception:
        logger.exception("Cache initialization failed.")
        sys.exit(1)


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
