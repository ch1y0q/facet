"""The pillow-heif 1.6 double-transpose repair (fix_double_transposed_heif_thumbnails).

A sideways stored HEIF row must come back upright from the stored thumbnail
alone -- no original re-decode -- with its dimensions swapped back and its
subject columns cleared for --recompute-saliency, and a second run must find
nothing through the watermark.
"""

import io
import sqlite3

import pytest
from PIL import Image

pytest.importorskip("pillow_heif")

from db import init_database  # noqa: E402
from processing.scorer import (  # noqa: E402
    HEIF_DOUBLE_TRANSPOSE_WATERMARK_KEY,
    fix_double_transposed_heif_thumbnails,
)

ROTATED_HIF = str(__import__('pathlib').Path(__file__).parent / 'fixtures' / 'canon_eos_r8_hdr_pq_rotated.hif')
UPRIGHT_HIF = str(__import__('pathlib').Path(__file__).parent / 'fixtures' / 'canon_eos_r8_hdr_pq.hif')


def _sideways_blob():
    """What the broken decode stored: an upright portrait turned by the extra
    ROTATE_90 (counterclockwise), i.e. lying on its side. White on top, black
    below -- after the repair, top must be white again."""
    upright = Image.new('RGB', (60, 80))
    for y in range(80):
        for x in range(60):
            upright.putpixel((x, y), (255, 255, 255) if y < 40 else (0, 0, 0))
    sideways = upright.transpose(Image.Transpose.ROTATE_90)
    buf = io.BytesIO()
    sideways.save(buf, format='JPEG', quality=80)
    return buf.getvalue()


def _seed(db_path):
    init_database(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO photos (path, filename, scanned_at, thumbnail, image_width, image_height, "
        "subject_sharpness, subject_prominence, subject_placement, bg_separation, subject_bbox) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ROTATED_HIF, 'rotated.hif', '2026-01-01 10:00:00', _sideways_blob(), 800, 600,
         5.0, 5.0, 5.0, 5.0, '[0.1, 0.1, 0.9, 0.9]'))
    # An upright-in-file landscape frame: sideways in the size predicate but
    # nothing wrong with it -- it must be examined and left untouched.
    conn.execute(
        "INSERT INTO photos (path, filename, scanned_at, thumbnail, image_width, image_height, "
        "subject_prominence) VALUES (?, ?, ?, ?, ?, ?, 4.0)",
        (UPRIGHT_HIF, 'upright.hif', '2026-02-01 10:00:00', _sideways_blob(), 600, 400))
    # Already upright in the DB (repaired, or scanned correctly): excluded.
    conn.execute(
        "INSERT INTO photos (path, filename, scanned_at, thumbnail, image_width, image_height) "
        "VALUES ('/x/portrait.hif', 'portrait.hif', '2026-03-01 10:00:00', "
        "x'00', 600, 800)")
    conn.commit()
    conn.close()


def _row(db_path, path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT thumbnail, image_width, image_height, subject_sharpness, subject_prominence, "
            "subject_placement, bg_separation, subject_bbox FROM photos WHERE path = ?",
            (path,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def test_repairs_the_sideways_row_from_its_thumbnail_alone(tmp_path):
    db = str(tmp_path / 't.db')
    _seed(db)
    before = _row(db, ROTATED_HIF)
    assert before['image_width'] == 800 and before['image_height'] == 600

    assert fix_double_transposed_heif_thumbnails(db) == 1

    after = _row(db, ROTATED_HIF)
    img = Image.open(io.BytesIO(after['thumbnail']))
    assert img.size == (60, 80)  # portrait again, at the synthetic thumbnail's scale
    # The white half is on TOP once more: the repair is the exact inverse turn,
    # not just any quarter rotation.
    rgb = img.convert('RGB')
    top = rgb.getpixel((30, 10))
    bottom = rgb.getpixel((30, 70))
    assert top[0] > 200 and bottom[0] < 50
    assert (after['image_width'], after['image_height']) == (600, 800)
    # Subject metrics scored from the sideways frame are handed to --recompute-saliency.
    assert [after[k] for k in ('subject_sharpness', 'subject_prominence', 'subject_placement',
                               'bg_separation', 'subject_bbox')] == [None] * 5


def test_leaves_an_upright_in_file_landscape_untouched(tmp_path):
    db = str(tmp_path / 't.db')
    _seed(db)
    before = _row(db, UPRIGHT_HIF)
    fix_double_transposed_heif_thumbnails(db)
    after = _row(db, UPRIGHT_HIF)
    assert after['thumbnail'] == before['thumbnail']
    assert (after['image_width'], after['image_height']) == (600, 400)
    assert after['subject_prominence'] is not None  # untouched row keeps its scores


def test_watermark_makes_the_second_run_a_noop(tmp_path):
    db = str(tmp_path / 't.db')
    _seed(db)
    assert fix_double_transposed_heif_thumbnails(db) == 1

    conn = sqlite3.connect(db)
    watermark = conn.execute(
        "SELECT value FROM stats_cache WHERE key = ?", (HEIF_DOUBLE_TRANSPOSE_WATERMARK_KEY,)
    ).fetchone()[0]
    conn.close()
    assert watermark == '2026-02-01 10:00:00'  # the newest examined row, repaired or not

    # A second run re-examines nothing already passed and finds nothing new.
    assert fix_double_transposed_heif_thumbnails(db) == 0


def test_rows_scanned_after_the_watermark_are_still_examined(tmp_path):
    db = str(tmp_path / 't.db')
    _seed(db)
    assert fix_double_transposed_heif_thumbnails(db) == 1

    # A NEW sideways row, scanned after the watermark: a copy of the rotated
    # fixture under its own path.
    later = tmp_path / 'rotated2.hif'
    later.write_bytes(__import__('pathlib').Path(ROTATED_HIF).read_bytes())
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO photos (path, filename, scanned_at, thumbnail, image_width, image_height) "
        "VALUES (?, ?, '2026-04-01 10:00:00', ?, 800, 600)",
        (str(later), 'rotated2.hif', _sideways_blob()))
    conn.commit()
    conn.close()

    assert fix_double_transposed_heif_thumbnails(db) == 1
    after = _row(db, str(later))
    assert (after['image_width'], after['image_height']) == (600, 800)


def test_faces_turn_with_the_thumbnail_and_stale_declines_go(tmp_path):
    """An upright face box (100, 200)-(200, 300) in the 600x800 frame was stored
    at (200, 400)-(300, 500) in the 800x600 sideways one; the repair must hand
    it back in upright coordinates, with its landmarks, and drop iqa_declined."""
    import numpy as np

    db = str(tmp_path / 't.db')
    _seed(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO faces (photo_path, face_index, embedding, bbox_x1, bbox_y1, bbox_x2, bbox_y2, "
        "landmark_2d_106) VALUES (?, 0, x'00', 200, 400, 300, 500, ?)",
        (ROTATED_HIF, np.array([[250.0, 450.0]] * 106, dtype=np.float32).tobytes()))
    conn.execute("INSERT INTO iqa_declined (photo_path, model, scan_fingerprint) VALUES (?, 'topiq_nr_face', 'x')",
                 (ROTATED_HIF,))
    conn.commit()
    conn.close()

    assert fix_double_transposed_heif_thumbnails(db) == 1

    conn = sqlite3.connect(db)
    box = conn.execute("SELECT bbox_x1, bbox_y1, bbox_x2, bbox_y2 FROM faces WHERE photo_path = ?",
                       (ROTATED_HIF,)).fetchone()
    landmarks = conn.execute("SELECT landmark_2d_106 FROM faces WHERE photo_path = ?",
                             (ROTATED_HIF,)).fetchone()[0]
    declined = conn.execute("SELECT COUNT(*) FROM iqa_declined WHERE photo_path = ?",
                            (ROTATED_HIF,)).fetchone()[0]
    conn.close()
    assert box == (100, 200, 200, 300)
    assert np.frombuffer(landmarks, dtype=np.float32).reshape(-1, 2)[0].tolist() == [150.0, 250.0]
    assert declined == 0


def test_an_unreadable_file_holds_the_watermark_for_the_next_run(tmp_path):
    """A row whose file cannot be read (an offline volume) must be examined
    again later, not passed by the watermark for good."""
    db = str(tmp_path / 't.db')
    _seed(db)
    offline = tmp_path / 'offline.hif'
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO photos (path, filename, scanned_at, thumbnail, image_width, image_height) "
        "VALUES (?, 'offline.hif', '2026-01-15 10:00:00', ?, 800, 600)",
        (str(offline), _sideways_blob()))
    conn.commit()
    conn.close()

    assert fix_double_transposed_heif_thumbnails(db) == 1  # the readable rotated row only

    offline.write_bytes(__import__('pathlib').Path(ROTATED_HIF).read_bytes())
    assert fix_double_transposed_heif_thumbnails(db) == 1
    after = _row(db, str(offline))
    assert (after['image_width'], after['image_height']) == (600, 800)
