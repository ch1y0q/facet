"""Build a small, family-free test library for Facet from LFW (Labeled Faces in the Wild).

Picks people with at least --min-photos photos in the funneled LFW download made by
scikit-learn's ``fetch_lfw_people`` and copies --per-person of each into one folder per
person, so the library has a known answer for face grouping: every folder is one person.
The choice is deterministic (sorted names, first N), so every run and every machine
builds the same library.

    python testdb/make_lfw_subset.py --lfw <data_home>/lfw_home/lfw_funneled --out <photos dir>

Writes ``people.csv`` (folder, person, photos) next to the photos as the ground truth.
"""

import argparse
import csv
import shutil
from pathlib import Path


def pick(lfw: Path, people: int, per_person: int, min_photos: int) -> list[tuple[str, list[Path]]]:
    """``[(person, photos)]``: the first ``people`` names (sorted) with at least ``min_photos``."""
    chosen = []
    for person_dir in sorted(p for p in lfw.iterdir() if p.is_dir()):
        photos = sorted(person_dir.glob("*.jpg"))
        if len(photos) >= min_photos:
            chosen.append((person_dir.name, photos[:per_person]))
        if len(chosen) == people:
            break
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lfw", type=Path, required=True, help="lfw_home/lfw_funneled from fetch_lfw_people")
    parser.add_argument("--out", type=Path, required=True, help="photos folder to create")
    parser.add_argument("--people", type=int, default=20)
    parser.add_argument("--per-person", type=int, default=10)
    parser.add_argument("--min-photos", type=int, default=10)
    args = parser.parse_args()

    chosen = pick(args.lfw, args.people, args.per_person, args.min_photos)
    if len(chosen) < args.people:
        raise SystemExit(f"only {len(chosen)} people have {args.min_photos}+ photos")
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, (person, photos) in enumerate(chosen, start=1):
        folder = args.out / f"{index:02d}_{person}"
        folder.mkdir(exist_ok=True)
        for photo in photos:
            shutil.copy2(photo, folder / photo.name)
        rows.append((folder.name, person.replace("_", " "), len(photos)))
    with open(args.out / "people.csv", "w", newline="", encoding="utf8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["folder", "person", "photos"])
        writer.writerows(rows)
    print(f"{len(rows)} people, {sum(r[2] for r in rows)} photos -> {args.out}")


if __name__ == "__main__":
    main()
