import argparse
import os
import time

from shiny import run_app

from configure_logger import LogLevel, configure_logger, configure_profile_logger


def run_shiny(args: argparse.Namespace) -> None:
    log_level = LogLevel.from_string(args.log_level)
    log_file = args.log_file or f"tfbpshiny_{time.strftime('%Y%m%d-%H%M%S')}.log"

    # Configure loggers in this process and persist settings to env so that
    # Shiny's --reload subprocess picks them up when it re-imports app.py.
    configure_logger(
        "shiny",
        level=log_level.value,
        handler_type=args.log_handler,
        log_file=log_file,
    )
    configure_profile_logger(
        handler_type=args.profile_handler,
        log_file=args.profile_log_file,
        enabled=not args.no_profile,
    )

    os.environ["_TFBPSHINY_LOG_LEVEL"] = str(log_level.value)
    os.environ["_TFBPSHINY_LOG_HANDLER"] = args.log_handler
    os.environ["_TFBPSHINY_LOG_FILE"] = log_file
    os.environ["_TFBPSHINY_PROFILE_HANDLER"] = args.profile_handler
    os.environ["_TFBPSHINY_PROFILE_LOG_FILE"] = args.profile_log_file
    os.environ["_TFBPSHINY_PROFILE_ENABLED"] = "0" if args.no_profile else "1"

    import logging

    logging.getLogger("shiny").info(
        f"Logger destinations — shiny: handler={args.log_handler} "
        f"file={log_file if args.log_handler == 'file' else 'n/a'} | "
        f"profiler: handler={args.profile_handler} "
        f"file={args.profile_log_file if args.profile_handler == 'file' else 'n/a'}"
    )

    kwargs: dict[str, object] = {"port": args.port, "host": args.host}
    if args.debug:
        kwargs.update({"reload": True, "reload_dirs": ["tfbpshiny/shiny_app"]})
    run_app("tfbpshiny.app:app", **kwargs)  # type: ignore


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

    subparsers = parser.add_subparsers(dest="command", required=True)

    shiny_parser = subparsers.add_parser("shiny", help="Run the shiny app")
    shiny_parser.add_argument(
        "--port", type=int, default=8000, help="Port to serve the Shiny app on"
    )
    shiny_parser.add_argument(
        "--host", type=str, default="127.0.0.1", help="Host to bind the Shiny app"
    )
    shiny_parser.add_argument(
        "--debug", action="store_true", help="Enable debug mode with auto-reload"
    )
    shiny_parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level for the shiny logger",
    )
    shiny_parser.add_argument(
        "--log-handler",
        type=str,
        default="console",
        choices=["console", "file"],
        help="Destination for the shiny logger",
    )
    shiny_parser.add_argument(
        "--log-file",
        type=str,
        default="",
        help="Log file path when --log-handler=file "
        "(default: tfbpshiny_<timestamp>.log)",
    )
    shiny_parser.add_argument(
        "--profile-handler",
        type=str,
        default="console",
        choices=["console", "file"],
        help="Destination for the profiler logger",
    )
    shiny_parser.add_argument(
        "--profile-log-file",
        type=str,
        default="tfbpshiny_profile.log",
        help="Log file path when --profile-handler=file",
    )
    shiny_parser.add_argument(
        "--no-profile",
        action="store_true",
        help="Disable the profiler logger entirely",
    )
    shiny_parser.set_defaults(func=run_shiny)

    return parser


def main() -> None:
    parser = make_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
