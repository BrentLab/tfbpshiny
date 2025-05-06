import logging
from enum import Enum
from typing import Literal


class LogLevel(Enum):
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL

    @classmethod
    def from_string(cls, level_str: str) -> int:
        """
        Convert a string representation of a log level to a LogLevel enum.

        :param level_str: The string representation of the log level.
        :return: The corresponding LogLevel enum.
        :raises ValueError: If the log level string is not recognized.

        """
        try:
            return getattr(cls, level_str.upper()).value
        except AttributeError:
            raise ValueError(
                f"Invalid log level: {level_str}. "
                f"Choose from {', '.join(cls._member_names_)}."
            )


def configure_logger(
    name: str,
    level: int = logging.DEBUG,  # Use int type hint here
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handler_type: Literal["console", "file"] = "console",
    log_file: str = "tfbpmodeling.log",
) -> logging.Logger:
    """
    Configures a logger.

    :param name: Name of the logger
    :type name: str
    :param level: Logging level, must be one of logging.DEBUG,
        logging.INFO, logging.WARNING, logging.ERROR
    :type level: int
    :param format: Logging format
    :type format: str
    :param handler_type: Type of handler, either 'console' or 'file'
    :type handler_type: Literal["console", "file"]
    :param log_file: Path to log file, required if handler_type is 'file'.
        Default is 'tfbpmodeling.log'
    :type log_file: str

    :return: Configured logger
    :rtype: logging.Logger

    :raises ValueError: If any of the parameters have invalid datatypes

    example usage:
    >>> logger = configure_logger("my_logger", level=logging.INFO)

    """
    if not isinstance(name, str):
        raise ValueError("name must be a string")
    if not isinstance(level, int):
        raise ValueError("level must be an integer")
    if level not in [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR]:
        raise ValueError("Invalid logging level")
    if not isinstance(format, str):
        raise ValueError("format must be a string")
    if handler_type not in ["console", "file"]:
        raise ValueError("handler_type must be 'console' or 'file'")
    if handler_type == "file" and not log_file:
        raise ValueError("log_file must be specified for file handler")

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Remove all handlers associated with the logger object to avoid duplicate logs
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    if handler_type == "console":
        handler = logging.StreamHandler()
    elif handler_type == "file":
        if not log_file:
            raise ValueError("log_file must be specified for file handler")
        handler = logging.FileHandler(log_file)
    else:
        raise ValueError("Invalid handler_type. Must be 'console' or 'file'.")

    handler.setLevel(level)
    formatter = logging.Formatter(format)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger
