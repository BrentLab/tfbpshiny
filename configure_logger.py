import json
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
    def from_string(cls, level_str: str) -> Enum:
        """
        Convert a string representation of a log level to a LogLevel enum.

        :param level_str: The string representation of the log level.
        :return: The corresponding LogLevel enum.
        :raises ValueError: If the log level string is not recognized.

        """
        try:
            return getattr(cls, level_str.upper())
        except AttributeError:
            raise ValueError(
                f"Invalid log level: {level_str}. "
                f"Choose from {', '.join(cls._member_names_)}."
            )


class _JsonFormatter(logging.Formatter):
    """
    Emit each log record as a single-line JSON object for CloudWatch Logs Insights.

    When the message body is itself a JSON object (e.g. perf records), its fields
    are merged into the top-level envelope rather than nested under ``"message"``,
    so that Logs Insights can filter on ``elapsed_ms``, ``module``, etc. directly.

    """

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        obj: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
        }
        try:
            parsed = json.loads(msg)
            if isinstance(parsed, dict):
                obj.update(parsed)
            else:
                obj["message"] = msg
        except (json.JSONDecodeError, TypeError):
            obj["message"] = msg
        if record.exc_info:
            obj["exc"] = self.formatException(record.exc_info)
        return json.dumps(obj, ensure_ascii=False)


def configure_logger(
    name: str,
    level: int = logging.DEBUG,
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handler_type: Literal["console", "file"] = "console",
    log_file: str = "tfbpmodeling.log",
) -> logging.Logger:
    """
    Configures a logger.

    When ``handler_type`` is ``"console"``, emits JSON so that CloudWatch Logs
    Insights can parse ``ts``, ``level``, ``logger``, and ``message`` as
    structured fields. When ``handler_type`` is ``"file"``, uses the plain-text
    ``format`` string instead.

    :param name: Name of the logger
    :type name: str
    :param level: Logging level, must be one of logging.DEBUG,
        logging.INFO, logging.WARNING, logging.ERROR
    :type level: int
    :param format: Logging format string, used only for the file handler.
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
        handler.setFormatter(_JsonFormatter())
    elif handler_type == "file":
        if not log_file:
            raise ValueError("log_file must be specified for file handler")
        handler = logging.FileHandler(log_file)
        handler.setFormatter(logging.Formatter(format))
    else:
        raise ValueError("Invalid handler_type. Must be 'console' or 'file'.")

    handler.setLevel(level)
    logger.addHandler(handler)

    return logger
