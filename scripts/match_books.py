"""Match library books to rows in the ML catalog and persist books.ml_idx.

Usage:
    python scripts/match_books.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from recommender import get_recommender  # noqa: E402


def main() -> int:
    recommender = get_recommender()
    if not recommender.ok:
        print(f"Recommender could not load: {recommender.error}")
        return 1

    result = recommender.match_library_books()
    print(f"Total library books: {result['total']}")
    print(f"Matched: {result['matched']}")
    print(f"Unmatched: {len(result['unmatched'])}")
    for title in result["unmatched"]:
        print(f"  - {title}")
    if result["total"]:
        print(f"Match rate: {result['matched'] / result['total']:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
