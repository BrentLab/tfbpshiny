import json
import logging
import os
import time
from collections import defaultdict
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone

_perf_logger = logging.getLogger("shiny.perf")
_render_counts: dict[tuple[str, str, str], int] = defaultdict(int)

# Page size for the /proc/self/statm RSS read, resolved once at import. ``None``
# disables memory reporting on platforms without ``SC_PAGE_SIZE`` (e.g. Windows).
try:
    _PAGE_SIZE: int | None = os.sysconf("SC_PAGE_SIZE")
except (ValueError, AttributeError, OSError):
    _PAGE_SIZE = None


def _current_rss_mb() -> float | None:
    """
    Return the process resident set size in MiB, or ``None`` if unavailable.

    Reads the resident-pages field of ``/proc/self/statm`` (a single small read
    of an in-memory pseudo-file) and multiplies by the page size. This is
    effectively zero overhead — no extra dependency and no process spawn — so it
    is safe to call on every timed block. Returns ``None`` on any platform where
    ``/proc`` or ``SC_PAGE_SIZE`` is unavailable, so callers degrade gracefully.

    :returns: Current RSS in MiB, or ``None`` if it cannot be read.
    :rtype: float | None

    """
    if _PAGE_SIZE is None:
        return None
    try:
        with open("/proc/self/statm") as fh:
            resident_pages = int(fh.read().split()[1])
    except (OSError, IndexError, ValueError):
        return None
    return resident_pages * _PAGE_SIZE / (1024 * 1024)


def reset_render_counts(session_id: str) -> None:
    """
    Reset per-flush render counts for one session.

    :param session_id: The Shiny session identifier.
    :type session_id: str

    """
    keys = [k for k in _render_counts if k[0] == session_id]
    for k in keys:
        del _render_counts[k]


@contextmanager
def perf(
    session_id: str, module: str, label: str, kind: str = "render"
) -> Generator[None, None, None]:
    """
    Time a reactive block and emit a JSON performance record.

    Increments a per-(session, module, label) render counter on entry so that
    re-renders within a single flush cycle are visible in the log. Each module
    tracks its own count independently, so the same label in two different
    modules does not share a counter.

    The record carries wall-clock duration (``elapsed_ms``) and, when readable,
    resident memory at block exit (``rss_mb``) and the net change across the
    block (``rss_delta_mb``). Memory is read from ``/proc/self/statm`` with
    negligible overhead; the memory fields are omitted when unavailable.

    :param session_id: The Shiny session identifier (``session.id``).
    :type session_id: str
    :param module: Dotted module name, e.g. ``"binding.workspace"``.
    :type module: str
    :param label: Short name for the timed operation, e.g. ``"_all_corr_data"``.
    :type label: str
    :param kind: Category of work being timed, used to filter the log. Use
        ``"data"`` for database/query work and ``"render"`` (default) for UI
        rendering.
    :type kind: str

    """
    key = (session_id, module, label)
    _render_counts[key] += 1
    rss_start = _current_rss_mb()
    t0 = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        rss_end = _current_rss_mb()
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session": session_id,
            "module": module,
            "label": label,
            "kind": kind,
            "elapsed_ms": round(elapsed_ms, 2),
            "render_count": _render_counts[key],
        }
        if rss_end is not None:
            record["rss_mb"] = round(rss_end, 1)
            if rss_start is not None:
                record["rss_delta_mb"] = round(rss_end - rss_start, 1)
        _perf_logger.info(json.dumps(record))
