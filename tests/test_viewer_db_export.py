"""Incremental viewer-DB export tests.

Covers review findings F30 (a re-export must not wipe ratings entered on a
viewer-only deployment) and F31 (faces extracted after the first export must
reach already-exported photos).
"""

import sqlite3
from contextlib import contextmanager
from io import BytesIO

import pytest
from PIL import Image

from db.maintenance import export_viewer_db
from db.schema import init_database
from utils.histogram import HISTOGRAM_BLOB_SIZE, pack_histogram

_A = '/photos/a.jpg'
_B = '/photos/b.jpg'
_USER = 'alice'


def _thumb_bytes(color=(120, 60, 30)):
    img = Image.new('RGB', (640, 640), color)
    buf = BytesIO()
    img.save(buf, format='JPEG', quality=85)
    return buf.getvalue()


def _make_source_db(path):
    init_database(path)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    for p in (_A, _B):
        conn.execute(
            "INSERT INTO photos (path, filename, thumbnail, star_rating, is_favorite, is_rejected) "
            "VALUES (?, ?, ?, 0, 0, 0)",
            (p, p.rsplit('/', 1)[-1], _thumb_bytes()),
        )
    conn.commit()
    conn.close()


def _spike_histogram(index):
    counts = [0.0] * 256
    counts[index] = 1000.0
    return pack_histogram(counts, counts, counts, counts)


def _manual_face(conn, path, person_id, key):
    return conn.execute(
        "INSERT INTO faces(photo_path,face_index,embedding,person_id,is_manual,manual_key,"
        "bbox_x1,bbox_y1,bbox_x2,bbox_y2,manual_width,manual_height,manual_source,face_thumbnail) "
        "VALUES (?,-1,X'',?,1,?,10,10,30,30,100,100,'source',?)",
        (path, person_id, key, _thumb_bytes('blue'))).lastrowid


def test_incremental_manual_faces_preserve_independent_colliding_people(tmp_path):
    src, out = str(tmp_path / 'source.db'), str(tmp_path / 'viewer.db')
    _make_source_db(src)
    export_viewer_db(src, out, verbose=False)
    with sqlite3.connect(out) as conn:
        viewer_pid = conn.execute("INSERT INTO persons(name) VALUES ('Viewer Alice')").lastrowid
        viewer_key = conn.execute('SELECT person_key FROM persons WHERE id=?', (viewer_pid,)).fetchone()[0]
        viewer_fid = _manual_face(conn, _A, viewer_pid, 'viewer-manual')
    with sqlite3.connect(src) as conn:
        source_pid = conn.execute("INSERT INTO persons(name) VALUES ('Scanner Bob')").lastrowid
        assert source_pid == viewer_pid
        source_key = conn.execute('SELECT person_key FROM persons WHERE id=?', (source_pid,)).fetchone()[0]
        assert source_key != viewer_key
        _manual_face(conn, _B, source_pid, 'source-manual')
        conn.execute("INSERT INTO faces(photo_path,face_index,embedding,person_id) VALUES (?,0,X'01',?)", (_A, source_pid))
    for _ in range(2):
        export_viewer_db(src, out, verbose=False)
        with sqlite3.connect(out) as conn:
            rows = conn.execute('SELECT f.manual_key,p.name,p.person_key FROM faces f JOIN persons p ON f.person_id=p.id WHERE f.is_manual=1 ORDER BY f.manual_key').fetchall()
            assert rows == [('source-manual', 'Scanner Bob', source_key), ('viewer-manual', 'Viewer Alice', viewer_key)]
            assert conn.execute('SELECT id FROM faces WHERE manual_key=?', ('viewer-manual',)).fetchone() == (viewer_fid,)
            assert conn.execute('SELECT p.name FROM faces f JOIN persons p ON f.person_id=p.id WHERE f.photo_path=? AND f.is_manual=0', (_A,)).fetchone() == ('Scanner Bob',)
            assert conn.execute('SELECT COUNT(*) FROM faces WHERE is_manual=1').fetchone() == (2,)
    with sqlite3.connect(src) as conn:
        conn.execute('DELETE FROM photos WHERE path=?', (_A,))
    export_viewer_db(src, out, verbose=False)
    with sqlite3.connect(out) as conn:
        assert conn.execute('SELECT 1 FROM faces WHERE manual_key=?', ('viewer-manual',)).fetchone() is None
        assert conn.execute('SELECT face_count,face_thumbnail,representative_face_id FROM persons WHERE person_key=?',
                            (viewer_key,)).fetchone() == (0, None, None)


def test_manual_api_deletion_wins_over_stale_exports_in_both_directions(tmp_path, edition_client, monkeypatch):
    from api.routers import manual_faces as router
    src, out = str(tmp_path / 'source.db'), str(tmp_path / 'viewer.db')
    _make_source_db(src)
    with sqlite3.connect(src) as conn:
        pid = conn.execute("INSERT INTO persons(name,face_count) VALUES ('Deleted Person',1)").lastrowid
        _manual_face(conn, _A, pid, 'deleted-source-mark')
    export_viewer_db(src, out, verbose=False)
    @contextmanager
    def viewer_db():
        conn = sqlite3.connect(out)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            yield conn
        finally:
            conn.close()
    monkeypatch.setattr(router, 'get_db', viewer_db)
    region = edition_client.get('/api/photo/manual-faces', params={'path': _A}).json()['regions'][0]
    assert edition_client.delete(f"/api/photo/manual-faces/{region['id']}", params={'path': _A}).status_code == 200
    # Scanner still contains the source-origin mark. Re-export must not revive it.
    for _ in range(2):
        export_viewer_db(src, out, verbose=False)
        with sqlite3.connect(out) as conn:
            assert conn.execute("SELECT 1 FROM faces WHERE manual_key='deleted-source-mark'").fetchone() is None
            assert conn.execute("SELECT face_count,face_thumbnail FROM persons WHERE name='Deleted Person'").fetchone() == (0, None)
    # The deletion is now the source of a reverse sync into an older active copy.
    export_viewer_db(out, src, verbose=False)
    for source, destination in ((src, out), (out, src)):
        export_viewer_db(source, destination, verbose=False)
        with sqlite3.connect(destination) as conn:
            assert conn.execute("SELECT 1 FROM faces WHERE manual_key='deleted-source-mark'").fetchone() is None
            assert conn.execute("SELECT manual_key FROM manual_face_deletions").fetchall() == [('deleted-source-mark',)]


def test_ambiguous_legacy_manual_person_export_fails_before_changes(tmp_path):
    src, out = str(tmp_path / 'source.db'), str(tmp_path / 'viewer.db')
    _make_source_db(src)
    with sqlite3.connect(src) as conn:
        conn.execute("INSERT INTO persons(id,name,person_key) VALUES (1,'Original','legacy:1')")
    export_viewer_db(src, out, verbose=False)
    with sqlite3.connect(out) as conn:
        conn.execute("UPDATE persons SET name='Different' WHERE id=1")
        _manual_face(conn, _A, 1, 'legacy-manual')
        conn.execute("UPDATE photos SET caption='viewer state' WHERE path=?", (_A,))
    with sqlite3.connect(src) as conn:
        conn.execute("UPDATE photos SET caption='source state'")
    with pytest.raises(ValueError, match='legacy.*identity'):
        export_viewer_db(src, out, verbose=False)
    with sqlite3.connect(out) as conn:
        assert conn.execute('SELECT caption FROM photos WHERE path=?', (_A,)).fetchone() == ('viewer state',)


def test_source_detection_overlapping_viewer_manual_is_not_duplicated(tmp_path):
    from db.manual_faces import source_identity
    src, out = str(tmp_path / 'source.db'), str(tmp_path / 'viewer.db')
    image = str(tmp_path / 'photo.jpg')
    Image.new('RGB', (100, 100), 'red').save(image)
    init_database(src)
    with sqlite3.connect(src) as conn:
        conn.execute('INSERT INTO photos(path,filename,image_width,image_height) VALUES (?,?,100,100)', (image, 'photo.jpg'))
    export_viewer_db(src, out, verbose=False)
    with sqlite3.connect(out) as conn:
        pid = conn.execute("INSERT INTO persons(name) VALUES ('Manual person')").lastrowid
        _manual_face(conn, image, pid, 'manual-overlap')
        conn.execute('UPDATE faces SET manual_source=? WHERE manual_key=?', (source_identity(image), 'manual-overlap'))
    with sqlite3.connect(src) as conn:
        pid = conn.execute("INSERT INTO persons(name) VALUES ('Detector person')").lastrowid
        conn.execute("INSERT INTO faces(photo_path,face_index,embedding,person_id,bbox_x1,bbox_y1,bbox_x2,bbox_y2) "
                     "VALUES (?,0,X'01',?,10,10,30,30)", (image, pid))
    for _ in range(2):
        export_viewer_db(src, out, verbose=False)
        with sqlite3.connect(out) as conn:
            assert conn.execute('SELECT COUNT(*) FROM faces WHERE photo_path=?', (image,)).fetchone() == (1,)
            assert conn.execute('SELECT p.name FROM faces f JOIN persons p ON f.person_id=p.id WHERE f.photo_path=?', (image,)).fetchone() == ('Manual person',)


def test_full_export_carries_manual_provenance_and_person_identity(tmp_path):
    src, out = str(tmp_path / 'source.db'), str(tmp_path / 'viewer.db')
    _make_source_db(src)
    with sqlite3.connect(src) as conn:
        pid = conn.execute("INSERT INTO persons(name) VALUES ('Source Manual')").lastrowid
        key = conn.execute('SELECT person_key FROM persons WHERE id=?', (pid,)).fetchone()[0]
        _manual_face(conn, _A, pid, 'full-manual')
    export_viewer_db(src, out, force=True, verbose=False)
    with sqlite3.connect(out) as conn:
        assert conn.execute('SELECT f.manual_key,f.is_manual,length(f.embedding),p.person_key FROM faces f '
                            'JOIN persons p ON f.person_id=p.id').fetchone() == ('full-manual', 1, 0, key)


def test_full_export_deletion_record_overrules_stale_active_row(tmp_path):
    src, out = str(tmp_path / 'source.db'), str(tmp_path / 'viewer.db')
    _make_source_db(src)
    with sqlite3.connect(src) as conn:
        pid = conn.execute("INSERT INTO persons(name,face_count,face_thumbnail) VALUES ('Deleted',1,?)", (_thumb_bytes('blue'),)).lastrowid
        _manual_face(conn, _A, pid, 'stale-active')
        conn.execute("INSERT INTO manual_face_deletions VALUES ('stale-active')")
    export_viewer_db(src, out, force=True, verbose=False)
    with sqlite3.connect(out) as conn:
        assert conn.execute("SELECT 1 FROM faces WHERE manual_key='stale-active'").fetchone() is None
        assert conn.execute("SELECT face_count,face_thumbnail FROM persons WHERE name='Deleted'").fetchone() == (0, None)


def test_full_export_keeps_the_histogram_the_viewer_draws(tmp_path):
    """The viewer's RGB histogram widget reads photos.histogram_data through
    /api/photo/histogram, so the export must stop stripping it — a stripped
    column silently downgrades every NAS deployment to thumbnail sampling."""
    src = str(tmp_path / 'scan.db')
    out = str(tmp_path / 'viewer.db')
    _make_source_db(src)
    sconn = sqlite3.connect(src)
    sconn.execute("UPDATE photos SET histogram_data = ?, clip_embedding = ?",
                  (sqlite3.Binary(_spike_histogram(42)), sqlite3.Binary(b'\x01' * 128)))
    sconn.commit()
    sconn.close()

    export_viewer_db(src, out, thumbnail_size=320, verbose=False, force=True)

    vconn = sqlite3.connect(out)
    hist, clip = vconn.execute(
        "SELECT histogram_data, clip_embedding FROM photos WHERE path = ?", (_A,)
    ).fetchone()
    vconn.close()
    assert len(hist) == HISTOGRAM_BLOB_SIZE
    assert clip is None


def test_incremental_export_carries_the_histogram_to_new_and_existing_photos(tmp_path):
    src = str(tmp_path / 'scan.db')
    out = str(tmp_path / 'viewer.db')
    _make_source_db(src)
    export_viewer_db(src, out, thumbnail_size=320, verbose=False)

    sconn = sqlite3.connect(src)
    sconn.execute("UPDATE photos SET histogram_data = ? WHERE path = ?",
                  (sqlite3.Binary(_spike_histogram(7)), _A))
    sconn.execute(
        "INSERT INTO photos (path, filename, thumbnail, histogram_data) VALUES (?, ?, ?, ?)",
        ('/photos/c.jpg', 'c.jpg', _thumb_bytes(), sqlite3.Binary(_spike_histogram(9))),
    )
    sconn.commit()
    sconn.close()

    export_viewer_db(src, out, thumbnail_size=320, verbose=False)

    vconn = sqlite3.connect(out)
    existing = vconn.execute(
        "SELECT histogram_data FROM photos WHERE path = ?", (_A,)).fetchone()[0]
    added = vconn.execute(
        "SELECT histogram_data FROM photos WHERE path = ?", ('/photos/c.jpg',)).fetchone()[0]
    vconn.close()
    assert len(existing) == HISTOGRAM_BLOB_SIZE
    assert len(added) == HISTOGRAM_BLOB_SIZE


def test_incremental_export_preserves_viewer_ratings(tmp_path):
    src = str(tmp_path / 'scan.db')
    out = str(tmp_path / 'viewer.db')
    _make_source_db(src)
    export_viewer_db(src, out, thumbnail_size=320, verbose=False)

    vconn = sqlite3.connect(out)
    vconn.execute(
        "UPDATE photos SET star_rating = 5, is_favorite = 1, is_rejected = 1 WHERE path = ?", (_A,)
    )
    vconn.commit()
    vconn.close()

    export_viewer_db(src, out, thumbnail_size=320, verbose=False)

    vconn = sqlite3.connect(out)
    star, fav, rej = vconn.execute(
        "SELECT star_rating, is_favorite, is_rejected FROM photos WHERE path = ?", (_A,)
    ).fetchone()
    vconn.close()
    assert star == 5
    assert fav == 1
    assert rej == 1


def test_incremental_export_propagates_scan_ratings_when_viewer_unrated(tmp_path):
    src = str(tmp_path / 'scan.db')
    out = str(tmp_path / 'viewer.db')
    _make_source_db(src)
    export_viewer_db(src, out, thumbnail_size=320, verbose=False)

    sconn = sqlite3.connect(src)
    sconn.execute("UPDATE photos SET star_rating = 4 WHERE path = ?", (_B,))
    sconn.commit()
    sconn.close()

    export_viewer_db(src, out, thumbnail_size=320, verbose=False)

    vconn = sqlite3.connect(out)
    star = vconn.execute("SELECT star_rating FROM photos WHERE path = ?", (_B,)).fetchone()[0]
    vconn.close()
    assert star == 4


def test_incremental_export_syncs_faces_for_existing_photos(tmp_path):
    src = str(tmp_path / 'scan.db')
    out = str(tmp_path / 'viewer.db')
    _make_source_db(src)
    export_viewer_db(src, out, thumbnail_size=320, verbose=False)

    sconn = sqlite3.connect(src)
    sconn.execute(
        "INSERT INTO faces (photo_path, face_index, embedding, face_thumbnail) VALUES (?, 0, ?, ?)",
        (_A, sqlite3.Binary(b'\x00' * 512), _thumb_bytes()),
    )
    sconn.commit()
    sconn.close()

    export_viewer_db(src, out, thumbnail_size=320, verbose=False)

    vconn = sqlite3.connect(out)
    n = vconn.execute("SELECT COUNT(*) FROM faces WHERE photo_path = ?", (_A,)).fetchone()[0]
    vconn.close()
    assert n == 1


def test_export_includes_user_preferences(tmp_path):
    src = str(tmp_path / 'scan.db')
    out = str(tmp_path / 'viewer.db')
    _make_source_db(src)

    sconn = sqlite3.connect(src)
    sconn.execute(
        "INSERT INTO user_preferences (user_id, photo_path, star_rating, is_favorite, is_rejected) "
        "VALUES (?, ?, 5, 1, 0)",
        (_USER, _A),
    )
    sconn.commit()
    sconn.close()

    export_viewer_db(src, out, thumbnail_size=320, verbose=False)

    vconn = sqlite3.connect(out)
    row = vconn.execute(
        "SELECT star_rating, is_favorite, is_rejected FROM user_preferences "
        "WHERE user_id = ? AND photo_path = ?",
        (_USER, _A),
    ).fetchone()
    vconn.close()
    assert row == (5, 1, 0)


def test_incremental_export_propagates_user_preferences_when_viewer_unrated(tmp_path):
    src = str(tmp_path / 'scan.db')
    out = str(tmp_path / 'viewer.db')
    _make_source_db(src)
    export_viewer_db(src, out, thumbnail_size=320, verbose=False)

    sconn = sqlite3.connect(src)
    sconn.execute(
        "INSERT INTO user_preferences (user_id, photo_path, star_rating) VALUES (?, ?, 4)",
        (_USER, _B),
    )
    sconn.commit()
    sconn.close()

    export_viewer_db(src, out, thumbnail_size=320, verbose=False)

    vconn = sqlite3.connect(out)
    star = vconn.execute(
        "SELECT star_rating FROM user_preferences WHERE user_id = ? AND photo_path = ?",
        (_USER, _B),
    ).fetchone()[0]
    vconn.close()
    assert star == 4


def test_incremental_export_preserves_viewer_user_preferences(tmp_path):
    src = str(tmp_path / 'scan.db')
    out = str(tmp_path / 'viewer.db')
    _make_source_db(src)

    sconn = sqlite3.connect(src)
    sconn.execute(
        "INSERT INTO user_preferences (user_id, photo_path, star_rating) VALUES (?, ?, 3)",
        (_USER, _A),
    )
    sconn.commit()
    sconn.close()
    export_viewer_db(src, out, thumbnail_size=320, verbose=False)

    vconn = sqlite3.connect(out)
    vconn.execute(
        "UPDATE user_preferences SET star_rating = 5, is_favorite = 1 "
        "WHERE user_id = ? AND photo_path = ?",
        (_USER, _A),
    )
    vconn.commit()
    vconn.close()

    export_viewer_db(src, out, thumbnail_size=320, verbose=False)

    vconn = sqlite3.connect(out)
    star, fav = vconn.execute(
        "SELECT star_rating, is_favorite FROM user_preferences "
        "WHERE user_id = ? AND photo_path = ?",
        (_USER, _A),
    ).fetchone()
    vconn.close()
    assert star == 5
    assert fav == 1


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
