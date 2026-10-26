"""Open-set face naming on the test library: known people at a confidence threshold, else Unknown.

1. Enroll: embed each reference photo (make_references.py) with the same ArcFace model
   Facet uses (InsightFace buffalo_l); a person's reference is the mean of their faces.
2. Test: for every face Facet detected in the test photos, take the most similar known
   person. Similarity >= T names it that person; below T it is Unknown 1, 2, 3...
3. Score with the answer key, which the tester never sees: in each photo the face
   nearest the centre, if near enough, is the primary (the person in the file name, LFW
   crops around them); every other face is a bystander and should come out Unknown.
   Only detected ArcFace faces are tested: manual faces have no embedding.

Sweeps T and prints, per threshold: primary faces named right / wrong / Unknown, and
bystanders Unknown / wrongly named. Also compares 1 reference per person with all.
Reads only; Facet's database is not changed.

    python open_set_eval.py --db /app/data/photo_scores_pro.db --refs /data/references
"""

import argparse
import collections
import csv
import sqlite3
from pathlib import Path

import cv2
import numpy as np

from lfw_common import AUTO_FACES_SQL, centre_offset, photo_parts, split_primary


def unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def embed_references(refs_dir):
    """``[(folder, photo, source, unit embedding)]`` for every reference photo with a face.

    The face model loads once; enroll() then picks the first k per person.
    """
    from insightface.app import FaceAnalysis
    app = FaceAnalysis(name="buffalo_l", providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=(640, 640))
    with open(refs_dir / "references.csv", encoding="utf8") as handle:
        rows = list(csv.DictReader(handle))
    out = []
    for row in rows:
        img = cv2.imread(str(refs_dir / row["folder"] / row["photo"]))
        faces = app.get(img) if img is not None else []
        if not faces:
            continue
        h, w = img.shape[:2]
        face = min(faces, key=lambda f: ((f.bbox[0] + f.bbox[2]) / 2 - w / 2) ** 2 + ((f.bbox[1] + f.bbox[3]) / 2 - h / 2) ** 2)
        out.append((row["folder"], row["photo"], row["source"], unit(face.embedding)))
    return out


def enroll(references, max_refs):
    """{folder: unit mean embedding}, plus the test-set photos used as references, as (folder, file)."""
    per_person = collections.defaultdict(list)
    excluded = set()
    for folder, photo, source, emb in references:
        if len(per_person[folder]) >= max_refs:
            continue
        per_person[folder].append(emb)
        if source == "from_test_set":
            excluded.add((folder, photo))
    return {k: unit(np.mean(v, axis=0)) for k, v in per_person.items()}, excluded


def test_faces(db):
    """``[(photo, role, true_folder, unit embedding)]``, role primary or bystander.

    Also returns the photo count, the photos with a face, and the photos whose person was
    not detected (no face near the centre: all their faces are bystanders).
    """
    conn = sqlite3.connect(db)
    by_photo = collections.defaultdict(list)
    for path, x1, y1, x2, y2, emb in conn.execute(
            "SELECT photo_path, bbox_x1, bbox_y1, bbox_x2, bbox_y2, embedding FROM faces "
            f"WHERE {AUTO_FACES_SQL}"):
        by_photo[path].append((centre_offset(x1, y1, x2, y2), unit(np.frombuffer(emb, np.float32))))
    n_photos = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
    out, missed = [], 0
    for path, faces in by_photo.items():
        folder = photo_parts(path)[0]
        primary, bystanders = split_primary(faces)
        if primary:
            out.append((path, "primary", folder, primary[1]))
        else:
            missed += 1
        out.extend((path, "bystander", folder, f[1]) for f in bystanders)
    return out, n_photos, len(by_photo), missed


def sweep(people, faces, excluded, thresholds):
    names = list(people)
    matrix = np.stack([people[n] for n in names])
    best = []
    for path, role, folder, emb in faces:
        if photo_parts(path) in excluded:
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
    faces, n_photos, with_faces, missed = test_faces(args.db)
    print(f"{n_photos} photos, {with_faces} with at least one face; {len(faces)} faces "
          f"({sum(f[1] == 'primary' for f in faces)} primary, {sum(f[1] == 'bystander' for f in faces)} bystanders); "
          f"person not detected in {missed} photo(s) with faces")
    thresholds = [round(x, 2) for x in np.arange(0.20, 0.61, 0.05)]
    references = embed_references(args.refs)
    for k in (1, 3):
        people, excluded = enroll(references, k)
        print(f"\n{k} reference photo(s) per person ({len(people)} people enrolled):")
        sweep(people, faces, excluded, thresholds)


if __name__ == "__main__":
    main()
