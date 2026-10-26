"""Pick reference faces for the test library's people: LFW photos NOT in the test set.

The open-set test enrolls each known person from a few reference photos, then asks of
every face in the test photos "is this one of the known people, or Unknown?". The
references must be photos the test never sees, or it is marked against itself. LFW
has more photos of most people than the 10 the test library uses, so the spares are
the references: up to --per-person of them, in sorted order (deterministic).

A person with no spare photo gets the first of their test photos as reference; it is
recorded in references.csv as ``from_test_set`` and the evaluation leaves it out of the
score.

    python testdb/make_references.py --lfw <lfw_funneled> --photos <test photos> --out <references dir>
"""

import argparse
import csv
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lfw", type=Path, required=True)
    parser.add_argument("--photos", type=Path, required=True, help="test library (with people.csv)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--per-person", type=int, default=3)
    args = parser.parse_args()

    with open(args.photos / "people.csv", encoding="utf8") as handle:
        people = list(csv.DictReader(handle))
    rows = []
    for person in people:
        folder = person["folder"]
        name = folder.split("_", 1)[1]
        used = {p.name for p in (args.photos / folder).glob("*.jpg")}
        spares = [p for p in sorted((args.lfw / name).glob("*.jpg")) if p.name not in used]
        chosen = [(p, "spare") for p in spares[:args.per_person]]
        if not chosen:
            chosen = [(args.photos / folder / sorted(used)[0], "from_test_set")]
        dest = args.out / folder
        dest.mkdir(parents=True, exist_ok=True)
        for src, source in chosen:
            shutil.copy2(src, dest / src.name)
            rows.append((folder, person["person"], src.name, source))
    with open(args.out / "references.csv", "w", newline="", encoding="utf8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["folder", "person", "photo", "source"])
        writer.writerows(rows)
    print(f"{len(people)} people, {len(rows)} reference photos "
          f"({sum(r[3] == 'from_test_set' for r in rows)} from the test set) -> {args.out}")


if __name__ == "__main__":
    main()
