import json
import logging
import time
from collections import defaultdict
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone

_perf_logger = logging.getLogger("shiny.perf")
_render_counts: dict[tuple[str, str, str], int] = defaultdict(int)


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
def perf(session_id: str, module: str, label: str) -> Generator[None, None, None]:
    """
    Time a reactive block and emit a JSON performance record.

    Increments a per-(session, module, label) render counter on entry so that
    re-renders within a single flush cycle are visible in the log. Each module
    tracks its own count independently, so the same label in two different
    modules does not share a counter.

    :param session_id: The Shiny session identifier (``session.id``).
    :type session_id: str
    :param module: Dotted module name, e.g. ``"binding.workspace"``.
    :type module: str
    :param label: Short name for the timed operation, e.g. ``"_all_corr_data"``.
    :type label: str

    """
    key = (session_id, module, label)
    _render_counts[key] += 1
    t0 = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session": session_id,
            "module": module,
            "label": label,
            "elapsed_ms": round(elapsed_ms, 2),
            "render_count": _render_counts[key],
        }
        _perf_logger.info(json.dumps(record))
