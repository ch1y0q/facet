"""POST /api/photos/by_paths: an explicit path list through the gallery's visibility and filters."""
import sqlite3

import pytest

from api.models.gallery import gallery_filter_keys
from tests.conftest import _TEST_DB_FILE

PFX = "/bypaths/"


def _row(name, aggregate, category="default", **extra):
    return {"path": PFX + name, "filename": name, "aggregate": aggregate, "category": category,
            "date_taken": "2026:02:01 10:00:00", **extra}


@pytest.fixture()
def rows(seed_photos_prefix):
    return seed_photos_prefix(PFX, [
        _row("low.jpg", 2.0),
        _row("high.jpg", 9.5, "portrait"),
        _row("mid.jpg", 5.0, "landscape"),
        _row("lead.jpg", 6.0, is_burst_lead=1, burst_group_id=900001),
        _row("member.jpg", 4.0, is_burst_lead=0, burst_group_id=900001),
    ])


def _post(client, paths, filters=None):
    body = {"paths": [PFX + p if not p.startswith("/") else p for p in paths]}
    if filters is not None:
        body["filters"] = filters
    return client.post("/api/photos/by_paths", json=body)


def test_rows_come_back_in_the_requested_order_not_the_sort_order(client, rows):
    data = _post(client, ["low.jpg", "high.jpg", "mid.jpg"]).json()
    assert [p["path"] for p in data["photos"]] == [PFX + n for n in ("low.jpg", "high.jpg", "mid.jpg")]
    assert data["total"] == 3 and data["missing"] == []


def test_unknown_path_is_missing_and_has_no_row(client, rows):
    data = _post(client, ["high.jpg", "nope.jpg"]).json()
    assert [p["path"] for p in data["photos"]] == [PFX + "high.jpg"]
    assert data["missing"] == [PFX + "nope.jpg"]


def test_viewer_default_type_does_not_narrow_an_explicit_list(client, rows, monkeypatch):
    from api.routers import gallery
    monkeypatch.setitem(gallery.VIEWER_CONFIG["defaults"], "type", "portrait")
    data = _post(client, ["low.jpg", "high.jpg"]).json()
    assert {p["path"] for p in data["photos"]} == {PFX + "low.jpg", PFX + "high.jpg"}


def test_an_explicit_type_filter_is_still_honoured(client, rows):
    data = _post(client, ["low.jpg", "high.jpg"], {"type": "portrait"}).json()
    assert [p["path"] for p in data["photos"]] == [PFX + "high.jpg"]
    assert data["missing"] == [PFX + "low.jpg"]


def test_hidden_burst_member_is_returned_though_the_gallery_hides_it(client, rows):
    listing = client.get("/api/photos", params={"hide_bursts": "1", "path_prefix": PFX, "per_page": 100}).json()
    shown = {p["path"] for p in listing["photos"]}
    assert PFX + "lead.jpg" in shown and PFX + "member.jpg" not in shown
    data = _post(client, ["member.jpg"]).json()
    assert [p["path"] for p in data["photos"]] == [PFX + "member.jpg"]


def test_unknown_filter_key_is_422(client, rows):
    assert _post(client, ["low.jpg"], {"drop_table": "1"}).status_code == 422


def test_501_paths_is_422_and_empty_is_422(client, rows):
    assert client.post("/api/photos/by_paths", json={"paths": [f"/x/{i}" for i in range(501)]}).status_code == 422
    assert client.post("/api/photos/by_paths", json={"paths": []}).status_code == 422


def test_a_metric_filter_moves_a_low_photo_to_missing(client, rows):
    data = _post(client, ["low.jpg", "high.jpg"], {"min_score": "9"}).json()
    assert [p["path"] for p in data["photos"]] == [PFX + "high.jpg"]
    assert data["missing"] == [PFX + "low.jpg"]


def test_a_fractional_json_number_filter_is_accepted_like_its_string_form(client, rows):
    as_number = _post(client, ["low.jpg", "high.jpg"], {"min_score": 9.5})
    assert as_number.status_code == 200, as_number.text
    assert as_number.json() == _post(client, ["low.jpg", "high.jpg"], {"min_score": "9.5"}).json()
    assert [p["path"] for p in as_number.json()["photos"]] == [PFX + "high.jpg"]


def test_paging_and_sort_keys_are_dropped_not_rejected(client, rows):
    data = _post(client, ["low.jpg", "high.jpg"], {"page": 7, "per_page": 1, "sort": "aggregate", "dir": "ASC"}).json()
    assert [p["path"] for p in data["photos"]] == [PFX + "low.jpg", PFX + "high.jpg"]


def test_person_alias_filters(client, rows):
    conn = sqlite3.connect(_TEST_DB_FILE.name)
    try:
        conn.execute("INSERT INTO persons(id, name, auto_clustered, face_count) VALUES (987001, 'Ann', 0, 1)")
        conn.execute("INSERT INTO faces(photo_path, face_index, embedding, person_id) VALUES (?, 0, ?, 987001)", (PFX + "mid.jpg", b"\x00" * 8))
        conn.commit()
        data = _post(client, ["low.jpg", "mid.jpg"], {"person_id": 987001}).json()
        assert [p["path"] for p in data["photos"]] == [PFX + "mid.jpg"]
        assert data["missing"] == [PFX + "low.jpg"]
    finally:
        conn.execute("DELETE FROM faces WHERE person_id = 987001")
        conn.execute("DELETE FROM persons WHERE id = 987001")
        conn.commit()
        conn.close()


def test_filter_key_helper_carries_the_client_aliases():
    keys = gallery_filter_keys()
    assert {"person_id", "sort_direction", "min_score", "type", "hide_bursts"} <= keys
