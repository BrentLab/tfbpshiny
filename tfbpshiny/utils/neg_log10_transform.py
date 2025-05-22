import logging

import numpy as np
import pandas as pd

from .safe_sci_notatation import safe_sci_notation

logger = logging.getLogger(__name__)


def neg_log10_transform(series: pd.Series, epsilon: float = 1e-300) -> pd.Series:
    """
    Apply a negative log10 transformation to a pandas Series, handling zero and negative
    values by clipping them to a small epsilon value.

    :param series: The input pandas Series to transform.
    :param epsilon: A small value to avoid log10(0) or log10 of negative numbers.
        Default is 1e-300.
    :return: A new pandas Series with the transformed values.
    :raises ValueError: If the input is not a pandas Series, if it contains non-numeric
        values, values less than zero, or if it contains NaN values.
    :raises TypeError: If the input is not a pandas Series or if epsilon is not numeric.

    """
    # validate that the input is a pandas Series and is numeric
    if not isinstance(series, pd.Series):
        raise TypeError("Input must be a pandas Series.")
    if not pd.api.types.is_numeric_dtype(series):
        raise ValueError("Input Series must be numeric.")
    if series.isnull().any():
        raise ValueError("Input Series contains NaN values.")
    if (series < 0).any():
        raise ValueError("Input Series contains non-positive values.")
    if not isinstance(epsilon, (int, float)):
        raise TypeError("Epsilon must be a numeric value.")

    # Check for values less than or equal to epsilon and log
    num_zeros = (series <= epsilon).sum()
    if num_zeros > 0:
        logger.warning(
            f"{num_zeros} values were ≤ {safe_sci_notation(epsilon)} "
            "and adjusted for log10 scale."
        )

    return -np.log10(series.clip(lower=epsilon))
