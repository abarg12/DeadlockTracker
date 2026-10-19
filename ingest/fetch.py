"""Downloads a fixed sample of recent matches as gzipped CSVs for the benchmarks (the app ingests on its own).

    python -m ingest.fetch --matches 50000 --days 7 --out data/raw
"""

import argparse
import csv
import gzip
import os
import time
from collections import Counter
from pathlib import Path

from ingest import lake


def write_csv(path: Path, header: list[str], rows) -> None:
    with gzip.open(path.with_name(path.name + ".part"), "wt", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def spread_order(n: int) -> list[int]:
    """Indices 0..n-1 ordered so any prefix is spread evenly (bit-reversal order)."""
    def reverse_bits(i: int) -> float:
        value, weight = 0.0, 0.5
        while i:
            value, i, weight = value + weight * (i & 1), i >> 1, weight / 2
        return value
    return sorted(range(n), key=reverse_bits)


def download(matches: int, days: float, out: Path) -> int:
    """Writes the CSVs for `matches` matches spread over the last `days` days; returns how many."""
    out.mkdir(parents=True, exist_ok=True)
    heroes, tiers, items = lake.reference_data()
    write_csv(out / "hero.csv.gz", ["hero_id", "name", "hero_type", "complexity"], heroes)
    write_csv(out / "item_tier.csv.gz", ["item_tier", "cost"], tiers)
    write_csv(out / "item.csv.gz", ["item_id", "name", "item_slot_type", "item_tier"], items)
    hero_ids, item_ids = {h[0] for h in heroes}, {i[0] for i in items}

    con = lake.connect()
    since = int(time.time() - days * 86400)
    chunks = lake.base_chunks(con, lake.manifest(), since)
    print(f"found {len(chunks)} data lake chunks overlapping the last {days:g} days")

    dropped = Counter()
    seen: set[int] = set()
    # every file is written as .part and renamed at the end, so a crash keeps the previous download
    files = {n: gzip.open(out / f"{n}.csv.gz.part", "wt", newline="") for n in ["match", "match_player", "match_player_item"]}
    writers = {n: csv.writer(f) for n, f in files.items()}
    writers["match"].writerow(lake.MATCH_COLUMNS)
    writers["match_player"].writerow(lake.PLAYER_COLUMNS)
    writers["match_player_item"].writerow(lake.ITEM_COLUMNS)

    # spread order keeps the sample covering the whole window whenever it fills up
    for n, index in enumerate(spread_order(len(chunks)), start=1):
        if len(seen) >= matches:
            break
        url, first_row, rows, _ = chunks[index]
        for match, players, bought in lake.match_records(lake.read_rows(con, url, since, first_row, rows),
                                                         hero_ids, item_ids, dropped):
            if len(seen) >= matches:
                break
            if match[0] in seen:
                continue
            seen.add(match[0])
            writers["match"].writerow([*match[:1], match[1].strftime("%Y-%m-%d %H:%M:%S+00"), *match[2:]])
            writers["match_player"].writerows(players)
            writers["match_player_item"].writerows(bought)
        print(f"chunk {n}: {len(seen)} matches kept so far")

    for f in files.values():
        f.close()
    for part in out.glob("*.csv.gz.part"):
        os.replace(part, part.with_suffix(""))
    print(f"\nwrote {len(seen)} matches to {out}/")
    for reason, count in dropped.most_common():
        print(f"  dropped {count}: {reason}")
    if len(seen) < matches:
        print(f"  note: asked for {matches}, but the window only had {len(seen)} usable matches")
    return len(seen)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--matches", type=int, default=50000, help="number of matches to download")
    parser.add_argument("--days", type=float, default=7, help="spread the sample over this many past days")
    parser.add_argument("--out", type=Path, default=Path("data/raw"))
    args = parser.parse_args()
    download(args.matches, args.days, args.out)


if __name__ == "__main__":
    main()
