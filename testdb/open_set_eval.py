"""Open-set face naming on the test library: known people at a confidence threshold, else Unknown.

1. Enroll: embed each reference photo (make_references.py) with the same ArcFace model
   Facet uses (InsightFace buffalo_l); a person's reference is the mean of their faces.
2. Test: for every face Facet detected in the test photos, take the most similar known
   person. Similarity >= T names it that person; below T it is Unknown 1, 2, 3...
3. Score with the answer key, which the tester never sees: in each photo the face
   nearest the centre is the primary (the person in the file name, LFW crops around
   them); every other face is a bystander and should come out Unknown.

Sweeps T and prints, per threshold: primary faces named right / wrong / Unknown, and
bystanders Unknown / wrongly named. Also compares 1 reference per person with all.
Reads only; Facet's database is not changed.

    python open_set_eval.py --db /app/data/photo_scores_pro.db --refs /data/references
"""

import argparse
import collections
import csv
from pathlib import Path

import cv2
import numpy as np

LFW_CENTRE = 125


def unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def enroll(refs_dir, max_refs):
    """{folder: unit mean embedding}, plus the test-set photos used as references."""
    from insightface.app import FaceAnalysis
    app = FaceAnalysis(name="buffalo_l", providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=(640, 640))
    with open(refs_dir / "references.csv", encoding="utf8") as handle:
        rows = list(csv.DictReader(handle))
    per_person = collections.defaultdict(list)
    excluded = set()
    for row in rows:
        if len(per_person[row["folder"]]) >= max_refs:
            continue
        img = cv2.imread(str(refs_dir / row["folder"] / row["photo"]))
        faces = app.get(img)
        if not faces:
            continue
        h, w = img.shape[:2]
        face = min(faces, key=lambda f: ((f.bbox[0] + f.bbox[2]) / 2 - w / 2) ** 2 + ((f.bbox[1] + f.bbox[3]) / 2 - h / 2) ** 2)
        per_person[row["folder"]].append(unit(face.embedding))
        if row["source"] == "from_test_set":
            excluded.add(f"/data/photos/{row['folder']}/{row['photo']}")
    return {k: unit(np.mean(v, axis=0)) for k, v in per_person.items()}, excluded


def test_faces(db):
    """``[(photo, role, true_folder, unit embedding)]``, role primary or bystander."""
    import sqlite3
    conn = sqlite3.connect(db)
    by_photo = collections.defaultdict(list)
    for path, x1, y1, x2, y2, emb in conn.execute(
            "SELECT photo_path, bbox_x1, bbox_y1, bbox_x2, bbox_y2, embedding FROM faces WHERE embedding IS NOT NULL"):
        off = ((x1 + x2) / 2 - LFW_CENTRE) ** 2 + ((y1 + y2) / 2 - LFW_CENTRE) ** 2
        by_photo[path].append((off, unit(np.frombuffer(emb, np.float32))))
    photos = [p for p in conn.execute("SELECT path FROM photos")]
    out = []
    for path, faces in by_photo.items():
        folder = Path(path).parts[3]
        faces.sort(key=lambda f: f[0])
        out.append((path, "primary", folder, faces[0][1]))
        out.extend((path, "bystander", folder, f[1]) for f in faces[1:])
    return out, len(photos), len(by_photo)


def sweep(people, faces, excluded, thresholds):
    names = list(people)
    matrix = np.stack([people[n] for n in names])
    best = []
    for path, role, folder, emb in faces:
        if path in excluded:
            continue
        sims = matrix @ emb
        i = int(np.argmax(sims))
        best.append((role, folder, names[i], float(sims[i])))
    n_primary = sum(r == "primary" for r, *_ in best)
    n_by = len(best) - n_primary
    print(f"  {'T':>5} | primary (of {n_primary}): right  wrong  unknown | bystanders (of {n_by}): unknown  named")
    rows = []
    for t in thresholds:
        c = collections.Counter()
        for role, folder, guess, sim in best:
            if role == "primary":
                c["p_unknown" if sim < t else ("p_right" if guess == folder else "p_wrong")] += 1
            else:
                c["b_unknown" if sim < t else "b_named"] += 1
        rows.append((t, c))
        print(f"  {t:5.2f} | {c['p_right']:>21}  {c['p_wrong']:>5}  {c['p_unknown']:>7} | "
              f"{c['b_unknown']:>30}  {c['b_named']:>5}")
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--refs", type=Path, required=True)
    args = ap.parse_args()
    faces, n_photos, with_faces = test_faces(args.db)
    print(f"{n_photos} photos, {with_faces} with at least one face; {len(faces)} faces "
          f"({sum(f[1] == 'primary' for f in faces)} primary, {sum(f[1] == 'bystander' for f in faces)} bystanders)")
    thresholds = [round(x, 2) for x in np.arange(0.20, 0.61, 0.05)]
    for k in (1, 3):
        people, excluded = enroll(args.refs, k)
        print(f"\n{k} reference photo(s) per person ({len(people)} people enrolled):")
        sweep(people, faces, excluded, thresholds)


if __name__ == "__main__":
    main()
