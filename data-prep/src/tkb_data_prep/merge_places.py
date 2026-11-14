"""Merge several POI name indexes (same schema) into one new SQLite index."""

from __future__ import annotations

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path

from tkb_common.place_names import PLACE_INDEX_SCHEMA_VERSION


def merge_place_indexes(inputs: list[Path], output_path: Path) -> dict[str, int]:
    """Copy poi_place/poi_alias rows of every input into a new index.

    Inputs are opened read-only and are never modified. place_ids are already
    namespaced by dataset, so equal ids are treated as duplicates and the first
    input wins. Returns the number of places newly added per input path.
    """
    if not inputs:
        raise ValueError("at least one input index is required")
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite existing index: {output_path}")
    for path in inputs:
        if not path.is_file():
            raise FileNotFoundError(f"input index not found: {path}")
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as source:
            version = source.execute("PRAGMA user_version").fetchone()[0]
        if version != PLACE_INDEX_SCHEMA_VERSION:
            raise ValueError(
                f"{path} has schema version {version}, expected {PLACE_INDEX_SCHEMA_VERSION}"
            )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    added: dict[str, int] = {}
    with closing(sqlite3.connect(output_path, uri=False)) as db:
        # Keep the partial file unusable until every input has been copied.
        db.execute("PRAGMA user_version = 0")
        db.execute("PRAGMA journal_mode = OFF")
        db.execute("PRAGMA synchronous = OFF")
        db.executescript(
            """
            CREATE TABLE poi_place (
                place_id TEXT PRIMARY KEY,
                license_verified INTEGER NOT NULL,
                record_json TEXT NOT NULL
            );
            CREATE TABLE poi_alias (
                name_key TEXT NOT NULL,
                place_id TEXT NOT NULL,
                PRIMARY KEY(name_key, place_id),
                FOREIGN KEY(place_id) REFERENCES poi_place(place_id)
            );
            CREATE INDEX poi_alias_name_idx ON poi_alias(name_key);
            """
        )
        for path in inputs:
            # ATTACH honours URI filenames only when the connection enabled them.
            db.execute("ATTACH DATABASE ? AS src", (str(path.resolve()),))
            before = db.execute("SELECT COUNT(*) FROM poi_place").fetchone()[0]
            db.execute("INSERT OR IGNORE INTO poi_place SELECT * FROM src.poi_place")
            db.execute("INSERT OR IGNORE INTO poi_alias SELECT * FROM src.poi_alias")
            after = db.execute("SELECT COUNT(*) FROM poi_place").fetchone()[0]
            added[str(path)] = after - before
            db.commit()
            db.execute("DETACH DATABASE src")
        db.execute(f"PRAGMA user_version = {PLACE_INDEX_SCHEMA_VERSION}")
        db.commit()
    return added


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        added = merge_place_indexes(args.input, args.output)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    for path, count in added.items():
        print(f"{count} places from {path}")


if __name__ == "__main__":
    main()
