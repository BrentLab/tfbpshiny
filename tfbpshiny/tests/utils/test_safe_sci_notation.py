import numpy as np
import pandas as pd

from tfbpshiny.utils.safe_sci_notatation import safe_sci_notation


def test_safe_sci_notation_numeric():
    assert safe_sci_notation(0.0001234) == "1.23e-04"
    assert safe_sci_notation("1000") == "1.00e+03"
    assert safe_sci_notation(42) == "4.20e+01"


def test_safe_sci_notation_non_numeric():
    assert safe_sci_notation("not_a_number") == "not_a_number"
    assert safe_sci_notation(None) is None
    assert pd.isna(safe_sci_notation(np.nan))  # Use pd.isna to check for NaN
