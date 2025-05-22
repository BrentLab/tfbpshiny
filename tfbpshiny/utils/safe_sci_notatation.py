import logging

import pandas as pd

logger = logging.getLogger("shiny")


def safe_sci_notation(x: str | object) -> object | str:
    """
    Format a number in scientific notation with 2 decimal places. If the input is NaN or
    cannot be converted to a float, return the input as is.

    :param x: The input value to format.
    :return: The formatted string or the original input if it cannot be formatted.

    """
    if pd.isna(x):
        return x
    try:
        return f"{float(x):.2e}"  # type: ignore
    except Exception:
        logger.debug(
            f"Failed to convert {x} to float for scientific notation formatting."
        )
        return x
