"""``group_compare``: per-frame faces and subject metrics for one culling group, over /mcp.

[REAL] ``agent_app`` (real auth chain), the real ``/api/culling-group/*`` routes, rows and faces
seeded into the shared session DB.
"""

import io
import sqlite3

import numpy as np
import pytest
from PIL import Image

from tests.conftest import _TEST_DB_FILE, AGENT_DIR

PREFIX = AGENT_DIR + "gc/"
A, B, C = (PREFIX + n for n in ("a.jpg", "b.jpg", "c.jpg"))
GHOST = PREFIX + "ghost.jpg"


def jpeg(sharp: bool) -> bytes:
    if sharp:
        arr = ((np.indices((128, 128)).sum(axis=0) % 2) * 255).astype(np.uint8)
        img = Image.fromarray(np.stack([arr] * 3, axis=-1), mode="RGB")
    else:
        img = Image.new("RGB", (128, 128), (128, 128, 128))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


BOX = "[0.1, 0.1, 0.6, 0.6]"
ROWS = [
    {"path": A, "filename": "a.jpg", "thumbnail": jpeg(True), "subject_bbox": BOX, "subject_sharpness": 7.123,
     "subject_prominence": 0.456},
    {"path": B, "filename": "b.jpg", "thumbnail": jpeg(False), "subject_bbox": BOX, "subject_sharpness": 3.0,
     "subject_prominence": 0.2},
    {"path": C, "filename": "c.jpg", "thumbnail": jpeg(True), "subject_bbox": None},
]
# (path, face_index, eyes_open_score, smile_score)
FACES = [(A, 0, 9.0, 1.0), (A, 1, 2.0, 8.0), (B, 0, 7.0, 3.0), (B, 1, 8.0, 9.0), (C, 0, 9.5, 5.0)]


def db(sql, *args):
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        return conn.execute(sql, args).fetchall()


@pytest.fixture()
def world(agent_app, seed_photos_prefix):
    seed_photos_prefix(PREFIX, ROWS)
    for path, index, eyes, smile in FACES:
        db("INSERT INTO faces(embedding, photo_path, face_index, bbox_x1, bbox_y1, bbox_x2, bbox_y2, confidence, "
           "eyes_open_score, smile_score) VALUES (x'00', ?, ?, 1, 1, 9, 9, 0.99, ?, ?)", path, index, eyes, smile)
    env = agent_app("legacy")
    yield env, env.token(env.login(), "readonly")
    db("DELETE FROM faces WHERE photo_path LIKE ?", PREFIX + "%")


class TestFaces:
    def test_rows_carry_counts_worst_eyes_and_best_smile(self, world):
        env, token = world
        data = env.call(token, "group_compare", {"paths": [A, B, C], "by": "faces"})["data"]
        rows = {r["path"]: r for r in data["rows"]}
        assert rows[A]["faces"] == 2 and rows[A]["worst_eyes_open"] == 2.0 and rows[A]["best_smile"] == 8.0
        assert rows[B]["worst_eyes_open"] == 7.0 and rows[C]["faces"] == 1
        assert data["thresholds"]["eyes_closed_max"] is not None and data["missing_paths"] == []

    def test_blinks_follow_the_route_threshold(self, world):
        env, token = world
        data = env.call(token, "group_compare", {"paths": [A, B], "by": "faces"})["data"]
        rows = {r["path"]: r for r in data["rows"]}
        assert rows[A]["blinks"] == 1 and rows[B]["blinks"] == 0

    def test_best_path_is_the_frame_whose_worst_eye_is_most_open(self, world):
        env, token = world
        data = env.call(token, "group_compare", {"paths": [A, B, C], "by": "faces"})["data"]
        assert data["best_path_by_eyes"] == C

    def test_tie_breaks_by_sorted_path(self, world):
        env, token = world
        db("UPDATE faces SET eyes_open_score = 7.0 WHERE photo_path = ?", C)
        data = env.call(token, "group_compare", {"paths": [C, B], "by": "faces"})["data"]
        assert data["best_path_by_eyes"] == B

    def test_items_are_capped_rounded_and_carry_no_bbox(self, world):
        env, token = world
        for i in range(2, 9):
            db("INSERT INTO faces(embedding, photo_path, face_index, bbox_x1, bbox_y1, bbox_x2, bbox_y2, confidence, "
               "eyes_open_score) VALUES (x'00', ?, ?, 1, 1, 9, 9, 0.123456, 9.87654)", A, i)
        row = env.call(token, "group_compare", {"paths": [A], "by": "faces"})["data"]["rows"][0]
        assert row["faces"] == 9 and len(row["items"]) == 6
        assert all("bbox_x1" not in item and "bbox" not in item for item in row["items"])
        assert row["items"][-1]["eyes_open_score"] == 9.88 and row["items"][-1]["confidence"] == 0.12

    def test_paths_the_viewer_cannot_see_are_missing(self, world):
        env, token = world
        data = env.call(token, "group_compare", {"paths": [A, GHOST], "by": "faces"})["data"]
        assert data["missing_paths"] == [GHOST] and [r["path"] for r in data["rows"]] == [A]

    def test_all_missing_returns_empty_rows(self, world):
        env, token = world
        data = env.call(token, "group_compare", {"paths": [GHOST], "by": "faces"})["data"]
        assert data["rows"] == [] and data["missing_paths"] == [GHOST]

    def test_over_twelve_paths_are_refused(self, world):
        env, token = world
        refused = env.call(token, "group_compare", {"paths": [PREFIX + f"{i}.jpg" for i in range(13)], "by": "faces"})
        assert refused["ok"] is False


class TestSubjects:
    def test_sharpest_frame_and_no_image_in_the_output(self, world):
        env, token = world
        data = env.call(token, "group_compare", {"paths": [A, B, C], "by": "subjects"})["data"]
        rows = {r["path"]: r for r in data["rows"]}
        assert data["sharpest_path"] == A
        assert rows[A]["has_subject"] and rows[A]["subject_sharpness"] == 7.12 and rows[A]["subject_prominence"] == 0.46
        assert rows[C]["has_subject"] is False and rows[C]["crop_sharpness_score"] is None
        assert all("crop" not in r for r in rows.values())

    def test_no_value_is_long_enough_to_be_an_image(self, world):
        env, token = world

        def walk(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    assert key != "crop"
                    yield from walk(value)
            elif isinstance(node, list):
                for value in node:
                    yield from walk(value)
            else:
                yield node
        for by in ("faces", "subjects"):
            leaves = list(walk(env.call(token, "group_compare", {"paths": [A, B, C], "by": by})["data"]))
            assert leaves and all(len(str(v)) <= 200 for v in leaves)

    def test_no_subject_anywhere_gives_no_sharpest(self, world):
        env, token = world
        assert env.call(token, "group_compare", {"paths": [C], "by": "subjects"})["data"]["sharpest_path"] is None


class TestVisibility:
    def test_another_users_library_is_missing_not_leaked(self, agent_app, seed_photos_prefix):
        seed_photos_prefix(PREFIX, ROWS)
        db("INSERT INTO faces(embedding, photo_path, face_index, bbox_x1, bbox_y1, bbox_x2, bbox_y2, confidence, "
           "eyes_open_score) VALUES (x'00', ?, 0, 1, 1, 9, 9, 0.9, 5.0)", A)
        try:
            env = agent_app("multi")
            bob = env.token(env.login("bob"), "readonly")
            for by in ("faces", "subjects"):
                data = env.call(bob, "group_compare", {"paths": [A, B], "by": by})["data"]
                assert data["rows"] == [] and sorted(data["missing_paths"]) == [A, B]
            alice = env.token(env.login("alice"), "readonly")
            assert env.call(alice, "group_compare", {"paths": [A], "by": "faces"})["data"]["rows"][0]["faces"] == 1
        finally:
            db("DELETE FROM faces WHERE photo_path LIKE ?", PREFIX + "%")

    def test_readonly_token_may_call_it(self, world):
        env, token = world
        assert "group_compare" in env.tool_names(token)
