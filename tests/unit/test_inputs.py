"""``read_input`` is the one place a not-yet-sent Shiny input becomes a default."""

from __future__ import annotations

from typing import Any

import pytest
from shiny.types import SilentException

from tfbpshiny.utils.inputs import read_input


class _FakeInput:
    """Stands in for Shiny's ``input``: attributes are callables returning a value."""

    def __init__(self, **values: Any) -> None:
        self._values = values

    def __getattr__(self, name: str) -> Any:
        def _get() -> Any:
            if name not in self._values:
                # What shiny raises until the client has sent the input's value.
                raise SilentException
            return self._values[name]

        return _get


def test_returns_the_cast_value_when_present() -> None:
    assert read_input(_FakeInput(top_n="25"), "top_n", 10, int) == 25


def test_returns_the_raw_value_without_a_cast() -> None:
    assert read_input(_FakeInput(picked=["a", "b"]), "picked", None) == ["a", "b"]


def test_falls_back_when_the_input_has_not_arrived() -> None:
    assert read_input(_FakeInput(), "top_n", 10, int) == 10


def test_falls_back_on_a_none_value() -> None:
    assert read_input(_FakeInput(tf=None), "tf", "", str) == ""


def test_falls_back_when_the_cast_rejects_the_value() -> None:
    assert read_input(_FakeInput(top_n="many"), "top_n", 10, int) == 10


def test_other_exceptions_propagate() -> None:
    """Only the 'not yet available' cases are swallowed; a real error must surface."""

    class _Broken:
        def __getattr__(self, name: str) -> Any:
            def _get() -> Any:
                raise RuntimeError("boom")

            return _get

    with pytest.raises(RuntimeError):
        read_input(_Broken(), "x", 0, int)
