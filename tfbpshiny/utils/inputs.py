"""Read a Shiny input with a fallback for the moment before the client has sent it."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from shiny.types import SilentException

T = TypeVar("T")


def read_input(
    input: Any,
    name: str,
    default: T,
    cast: Callable[[Any], T] | None = None,
) -> T:
    """
    Return ``input.<name>()`` cast with ``cast``, or ``default`` when unavailable.

    An input created by a ``render.ui`` has no value until the browser has drawn it and
    sent one back; ``input.<name>()`` raises :class:`~shiny.types.SilentException` in
    that window. Reading it still registers the reactive dependency, so the caller
    re-runs once the value arrives. A ``None`` value (a select with no choices) and a
    value the cast rejects also fall back to ``default``.

    :param input: The Shiny ``input`` object.
    :param name: Input id.
    :param default: Returned when the input has no usable value yet.
    :param cast: Converter applied to the raw value, e.g. ``int``; ``None`` returns the
        value as sent.
    :returns: The cast value, or ``default``.

    """
    try:
        value = getattr(input, name)()
    except SilentException:
        return default
    if value is None:
        return default
    if cast is None:
        return value  # type: ignore[no-any-return]
    try:
        return cast(value)
    except (TypeError, ValueError):
        return default


__all__ = ["read_input"]
