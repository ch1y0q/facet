"""scripts/rewrite_db_paths.py: move a Docker-scanned library to Windows paths."""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from db.schema import init_database

SCRIPT = Path(__file__).resolve().parent.parent / 'scripts' / 'rewrite_db_paths.py'
SRC = '/data/photos'
DST = r'\\NAS\Photos'


def _run(db, *extra):
    return subprocess.run([sys.executable, str(SCRIPT), str(db), SRC, DST, *extra],
                          capture_output=True, text=True, check=True)


@pytest.fixture
def library(tmp_path):
    db = tmp_path / 'library.db'
    init_database(str(db))
    with sqlite3.connect(db) as conn:
        conn.executemany('INSERT INTO photos (path, filename) VALUES (?, ?)', [
            ('/data/photos/2024/trip/a.jpg', 'a.jpg'),
            ('/data/photos/b.jpg', 'b.jpg'),
            ('/data/photos-old/c.jpg', 'c.jpg'),  # shares the prefix text, not the folder
            ('/elsewhere/d.jpg', 'd.jpg'),
        ])
        conn.execute("INSERT INTO faces (photo_path, face_index, embedding) VALUES (?, 0, x'00')",
                     ('/data/photos/2024/trip/a.jpg',))
        album = conn.execute(
            'INSERT INTO albums (name, cover_photo_path, smart_filter_json) VALUES (?, ?, ?)',
            ('Trip', '/data/photos/b.jpg',
             json.dumps({'path_prefix': '/data/photos/2024', 'tags': ['beach']}))).lastrowid
        conn.execute('INSERT INTO album_photos (album_id, photo_path) VALUES (?, ?)',
                     (album, '/data/photos/2024/trip/a.jpg'))
        conn.execute('INSERT INTO scan_runs (args_json) VALUES (?)',
                     (json.dumps({'directories': ['/data/photos/2024'], 'force': False}),))
    return db


def _paths(db, sql):
    with sqlite3.connect(db) as conn:
        return [row[0] for row in conn.execute(sql)]


def test_rewrites_every_path_column_under_the_prefix_only(library):
    out = _run(library).stdout
    assert sorted(_paths(library, 'SELECT path FROM photos')) == sorted([
        r'\\NAS\Photos\2024\trip\a.jpg',
        r'\\NAS\Photos\b.jpg',
        '/data/photos-old/c.jpg',
        '/elsewhere/d.jpg',
    ])
    assert _paths(library, 'SELECT photo_path FROM faces') == [r'\\NAS\Photos\2024\trip\a.jpg']
    assert _paths(library, 'SELECT photo_path FROM album_photos') == [r'\\NAS\Photos\2024\trip\a.jpg']
    assert _paths(library, 'SELECT cover_photo_path FROM albums') == [r'\\NAS\Photos\b.jpg']
    assert 'integrity: ok' in out
    assert '| foreign keys: 0 violations' in out
    assert out.rstrip().endswith('photos left on old prefix: 0')


def test_rewrites_paths_inside_json_columns(library):
    _run(library)
    smart = json.loads(_paths(library, 'SELECT smart_filter_json FROM albums')[0])
    assert smart == {'path_prefix': r'\\NAS\Photos\2024', 'tags': ['beach']}
    args = json.loads(_paths(library, 'SELECT args_json FROM scan_runs')[0])
    assert args == {'directories': [r'\\NAS\Photos\2024'], 'force': False}


def test_rebuilds_fts_on_the_new_paths(library):
    _run(library)
    with sqlite3.connect(library) as conn:
        indexed = {row[0] for row in conn.execute('SELECT path FROM photos_fts')}
    assert r'\\NAS\Photos\b.jpg' in indexed
    assert '/data/photos/b.jpg' not in indexed


def test_second_run_changes_nothing(library):
    _run(library)
    before = _paths(library, 'SELECT path FROM photos ORDER BY rowid')
    out = _run(library).stdout
    assert _paths(library, 'SELECT path FROM photos ORDER BY rowid') == before
    assert 'photos.path' not in out


def test_separator_can_stay_forward_slash(library):
    _run(library, '--sep', '/')
    assert r'\\NAS\Photos/2024/trip/a.jpg' in _paths(library, 'SELECT path FROM photos')
