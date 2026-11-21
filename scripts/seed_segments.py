"""Create/update the ten ML segment rows from Machine_Learning/segment_report.csv.

Usage:
    python scripts/seed_segments.py

Idempotent: matches on (kind='ml', ml_cluster).
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pandas as pd  # noqa: E402

from db import execute, query_one  # noqa: E402

REPORT = os.path.join(ROOT, "Machine_Learning", "segment_report.csv")


def parse_top_genres(text: str) -> list[tuple[str, float]]:
    parsed = []
    for part in str(text).split(","):
        match = re.search(r"(.+?)\s*\((\d+(?:\.\d+)?)%\)", part.strip())
        if match:
            parsed.append((match.group(1).strip(), float(match.group(2))))
    return parsed


def segment_name(top: list[tuple[str, float]], cluster: int) -> str:
    if not top:
        return f"Readers group {cluster + 1}"
    first, first_pct = top[0]
    if len(top) > 1 and first_pct < 60 and top[1][1] >= 5:
        return f"{first} & {top[1][0]} readers"
    if first == "Fantasy":
        return "Fantasy lovers"
    if first == "Mystery & Thriller":
        return "Mystery & Thriller fans"
    if first == "Romance":
        return "Romance readers"
    return f"{first} readers"


def main() -> int:
    if not os.path.isfile(REPORT):
        print(f"Missing {REPORT}")
        return 1

    report = pd.read_csv(REPORT)
    created = updated = 0
    for row in report.itertuples(index=False):
        cluster = int(row.segment)
        top = parse_top_genres(row.top_genres)
        name = segment_name(top, cluster)
        description = f"Automatic KMeans segment {cluster} (top genres from segment_report.csv)."

        existing = query_one(
            "SELECT segment_id FROM segments WHERE kind = 'ml' AND ml_cluster = %s",
            (cluster,),
        )
        if existing:
            execute(
                "UPDATE segments SET label = %s, name = %s, description = %s, "
                "top_genres = %s WHERE segment_id = %s",
                (name, name, description, row.top_genres, existing["segment_id"]),
            )
            updated += 1
            print(f"Updated cluster {cluster}: {name}")
        else:
            execute(
                "INSERT INTO segments (label, name, description, kind, ml_cluster, top_genres) "
                "VALUES (%s, %s, %s, 'ml', %s, %s)",
                (name, name, description, cluster, row.top_genres),
            )
            created += 1
            print(f"Created cluster {cluster}: {name}")

    print(f"Done. Created {created}, updated {updated} ML segments.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
