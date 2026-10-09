"""
Compare two ``snapshot_db.py`` outputs table by table.

Prints one line per table: ``same``, ``rows changed``, ``content changed`` (same row
count, different hash), ``columns changed``, ``added`` or ``removed``. Exits non-zero
when anything differs, so it can gate a CI step.

Usage::

    poetry run python scripts/diff_snapshots.py baseline.json after.json

"""

from __future__ import annotations

import json
import sys


def classify(before: dict | None, after: dict | None) -> str:
    """Describe the difference between two table fingerprints."""
    if before is None:
        return "added"
    if after is None:
        return "removed"
    if before["columns"] != after["columns"]:
        return "columns changed"
    if before["rows"] != after["rows"]:
        return f"rows changed ({before['rows']:,} -> {after['rows']:,})"
    if before["md5"] != after["md5"]:
        return "content changed"
    return "same"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print(__doc__)
        return 2
    with open(argv[0]) as fh:
        before = json.load(fh)
    with open(argv[1]) as fh:
        after = json.load(fh)
    differences = 0
    for table in sorted(set(before) | set(after)):
        verdict = classify(before.get(table), after.get(table))
        if verdict != "same":
            differences += 1
        print(f"{table:42s} {verdict}")
    print(
        f"\n{differences} table(s) differ" if differences else "\nall tables identical"
    )
    return 1 if differences else 0


if __name__ == "__main__":
    sys.exit(main())
