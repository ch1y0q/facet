"""Name the test library's people "Person NN" and score face naming against the answer key.

Each LFW folder is one person (folder NN_Name -> "Person NN"), and LFW crops every photo
around that person, so in each photo the face nearest the centre is the KNOWN face: the
person in the file name. Every other face is a bystander, an UNKNOWN face, labelled
"Unknown 01", "Unknown 02"... in the answer key. A good result names known faces
correctly and leaves unknown faces unnamed or ignored; an unknown face under a
"Person NN" name is an error.

For every person, the largest face group made mostly of their known faces becomes the
reference and gets the name. Split-off groups, ungrouped faces and unknown faces stay
unnamed, so Find more and the naming tools have real work to do.

Safety: --apply only runs on the test library (every photo folder must be listed in
people.csv) and never renames a person that already has a name other than an earlier
run's "Person NN". Manual faces are left out of the answer key. Nothing is written
without --apply or --score.

    python seed_names.py --db /app/data/photo_scores_pro.db            # report only
    python seed_names.py --db ... --apply                              # name references
    python seed_names.py --db ... --score                              # after testing

Writes beside the DB: reference.csv (Person NN, real name, person id, faces in group,
with --apply) and answer_key.csv (face id, photo, known/unknown, expected name).
"""

import argparse
import collections
import csv
import re
import sqlite3
import sys
from pathlib import Path

from lfw_common import AUTO_FACES_SQL, centre_offset, photo_parts, read_people, split_primary

SEEDED_NAME = re.compile(r"Person \d+")


def folder_of(path):
    """LFW folder (NN_Name) of a photo path: its parent folder, whatever the root."""
    return photo_parts(path)[0]


def label(folder):
    return f"Person {folder.split('_', 1)[0]}"


def answer_key(conn):
    """``[(face_id, person_id, photo, role, expected)]``, role ``known`` or ``unknown``.

    Per photo, the face nearest the image centre is the known one, if it is near enough
    (``lfw_common.split_primary``); otherwise the detector missed the person and every
    face in the photo is unknown. Unknown faces are numbered in photo order, one label
    per face: the bystanders' identities are not in the data, so two faces of one
    bystander get two labels. Manual faces are not part of the test.
    """
    by_photo = collections.defaultdict(list)
    for fid, pid, path, x1, y1, x2, y2 in conn.execute(
            "SELECT id, person_id, photo_path, bbox_x1, bbox_y1, bbox_x2, bbox_y2 FROM faces "
            f"WHERE {AUTO_FACES_SQL}"):
        by_photo[path].append((centre_offset(x1, y1, x2, y2), fid, pid))
    key, unknown = [], 0
    for path in sorted(by_photo):
        primary, bystanders = split_primary(by_photo[path])
        if primary:
            key.append((primary[1], primary[2], path, "known", label(folder_of(path))))
        for _, fid, pid in sorted(bystanders, key=lambda f: f[1]):
            unknown += 1
            key.append((fid, pid, path, "unknown", f"Unknown {unknown:02d}"))
    return key


def groups(key):
    """{person_id: Counter(folder -> known faces)} for grouped known faces."""
    by_person = collections.defaultdict(collections.Counter)
    for _, pid, path, role, _ in key:
        if pid is not None and role == "known":
            by_person[pid][folder_of(path)] += 1
    return by_person


def references(by_person, sizes):
    """{folder: (person_id, faces)}: the largest group whose majority is that folder."""
    best = {}
    for pid, counts in by_person.items():
        folder, n = counts.most_common(1)[0]
        if n * 2 > sizes[pid] and n > best.get(folder, (None, 0))[1]:
            best[folder] = (pid, n)
    return best


def score(conn, key):
    """Known faces: right / wrong / unnamed. Unknown faces: left alone / wrongly named."""
    names = dict(conn.execute("SELECT id, name FROM persons"))
    hidden = {pid for (pid,) in conn.execute("SELECT id FROM persons WHERE is_hidden = 1")} \
        if "is_hidden" in {r[1] for r in conn.execute("PRAGMA table_info(persons)")} else set()
    known = collections.Counter()
    unknown = collections.Counter()
    wrong_unknown = []
    for fid, pid, path, role, expected in key:
        name = (names.get(pid) or "").strip() if pid is not None else ""
        if role == "known":
            if not name:
                known["unnamed"] += 1
            elif name.lower() == expected.lower():
                known["right"] += 1
            else:
                known["wrong"] += 1
        elif name and pid not in hidden and not name.lower().startswith("unknown"):
            unknown["named"] += 1
            wrong_unknown.append((expected, fid, name, photo_parts(path)[1]))
        else:
            unknown["ok"] += 1
    nk, nu = sum(known.values()), sum(unknown.values())
    missed = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0] - nk
    print(f"photos whose person was not detected (no face near the centre): {missed}")
    print(f"known faces {nk}: right {known['right']}, wrong {known['wrong']}, unnamed {known['unnamed']} "
          f"({100 * known['right'] / max(nk, 1):.0f}% correctly named)")
    print(f"unknown faces {nu}: left unnamed/ignored {unknown['ok']}, wrongly given a person's name {unknown['named']}")
    for expected, fid, name, photo in wrong_unknown:
        print(f"  {expected} (face {fid}, {photo}) is under {name!r}")
    twice = conn.execute(
        f"SELECT f.photo_path, p.name, COUNT(*) FROM (SELECT * FROM faces WHERE {AUTO_FACES_SQL}) f "
        "JOIN persons p ON p.id = f.person_id WHERE p.name IS NOT NULL AND p.name != '' "
        "GROUP BY f.photo_path, f.person_id HAVING COUNT(*) > 1 ORDER BY f.photo_path").fetchall()
    print(f"photos with one name on two or more faces (always wrong): {len({t[0] for t in twice})}")
    for path, name, n in twice:
        print(f"  {photo_parts(path)[1]}: {name!r} x{n}")


def check_test_library(conn, people):
    """Exit unless every photo folder in the database is a test-library folder."""
    folders = {photo_parts(path)[0] for (path,) in conn.execute("SELECT path FROM photos")}
    stray = sorted(folders - set(people))
    if not folders or stray:
        reason = "no photos" if not folders else "folders not in people.csv: " + ", ".join(stray[:5])
        sys.exit(f"refusing --apply: this is not the test library ({reason})")


def renameable(conn, pids):
    """The persons among ``pids`` with no name or an earlier run's "Person NN"."""
    names = dict(conn.execute("SELECT id, name FROM persons"))
    return {pid for pid in pids
            if not (names.get(pid) or "").strip() or SEEDED_NAME.fullmatch(names[pid].strip())}


def write_answer_key(db, key):
    with open(Path(db).with_name("answer_key.csv"), "w", newline="", encoding="utf8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["face_id", "photo", "role", "expected"])
        writer.writerows((fid, path, role, expected) for fid, _, path, role, expected in key)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--people", default="/data/photos/people.csv")
    ap.add_argument("--apply", action="store_true", help="write the names")
    ap.add_argument("--score", action="store_true", help="only score current names")
    args = ap.parse_args()

    people = read_people(args.people)
    conn = sqlite3.connect(args.db)
    key = answer_key(conn)
    if args.score:
        write_answer_key(args.db, key)
        score(conn, key)
        return

    sizes = collections.Counter(pid for _, pid, _, _, _ in key if pid is not None)
    refs = references(groups(key), sizes)
    missing = sorted(set(people) - set(refs))
    named = {pid for pid, _ in refs.values()} - renameable(conn, {pid for pid, _ in refs.values()})
    for folder in sorted(f for f in refs if refs[f][0] in named):
        print(f"skipped {label(folder)}: person #{refs[folder][0]} already has a name")
        del refs[folder]
    rows = []
    for folder in sorted(refs):
        pid, n = refs[folder]
        rows.append((label(folder), people.get(folder, folder), pid, n))
        print(f"{label(folder)}  #{pid:<4} {n:>2} faces  ({people.get(folder, folder)})")
    print(f"{len(refs)} of {len(people)} people have a reference group")
    if missing:
        print("no reference group:", ", ".join(missing))
    if not args.apply:
        print("dry run: add --apply to name them")
        return
    check_test_library(conn, people)
    with conn:
        for name, _, pid, _ in rows:
            conn.execute("UPDATE persons SET name = ? WHERE id = ?", (name, pid))
        # The gallery filter's cached person list; the viewer's in-memory stats expire on
        # their own (restart it to see the names at once).
        conn.execute("DELETE FROM stats_cache WHERE key = 'persons'")
    write_answer_key(args.db, key)
    with open(Path(args.db).with_name("reference.csv"), "w", newline="", encoding="utf8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["name", "real_name", "person_id", "faces"])
        writer.writerows(rows)
    print(f"named {len(rows)}")
    score(conn, key)


if __name__ == "__main__":
    main()
