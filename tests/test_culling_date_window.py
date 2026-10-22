"""ISO ``date_from`` / ``date_to`` on the culling routes (GET /api/culling-groups,
POST /api/culling/auto, GET /api/culling/suggest_profile).

``date_taken`` is stored as EXIF ``YYYY:MM:DD HH:MM:SS`` and compared
lexicographically, so an ISO window used to match nothing (or, for the
suggestion route, answer 422). Every form the helper accepts must now give the
same answer as the EXIF form. Auth goes through the conftest fixtures.
"""

import pytest

from fastapi import HTTPException

PREFIX = "/cull-date-window/"
GID = 71717


def _rows():
    def row(name, second, aggregate):
        return {"path": PREFIX + name, "filename": name, "date_taken": f"1997:02:02 10:00:{second:02d}",
                "aggregate": aggregate, "aesthetic": aggregate, "tech_sharpness": aggregate,
                "burst_group_id": GID, "is_burst_lead": int(second == 1), "category": "portrait"}
    return [row("a.jpg", 1, 9.0), row("b.jpg", 2, 6.0), row("c.jpg", 3, 3.0)]


@pytest.fixture()
def seeded(seed_photos_prefix):
    from api.routers.burst_culling import _invalidate_culling_groups_cache
    seed_photos_prefix(PREFIX, _rows())
    _invalidate_culling_groups_cache()
    yield
    _invalidate_culling_groups_cache()


def _paths(resp):
    assert resp.status_code == 200, resp.text
    return sorted(p["path"] for g in resp.json()["groups"] for p in g["photos"]
                  if p["path"].startswith(PREFIX))


EXIF = "date_from=1997:02:02 00:00:00&date_to=1997:02:02 23:59:59"


class TestWindowOr400:
    @staticmethod
    def _fn():
        from api.db_helpers import window_or_400
        return window_or_400

    def test_iso_date_only_to_covers_the_whole_day(self):
        assert self._fn()("1997-02-02", "1997-02-02") == ("1997:02:02 00:00:00", "1997:02:02 23:59:59")

    def test_none_passes_through_and_exif_is_idempotent(self):
        assert self._fn()(None, None) == (None, None)
        assert self._fn()("1997:02:02 10:00:00", "1997:02:02 11:00:00") == (
            "1997:02:02 10:00:00", "1997:02:02 11:00:00")

    def test_garbage_is_a_400(self):
        with pytest.raises(HTTPException) as ex:
            self._fn()("garbage", None)
        assert ex.value.status_code == 400


class TestCullingGroupsIsoWindow:
    def test_iso_date_matches_the_exif_form(self, seeded, edition_client):
        exif = _paths(edition_client.get(f"/api/culling-groups?group_by=all&{EXIF}"))
        assert len(exif) == 3
        iso = _paths(edition_client.get(
            "/api/culling-groups?group_by=all&date_from=1997-02-02&date_to=1997-02-02"))
        assert iso == exif

    def test_iso_datetime_and_midday_window(self, seeded, edition_client):
        resp = edition_client.get(
            "/api/culling-groups?group_by=all&date_from=1997-02-02T10:00:00&date_to=1997-02-02 10:00:02")
        assert len(_paths(resp)) == 3

    def test_garbage_is_a_400(self, seeded, edition_client):
        assert edition_client.get("/api/culling-groups?date_from=garbage").status_code == 400


class TestAutoCullIsoWindow:
    def _plan(self, client, **window):
        resp = client.post("/api/culling/auto", json={"group_by": "burst", "strictness": 50, **window})
        assert resp.status_code == 200, resp.text
        return resp.json()

    def test_iso_dry_run_has_the_exif_digest(self, seeded, edition_client):
        exif = self._plan(edition_client, date_from="1997:02:02 00:00:00", date_to="1997:02:02 23:59:59")
        assert exif["groups_processed"] >= 1
        iso = self._plan(edition_client, date_from="1997-02-02", date_to="1997-02-02")
        assert iso["plan_digest"] == exif["plan_digest"]
        assert iso["preview"] == exif["preview"]

    def test_garbage_is_a_400(self, seeded, edition_client):
        resp = edition_client.post("/api/culling/auto", json={"date_from": "garbage"})
        assert resp.status_code == 400


class TestSuggestProfileIsoWindow:
    def test_iso_window_answers_like_the_exif_form(self, seeded, edition_client):
        exif = edition_client.get(f"/api/culling/suggest_profile?{EXIF}")
        assert exif.status_code == 200, exif.text
        iso = edition_client.get("/api/culling/suggest_profile?date_from=1997-02-02&date_to=1997-02-02")
        assert iso.status_code == 200, iso.text
        assert iso.json() == exif.json()
        assert iso.json()["evidence"]["photos"] == 3

    def test_garbage_is_a_400(self, seeded, edition_client):
        assert edition_client.get("/api/culling/suggest_profile?date_from=garbage").status_code == 400
