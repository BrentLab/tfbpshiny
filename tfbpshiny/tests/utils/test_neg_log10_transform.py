import numpy as np
import pandas as pd
import pytest

from tfbpshiny.utils.neg_log10_transform import neg_log10_transform


def test_neg_log10_transform_success():
    series = pd.Series([1e-2, 1e-5, 1e-10])
    transformed = neg_log10_transform(series)
    expected = -np.log10(series)
    pd.testing.assert_series_equal(transformed, expected)


def test_neg_log10_transform_clip_warning(caplog):
    series = pd.Series([1e-2, 1e-400, 1e-10])
    with caplog.at_level("WARNING"):
        result = neg_log10_transform(series)
    assert "adjusted for log10 scale" in caplog.text
    assert result[1] == -np.log10(1e-300)


def test_neg_log10_transform_non_series():
    with pytest.raises(TypeError, match="Input must be a pandas Series."):
        neg_log10_transform([0.1, 0.01])


def test_neg_log10_transform_non_numeric_series():
    with pytest.raises(ValueError, match="Input Series must be numeric."):
        neg_log10_transform(pd.Series(["a", "b", "c"]))


def test_neg_log10_transform_contains_nan():
    with pytest.raises(ValueError, match="Input Series contains NaN values."):
        neg_log10_transform(pd.Series([0.1, np.nan]))


def test_neg_log10_transform_non_positive_values():
    with pytest.raises(ValueError, match="Input Series contains non-positive values."):
        neg_log10_transform(pd.Series([0.1, 0.0, -1]))


def test_neg_log10_transform_non_numeric_epsilon():
    with pytest.raises(TypeError, match="Epsilon must be a numeric value."):
        neg_log10_transform(pd.Series([0.1, 0.01]), epsilon="small")  # type: ignore
