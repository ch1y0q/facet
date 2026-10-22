"""POST /api/culling/plan: the agent's auto-cull plan as culling groups.

Auth goes through the conftest fixtures (edition_client / regular_client / anonymous_client); rows are
written into the shared session database under one path prefix.
"""

import json
import sqlite3

import pytest

from api.models.culling import CullPlanRequest
from api.routers import burst_culling
from tests.conftest import _TEST_DB_FILE

PREFIX = "/cull-plan-route/"
DAY = "1996:03:03"
WINDOW = {"date_from": "1996-03-03", "date_to": "1996-03-03"}
BURST_A, BURST_B = 80801, 80802


def _row(name, second, aggregate, gid, **extra):
    return {"path": PREFIX + name, "filename": name, "date_taken": f"{DAY} 10:00:{second:02d}",
            "aggregate": aggregate, "aesthetic": aggregate, "tech_sharpness": aggregate,
            "burst_group_id": gid, "is_burst_lead": 0, **extra}


def _rows():
    return [
        _row("a1.jpg", 1, 9.0, BURST_A), _row("a2.jpg", 2, 5.0, BURST_A), _row("a3.jpg", 3, 2.0, BURST_A),
        _row("b1.jpg", 11, 8.0, BURST_B), _row("b2.jpg", 12, 4.0, BURST_B), _row("b3.jpg", 13, 1.0, BURST_B),
    ]


def _db():
    conn = sqlite3.connect(_TEST_DB_FILE.name)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture()
def seeded(seed_photos_prefix):
    seed_photos_prefix(PREFIX, _rows())
    burst_culling._invalidate_culling_groups_cache()
    yield
    conn = _db()
    conn.execute("DELETE FROM comparisons WHERE photo_a_path LIKE ? OR photo_b_path LIKE ?",
                 (PREFIX + "%", PREFIX + "%"))
    conn.commit()
    conn.close()
    burst_culling._invalidate_culling_groups_cache()


def _auto_body(**extra):
    return {"group_by": "burst", "strictness": 100, **WINDOW, **extra}


def _digest(client, **extra):
    resp = client.post("/api/culling/auto", json=_auto_body(**extra))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _plan(client, digest, **extra):
    return client.post("/api/culling/plan", json={**_auto_body(**extra), "expected_digest": digest})


def _ours(groups):
    return [g for g in groups if any(p["path"].startswith(PREFIX) for p in g["photos"])]


def _rejected_paths():
    conn = _db()
    try:
        return {r[0] for r in conn.execute("SELECT path FROM photos WHERE path LIKE ? AND is_rejected = 1",
                                           (PREFIX + "%",))}
    finally:
        conn.close()


class TestPlanMatchesAutoCull:
    def test_numbers_keepers_reasons_and_group_reason_equal_the_preview(self, seeded, edition_client):
        auto = _digest(edition_client)
        resp = _plan(edition_client, auto["plan_digest"])
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["plan_digest"] == auto["plan_digest"]
        assert body["truncated"] is False and body["oversize_groups"] == 0
        assert body["total_groups"] == auto["groups_processed"]
        rows = {(r["type"], r["group_id"]): r for r in auto["preview"]}
        groups = {(g["type"], g["group_id"]): g for g in body["groups"]}
        assert groups.keys() == rows.keys()
        assert (("burst", BURST_A) in groups) and (("burst", BURST_B) in groups)
        for key, row in rows.items():
            group = groups[key]
            assert group["plan"]["number"] == row["number"]
            assert group["plan"]["keep_paths"][:len(row["keep_paths"])] == row["keep_paths"]
            assert group["best_path"] == row["keep_paths"][0]
            assert [p["path"] for p in group["photos"]] == row["keep_paths"] + row["reject_paths"]
            assert group["plan"]["group_reason"] == row.get("group_reason")
            for photo in group["photos"]:
                if photo["path"] in row["reasons"]:
                    assert photo["cull_reason"] == row["reasons"][photo["path"]]
                assert type(photo["is_rejected"]) is int

    def test_round_trip_of_the_agent_request_gives_the_dry_run_digest(self, seeded, edition_client):
        request = CullPlanRequest(group_by="burst", strictness=100, date_from="1996-03-03",
                                  date_to="1996-03-03", highlights_album="Best")
        auto = edition_client.post("/api/culling/auto", json={**request.model_dump(), "dry_run": True}).json()
        resp = edition_client.post("/api/culling/plan",
                                   json={**request.model_dump(), "expected_digest": auto["plan_digest"]})
        assert resp.status_code == 200, resp.text
        assert resp.json()["plan_digest"] == auto["plan_digest"]

    def test_overrides_in_the_request_move_the_plan(self, seeded, edition_client):
        overrides = {"keep_paths": [PREFIX + "a2.jpg"]}
        auto = _digest(edition_client, **overrides)
        body = _plan(edition_client, auto["plan_digest"], **overrides).json()
        group = next(g for g in body["groups"] if g["group_id"] == BURST_A)
        assert PREFIX + "a2.jpg" in group["plan"]["keep_paths"]


class TestDigestGuard:
    def test_a_stale_digest_is_a_412_and_writes_nothing(self, seeded, edition_client):
        resp = _plan(edition_client, "0" * 64)
        assert resp.status_code == 412
        assert resp.json()["detail"].startswith("The plan changed since it was previewed")
        assert _rejected_paths() == set()

    def test_a_missing_digest_is_a_422(self, seeded, edition_client):
        assert edition_client.post("/api/culling/plan", json=_auto_body()).status_code == 422

    def test_a_bad_override_is_a_400(self, seeded, edition_client):
        both = {"keep_paths": [PREFIX + "a2.jpg"], "remove_paths": [PREFIX + "a2.jpg"]}
        assert _plan(edition_client, "x", **both).status_code == 400


class TestAuth:
    def test_a_regular_user_is_refused(self, regular_client):
        assert regular_client.post("/api/culling/plan", json={"expected_digest": "x"}).status_code == 403

    def test_an_anonymous_caller_is_refused(self, anonymous_client):
        assert anonymous_client.post("/api/culling/plan", json={"expected_digest": "x"}).status_code in (401, 403)


class TestKindsAndCollisions:
    def test_burst_and_similar_ids_that_collide_stay_separate(self, seeded, edition_client, monkeypatch):
        real = burst_culling._collect_auto_cull_groups

        def collect(*args, **kwargs):
            groups = real(*args, **kwargs)
            a = next(g for g in groups if g["group_id"] == BURST_A)
            b = next(g for g in groups if g["group_id"] == BURST_B)
            a["group_id"] = 5
            return [a, {**b, "type": "similar", "group_id": 5}]

        monkeypatch.setattr(burst_culling, "_collect_auto_cull_groups", collect)
        auto = _digest(edition_client, group_by="all")
        body = _plan(edition_client, auto["plan_digest"], group_by="all").json()
        assert {(g["type"], g["group_id"]) for g in _ours(body["groups"])} == {("burst", 5), ("similar", 5)}
        keeps = [set(g["plan"]["keep_paths"]) for g in body["groups"]]
        assert len(keeps) == 2 and not keeps[0] & keeps[1]

    def test_trim_brackets_adds_the_bracket_group(self, seed_photos_prefix, edition_client):
        prefix = "/cull-plan-route-bracket/"
        rows = [{"path": f"{prefix}k{i}.jpg", "filename": f"k{i}.jpg", "date_taken": f"1996:03:04 10:00:0{i}",
                 "aggregate": 6.0, "aesthetic": 6.0, "tech_sharpness": 6.0, "sequence_kind": "bracket",
                 "sequence_group_id": 80811, "sequence_ev_offset": off, "shadow_clipped": 0,
                 "highlight_clipped": 0} for i, off in enumerate((-2.0, 0.0, 2.0))]
        seed_photos_prefix(prefix, rows)
        window = {"date_from": "1996-03-04", "date_to": "1996-03-04"}
        plain = edition_client.post("/api/culling/auto", json={"group_by": "burst", **window}).json()
        assert not [r for r in plain["preview"] if r["type"] == "bracket"]
        body = {"group_by": "burst", "trim_brackets": True, **window}
        auto = edition_client.post("/api/culling/auto", json=body).json()
        resp = edition_client.post("/api/culling/plan", json={**body, "expected_digest": auto["plan_digest"]})
        assert resp.status_code == 200, resp.text
        group = next(g for g in resp.json()["groups"] if g["type"] == "bracket")
        assert group["plan"]["keep_paths"] == [prefix + "k1.jpg"]
        assert group["sequence_kind"] == "bracket"
        assert len(group["photos"]) == 3


class TestBurstConfirmKeepsWhatThePlanNeverSaw:
    """Confirming a burst rejects every visible DB member outside keep_paths (R2)."""

    ALBUM = 80890

    def _scene(self, seed_photos_prefix):
        rows = _rows() + [
            # Same burst as a1..a3 but outside the album the plan is scoped to: the plan never lists them.
            _row("a4.jpg", 4, 3.0, BURST_A),
            _row("a5.jpg", 5, 3.0, BURST_A, is_rejected=1),
        ]
        seed_photos_prefix(PREFIX, rows)
        conn = _db()
        conn.execute("INSERT OR REPLACE INTO albums (id, user_id, name) VALUES (?, 'test', 'cull-plan-route')",
                     (self.ALBUM,))
        for name in ("a1.jpg", "a2.jpg", "a3.jpg"):
            conn.execute("INSERT OR REPLACE INTO album_photos (album_id, photo_path, position) VALUES (?, ?, 0)",
                         (self.ALBUM, PREFIX + name))
        conn.commit()
        conn.close()
        burst_culling._invalidate_culling_groups_cache()

    @pytest.fixture(autouse=True)
    def _drop_album(self):
        yield
        conn = _db()
        conn.execute("DELETE FROM album_photos WHERE album_id = ?", (self.ALBUM,))
        conn.execute("DELETE FROM albums WHERE id = ?", (self.ALBUM,))
        conn.commit()
        conn.close()

    def _confirm(self, client, group):
        return client.post("/api/culling-groups/confirm", json={
            "type": group["type"], "group_id": group["group_id"],
            "paths": [p["path"] for p in group["photos"]], "keep_paths": group["plan"]["keep_paths"]})

    def test_a_visible_member_outside_the_window_is_kept_and_a_rejected_one_is_not_revived(
            self, seed_photos_prefix, edition_client):
        self._scene(seed_photos_prefix)
        scope = {"album_id": self.ALBUM}
        auto = _digest(edition_client, **scope)
        body = _plan(edition_client, auto["plan_digest"], **scope).json()
        group = next(g for g in body["groups"] if g["group_id"] == BURST_A)
        listed = [p["path"] for p in group["photos"]]
        assert PREFIX + "a4.jpg" not in listed and PREFIX + "a5.jpg" not in listed
        assert PREFIX + "a4.jpg" in group["plan"]["keep_paths"]
        assert PREFIX + "a5.jpg" not in group["plan"]["keep_paths"]
        resp = self._confirm(edition_client, group)
        assert resp.status_code == 200, resp.text
        conn = _db()
        try:
            state = {r["path"]: (r["is_rejected"], r["is_burst_lead"]) for r in conn.execute(
                "SELECT path, is_rejected, is_burst_lead FROM photos WHERE path LIKE ?", (PREFIX + "a%",))}
            winners = {r[0] for r in conn.execute(
                "SELECT CASE winner WHEN 'a' THEN photo_a_path WHEN 'b' THEN photo_b_path END FROM comparisons "
                "WHERE photo_a_path LIKE ? OR photo_b_path LIKE ?", (PREFIX + "%", PREFIX + "%"))}
        finally:
            conn.close()
        assert state[PREFIX + "a2.jpg"][0] == 1 and state[PREFIX + "a3.jpg"][0] == 1
        assert state[PREFIX + "a1.jpg"] == (0, 1)
        assert state[PREFIX + "a4.jpg"][0] == 0
        assert state[PREFIX + "a5.jpg"] == (1, 0)
        assert PREFIX + "a5.jpg" not in winners

    def test_similar_plan_group_posted_unchanged_rejects_exactly_the_plan_rejects(
            self, seeded, edition_client, monkeypatch):
        real = burst_culling._collect_auto_cull_groups

        def collect(*args, **kwargs):
            groups = real(*args, **kwargs)
            b = next(g for g in groups if g["group_id"] == BURST_B)
            return [{**b, "type": "similar", "group_id": 3}]

        monkeypatch.setattr(burst_culling, "_collect_auto_cull_groups", collect)
        auto = _digest(edition_client, group_by="all")
        group = _plan(edition_client, auto["plan_digest"], group_by="all").json()["groups"][0]
        assert group["type"] == "similar"
        assert self._confirm(edition_client, group).status_code == 200
        assert _rejected_paths() == {PREFIX + "b2.jpg", PREFIX + "b3.jpg"}


class TestCaps:
    def _plan_of(self, groups, per_group):
        plan = []
        for n in range(groups):
            photos = [{"path": f"/cap/{n}/{i}.jpg", "burst_score": 10 - i, "aggregate": 5.0,
                       "filename": f"{i}.jpg", "date_taken": "2025:01:01 10:00:00"} for i in range(per_group)]
            group = {"group_id": n, "type": "similar", "reason": "burst", "photos": photos,
                     "best_path": photos[0]["path"], "count": per_group, "category": None}
            plan.append({"group": group, "keep": photos[:1], "reject": photos[1:], "number": n + 1,
                         "keep_paths": [photos[0]["path"]], "reject_paths": [p["path"] for p in photos[1:]]})
        return plan

    def _run(self, plan):
        conn = sqlite3.connect(_TEST_DB_FILE.name)
        conn.row_factory = sqlite3.Row
        try:
            return burst_culling._plan_as_culling_groups(conn, "test", plan)
        finally:
            conn.close()

    def test_more_than_500_groups_are_truncated(self):
        groups, truncated, oversize = self._run(self._plan_of(501, 2))
        assert (len(groups), truncated, oversize) == (500, True, 0)

    def test_the_photo_cap_truncates(self):
        groups, truncated, _ = self._run(self._plan_of(6, 900))
        assert truncated is True and sum(len(g["photos"]) for g in groups) <= 5000 and len(groups) == 5

    def test_a_group_over_the_confirm_cap_is_dropped_and_counted(self):
        plan = self._plan_of(1, 1001) + self._plan_of(1, 3)
        groups, truncated, oversize = self._run(plan)
        assert (len(groups), truncated, oversize) == (1, False, 1)

    def test_a_500_group_response_stays_under_8_mb(self):
        groups, _, _ = self._run(self._plan_of(500, 10))
        assert len(json.dumps({"groups": groups})) < 8 * 1024 * 1024
