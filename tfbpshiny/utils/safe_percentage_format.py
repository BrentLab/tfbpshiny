import logging

import pandas as pd

logger = logging.getLogger("shiny")


def safe_percentage_format(x: str | object) -> object | str:
    """
    Format a fraction as a percentage with no decimal places and a percent symbol. If
    the input is NaN or cannot be converted to a float, return the input as is.

    :param x: The input value to format (should be a fraction between 0 and 1).
    :return: The percentage string or the original input if it cannot be formatted.

    """
    if pd.isna(x):
        return x
    try:
        percentage = float(x) * 100  # type: ignore
        return f"{round(percentage)}%"
    except Exception:
        logger.warning(f"Failed to convert {x} to float for percentage formatting.")
        return x
