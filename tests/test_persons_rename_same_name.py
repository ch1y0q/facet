"""POST /api/persons/{id}/rename reports other persons of the same name.

Clustering often splits one person over several clusters; naming the second one
"peter salem" when "Peter Salem" exists should let the viewer offer a merge. The
rename itself never merges (two people may share a name), it only reports.

Real temp-DB pattern from tests/test_persons_split_hide.py: the session DB is
shared, so every test cleans up its own rows.
"""

import os
import sqlite3

PREFIX = "/tmp/rename_same_name/"


def _db():
    conn = sqlite3.connect(os.environ["DB_PATH"])
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _seed(persons):
    """``persons``: ``[(id, name, face_count, is_hidden)]``, one face each."""
    conn = _db()
    for pid, name, face_count, is_hidden in persons:
        conn.execute("DELETE FROM persons WHERE id = ?", (pid,))
        conn.execute(
            "INSERT INTO persons(id, name, face_count, is_hidden) VALUES (?, ?, ?, ?)",
            (pid, name, face_count, is_hidden),
        )
        path = f"{PREFIX}{pid}.jpg"
        conn.execute("INSERT OR IGNORE INTO photos(path) VALUES (?)", (path,))
        conn.execute(
            "INSERT INTO faces(photo_path, face_index, embedding, person_id) VALUES (?, 0, ?, ?)",
            (path, sqlite3.Binary(b"\x00\x00\x00\x00"), pid),
        )
    conn.commit()
    conn.close()


def _cleanup(ids):
    conn = _db()
    conn.execute("DELETE FROM faces WHERE photo_path LIKE ?", (PREFIX + "%",))
    conn.execute("DELETE FROM photos WHERE path LIKE ?", (PREFIX + "%",))
    conn.execute(f"DELETE FROM persons WHERE id IN ({','.join('?' * len(ids))})", ids)
    conn.commit()
    conn.close()


def test_rename_reports_same_name_ignoring_case_and_spaces(edition_client):
    ids = [99101, 99102, 99103, 99104]
    _seed([
        (99101, None, 3, 0),
        (99102, "Peter Salem", 34, 0),
        (99103, "  PETER salem ", 77, 0),
        (99104, "Peter Salemi", 50, 0),
    ])
    try:
        resp = edition_client.post("/api/persons/99101/rename", json={"name": "peter salem"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "peter salem"
        # Largest first; the near-miss "Peter Salemi" is not reported.
        assert body["same_name_persons"] == [
            {"id": 99103, "name": "  PETER salem ", "face_count": 77},
            {"id": 99102, "name": "Peter Salem", "face_count": 34},
        ]
        conn = _db()
        names = dict(conn.execute(
            "SELECT id, name FROM persons WHERE id IN (99101, 99102, 99103)").fetchall())
        conn.close()
        # Reporting only: nothing merged, nothing else renamed.
        assert names == {99101: "peter salem", 99102: "Peter Salem", 99103: "  PETER salem "}
    finally:
        _cleanup(ids)


def test_rename_skips_hidden_same_name(edition_client):
    ids = [99111, 99112]
    _seed([(99111, None, 3, 0), (99112, "Anna", 9, 1)])
    try:
        body = edition_client.post("/api/persons/99111/rename", json={"name": "anna"}).json()
        assert body["same_name_persons"] == []
    finally:
        _cleanup(ids)


def test_rename_folds_non_ascii_case(edition_client):
    ids = [99121, 99122]
    _seed([(99121, None, 3, 0), (99122, "Élodie", 5, 0)])
    try:
        body = edition_client.post("/api/persons/99121/rename", json={"name": "élodie"}).json()
        assert [p["id"] for p in body["same_name_persons"]] == [99122]
    finally:
        _cleanup(ids)


def test_clearing_a_name_reports_nothing(edition_client):
    ids = [99131, 99132]
    _seed([(99131, "Bob", 3, 0), (99132, None, 5, 0)])
    try:
        body = edition_client.post("/api/persons/99131/rename", json={"name": ""}).json()
        assert body["same_name_persons"] == []
    finally:
        _cleanup(ids)
