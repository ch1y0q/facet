"""Helpers shared by the test-library scripts: photo paths, people.csv and the primary face.

LFW photos are 250x250 and cropped around the labelled person, so the face nearest the
centre is that person (the PRIMARY face) and every other face is a bystander. When the
detector misses the person, the nearest face is a bystander, so a face only counts as
primary within ``PRIMARY_MAX_OFFSET`` px of the centre: on the baseline library primary
faces sit at most 31 px from it and bystanders at least 67 px.
"""

import csv
import math
from pathlib import PurePosixPath, PureWindowsPath

LFW_CENTRE = 125
PRIMARY_MAX_OFFSET = 45
ARCFACE_MODEL = "arcface_buffalo_l"

# Detected faces with an ArcFace embedding: manual faces store an empty embedding, and a
# commercial build's SFace embeddings are another size. NULL tags predate the column and
# are ArcFace, as in Facet's own clusterer.
AUTO_FACES_SQL = (
    "is_manual = 0 AND length(embedding) > 0 "
    f"AND (embedding_model = '{ARCFACE_MODEL}' OR embedding_model IS NULL)"
)


def photo_parts(path):
    """``(folder, file name)`` of a stored photo path, from any OS.

    A database scanned on Windows stores Windows paths (drive letter, backslashes); read on Linux,
    ``Path`` would not split it, so a backslash selects Windows path rules.
    """
    p = PureWindowsPath(path) if "\\" in path else PurePosixPath(path)
    return p.parent.name, p.name


def centre_offset(x1, y1, x2, y2):
    """Distance in px from a face box's centre to the LFW photo's centre."""
    return math.hypot((x1 + x2) / 2 - LFW_CENTRE, (y1 + y2) / 2 - LFW_CENTRE)


def split_primary(faces):
    """``(primary or None, bystanders)`` of one photo's ``[(offset, ...)]`` faces."""
    faces = sorted(faces, key=lambda f: f[0])
    if faces and faces[0][0] <= PRIMARY_MAX_OFFSET:
        return faces[0], faces[1:]
    return None, faces


def read_people(path):
    """``{folder: person}`` from a test library's people.csv."""
    with open(path, encoding="utf8") as handle:
        return {row["folder"]: row["person"] for row in csv.DictReader(handle)}
