"""``POST /api/culling/apply_marks`` and ``POST /api/culling/undo_apply_marks``.

The gallery's assistant-pinned review lets the user commit their own Keep/Remove marks. The routes run on the
shared session database (``seed_photos_prefix``, schema from ``init_database``) with the real auth dependency
chain through the ``*_client`` fixtures; multi-user cases pin ``is_multi_user_enabled`` the way the auto-cull
guard tests do.
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pytest

import api.config
from api.routers import burst_culling
from api.routers.burst_culling import _fetch_unreviewed_burst_groups
from api.similarity_groups import compute_similarity_groups
from tests.conftest import _TEST_DB_FILE

PREFIX = "/apply-marks/"
APPLY = "/api/culling/apply_marks"
UNDO = "/api/culling/undo_apply_marks"
BURST = 9100


def _p(name):
    return PREFIX + name


def _photo(name, **cols):
    return {"path": _p(name), "filename": name, "date_taken": "2026:03:01 10:00:00",
            "aggregate": 5.0, **cols}


def _db():
    conn = sqlite3.connect(_TEST_DB_FILE.name)
    conn.row_factory = sqlite3.Row
    return conn


def _photo_row(name):
    with _db() as conn:
        return dict(conn.execute("SELECT * FROM photos WHERE path = ?", (_p(name),)).fetchone())


def _pref(user, name):
    with _db() as conn:
        row = conn.execute("SELECT * FROM user_preferences WHERE user_id = ? AND photo_path = ?",
                           (user, _p(name))).fetchone()
    return dict(row) if row else None


def _pairs():
    with _db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM comparisons WHERE photo_a_path LIKE ? ORDER BY id", (PREFIX + "%",))]


def _group(keep, reject, kind="burst", **extra):
    return {"kind": kind, "keep_paths": [_p(n) for n in keep], "reject_paths": [_p(n) for n in reject], **extra}


def _apply(client, *groups, status=200):
    resp = client.post(APPLY, json={"groups": list(groups)})
    assert resp.status_code == status, resp.text
    return resp.json()


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    burst_culling.reset_apply_receipts()
    retrains = []
    monkeypatch.setattr("api.routers.burst_culling.trigger_auto_retrain",
                        lambda *a, **k: retrains.append((a, k)))
    yield retrains
    burst_culling.reset_apply_receipts()
    with _db() as conn:
        conn.execute("DELETE FROM comparisons WHERE photo_a_path LIKE ?", (PREFIX + "%",))
        conn.execute("DELETE FROM user_preferences WHERE photo_path LIKE ?", (PREFIX + "%",))


@pytest.fixture()
def retrains(_clean):
    return _clean


@pytest.fixture()
def burst(seed_photos_prefix):
    """A four-frame burst, one frame already rejected, one rated and favourited."""
    return seed_photos_prefix(PREFIX, [
        _photo("b1.jpg", burst_group_id=BURST, is_burst_lead=1, star_rating=4, is_favorite=1),
        _photo("b2.jpg", burst_group_id=BURST, star_rating=3, is_favorite=1),
        _photo("b3.jpg", burst_group_id=BURST, star_rating=2),
        _photo("b4.jpg", burst_group_id=BURST, is_rejected=1, star_rating=5, is_favorite=1),
    ])


@pytest.fixture()
def multi(monkeypatch):
    """Multi-user mode: the edition fixture's user ``test`` and a second user ``other`` see the prefix."""
    monkeypatch.setitem(api.config._FULL_CONFIG, "users", {
        "test": {"role": "admin", "directories": [PREFIX]},
        "other": {"role": "user", "directories": [PREFIX]}})
    monkeypatch.setattr("api.db_helpers.is_multi_user_enabled", lambda: True)
    monkeypatch.setattr("api.routers.burst_culling.is_multi_user_enabled", lambda: True)


class TestWrites:
    def test_remove_marked_photos_are_rejected_and_keep_marked_are_left_alone(self, edition_client, burst):
        body = _apply(edition_client, _group(["b1.jpg"], ["b2.jpg", "b3.jpg"]))
        assert (_photo_row("b2.jpg")["is_rejected"], _photo_row("b3.jpg")["is_rejected"]) == (1, 1)
        assert _photo_row("b1.jpg")["is_rejected"] in (0, None)
        assert body["rejected"] == 2 and body["groups"][0]["rejected"] == 2
        assert sorted(body["groups"][0]["rejected_paths"]) == [_p("b2.jpg"), _p("b3.jpg")]

    def test_a_rejected_keep_photo_is_unrejected(self, edition_client, burst):
        body = _apply(edition_client, _group(["b1.jpg", "b4.jpg"], ["b2.jpg"]))
        assert _photo_row("b4.jpg")["is_rejected"] == 0
        assert body["unrejected"] == 1 and body["groups"][0]["unrejected_paths"] == [_p("b4.jpg")]

    def test_rating_and_favourite_are_never_touched(self, edition_client, burst):
        before = {n: (_photo_row(n)["star_rating"], _photo_row(n)["is_favorite"])
                  for n in ("b1.jpg", "b2.jpg", "b3.jpg", "b4.jpg")}
        _apply(edition_client, _group(["b1.jpg", "b4.jpg"], ["b2.jpg", "b3.jpg"]))
        assert {n: (_photo_row(n)["star_rating"], _photo_row(n)["is_favorite"]) for n in before} == before
        assert before["b2.jpg"] == (3, 1) and before["b4.jpg"] == (5, 1)

    def test_second_identical_apply_changes_nothing(self, edition_client, burst):
        _apply(edition_client, _group(["b1.jpg", "b4.jpg"], ["b2.jpg", "b3.jpg"]))
        body = _apply(edition_client, _group(["b1.jpg", "b4.jpg"], ["b2.jpg", "b3.jpg"]))
        assert body["rejected"] == body["unrejected"] == body["pairs"] == 0
        assert body["noop"] > 0 and body["groups"][0]["noop"] == body["noop"]

    def test_one_retrain_nudge_per_request(self, edition_client, burst, retrains):
        _apply(edition_client, _group(["b1.jpg"], ["b2.jpg"]), _group(["b4.jpg"], ["b3.jpg"], kind=None))
        assert len(retrains) == 1


class TestPerUser:
    def test_multi_user_writes_only_the_callers_preferences(self, edition_client, burst, multi):
        _apply(edition_client, _group(["b1.jpg"], ["b2.jpg"]))
        assert _pref("test", "b2.jpg")["is_rejected"] == 1
        assert _pref("other", "b2.jpg") is None
        assert _photo_row("b2.jpg")["is_rejected"] in (0, None)

    def test_multi_user_unreject_is_per_user(self, edition_client, burst, multi):
        with _db() as conn:
            conn.execute("INSERT INTO user_preferences (user_id, photo_path, is_rejected, star_rating) "
                         "VALUES ('test', ?, 1, 4), ('other', ?, 1, 0)", (_p("b3.jpg"), _p("b3.jpg")))
        body = _apply(edition_client, _group(["b3.jpg"], ["b2.jpg"]))
        assert body["unrejected"] == 1
        assert _pref("test", "b3.jpg")["is_rejected"] == 0 and _pref("test", "b3.jpg")["star_rating"] == 4
        assert _pref("other", "b3.jpg")["is_rejected"] == 1

    def test_single_user_writes_photos(self, edition_client, burst):
        _apply(edition_client, _group(["b1.jpg"], ["b2.jpg"]))
        assert _photo_row("b2.jpg")["is_rejected"] == 1
        assert _pref("test", "b2.jpg") is None


class TestKeepWhole:
    @pytest.fixture()
    def mixed(self, seed_photos_prefix):
        return seed_photos_prefix(PREFIX, [
            _photo("b1.jpg", burst_group_id=BURST),
            _photo("b2.jpg", burst_group_id=BURST),
            _photo("k1.jpg", burst_group_id=BURST, sequence_kind="bracket", sequence_ev_offset=-2,
                   sequence_group_id=1),
            _photo("k2.jpg", burst_group_id=BURST, sequence_kind="panorama", sequence_group_id=2),
        ])

    def test_a_keep_whole_frame_in_reject_paths_is_not_rejected(self, edition_client, mixed):
        body = _apply(edition_client, _group(["b1.jpg"], ["b2.jpg", "k1.jpg", "k2.jpg"]))
        group = body["groups"][0]
        assert sorted(group["skipped_keep_whole"]) == [_p("k1.jpg"), _p("k2.jpg")]
        assert _photo_row("k1.jpg")["is_rejected"] in (0, None) and _photo_row("k2.jpg")["is_rejected"] in (0, None)
        assert _photo_row("b2.jpg")["is_rejected"] == 1
        assert group["rejected_paths"] == [_p("b2.jpg")]

    def test_a_rejected_keep_whole_frame_sent_as_remove_stays_rejected_and_is_never_unrejected(
            self, edition_client, mixed):
        with _db() as conn:
            conn.execute("UPDATE photos SET is_rejected = 1 WHERE path = ?", (_p("k1.jpg"),))
        body = _apply(edition_client, _group(["b1.jpg"], ["b2.jpg", "k1.jpg"], kind="bracket"))
        group = body["groups"][0]
        assert group["skipped_keep_whole"] == [_p("k1.jpg")]
        assert group["unrejected_paths"] == [] and group["unrejected"] == 0
        assert _photo_row("k1.jpg")["is_rejected"] == 1

    def test_no_pair_names_a_keep_whole_frame(self, edition_client, mixed):
        _apply(edition_client, _group(["b1.jpg"], ["b2.jpg", "k1.jpg", "k2.jpg"]))
        pairs = _pairs()
        assert pairs
        assert not {p["photo_a_path"] for p in pairs} & {_p("k1.jpg"), _p("k2.jpg")}
        assert not {p["photo_b_path"] for p in pairs} & {_p("k1.jpg"), _p("k2.jpg")}

    def test_a_burst_group_with_trimmed_frames_is_reviewed_for_every_member(self, edition_client, mixed):
        _apply(edition_client, _group(["b1.jpg"], ["b2.jpg", "k1.jpg", "k2.jpg"]))
        assert {n: _photo_row(n)["burst_reviewed"] for n in ("b1.jpg", "b2.jpg", "k1.jpg", "k2.jpg")} == {
            "b1.jpg": 1, "b2.jpg": 1, "k1.jpg": 1, "k2.jpg": 1}
        assert _photo_row("k1.jpg")["is_burst_lead"] == 1
        with _db() as conn:
            assert not any(g["group_id"] == BURST for g in _fetch_unreviewed_burst_groups(conn, "1=1", []))

    def test_a_keep_whole_kind_sharing_one_burst_id_marks_the_burst_reviewed(self, edition_client, seed_photos_prefix):
        seed_photos_prefix(PREFIX, [
            _photo(f"p{i}.jpg", burst_group_id=BURST + 1, sequence_kind="panorama", sequence_group_id=7)
            for i in range(3)])
        body = _apply(edition_client, _group([], [], kind="panorama") | {
            "keep_paths": [_p("p0.jpg"), _p("p1.jpg"), _p("p2.jpg")]})
        assert body["rejected"] == 0 and body["pairs"] == 0
        assert {_photo_row(f"p{i}.jpg")["burst_reviewed"] for i in range(3)} == {1}

    def test_a_keep_whole_kind_across_two_burst_ids_marks_nothing(self, edition_client, seed_photos_prefix):
        seed_photos_prefix(PREFIX, [
            _photo("p0.jpg", burst_group_id=BURST + 2, sequence_kind="bracket", sequence_group_id=8),
            _photo("p1.jpg", burst_group_id=BURST + 3, sequence_kind="bracket", sequence_group_id=8)])
        _apply(edition_client, _group(["p0.jpg", "p1.jpg"], [], kind="bracket"))
        assert {_photo_row(n)["burst_reviewed"] for n in ("p0.jpg", "p1.jpg")} == {0}


class TestReviewedFlags:
    def test_burst_kind_sets_reviewed_and_leads(self, edition_client, burst):
        _apply(edition_client, _group(["b1.jpg"], ["b2.jpg", "b3.jpg"]))
        rows = {n: _photo_row(n) for n in ("b1.jpg", "b2.jpg", "b3.jpg", "b4.jpg")}
        assert (rows["b1.jpg"]["is_burst_lead"], rows["b1.jpg"]["burst_reviewed"]) == (1, 1)
        assert (rows["b2.jpg"]["is_burst_lead"], rows["b2.jpg"]["burst_reviewed"]) == (0, 1)
        assert (rows["b3.jpg"]["is_burst_lead"], rows["b3.jpg"]["burst_reviewed"]) == (0, 1)
        assert rows["b4.jpg"]["burst_reviewed"] == 0

    def test_similar_kind_sets_similarity_reviewed_on_every_path(self, edition_client, seed_photos_prefix):
        seed_photos_prefix(PREFIX, [_photo("s1.jpg"), _photo("s2.jpg"), _photo("s3.jpg")])
        _apply(edition_client, _group(["s1.jpg"], ["s2.jpg"], kind="similar"))
        assert (_photo_row("s1.jpg")["similarity_reviewed"], _photo_row("s2.jpg")["similarity_reviewed"]) == (1, 1)
        assert _photo_row("s3.jpg")["similarity_reviewed"] in (0, None)

    @pytest.mark.parametrize("kind", ["scene", None])
    def test_scene_and_unknown_kind_mark_nothing(self, edition_client, burst, kind):
        body = _apply(edition_client, _group(["b1.jpg"], ["b2.jpg"], kind=kind))
        assert {_photo_row(n)["burst_reviewed"] for n in ("b1.jpg", "b2.jpg")} == {0}
        assert _photo_row("b1.jpg")["similarity_reviewed"] in (0, None)
        assert body["groups"][0]["rejected"] == 1

    def test_an_unknown_kind_still_records_pairs(self, edition_client, burst):
        body = _apply(edition_client, _group(["b1.jpg"], ["b2.jpg"], kind=None))
        assert body["pairs"] == 1 and _pairs()[0]["session_id"] == "cull-review"

    def test_an_applied_burst_group_leaves_the_burst_feed(self, edition_client, burst):
        with _db() as conn:
            assert any(g["group_id"] == BURST for g in _fetch_unreviewed_burst_groups(conn, "1=1", []))
        _apply(edition_client, _group(["b1.jpg", "b4.jpg"], ["b2.jpg", "b3.jpg"]))
        with _db() as conn:
            assert not any(g["group_id"] == BURST for g in _fetch_unreviewed_burst_groups(conn, "1=1", []))

    def test_an_applied_similar_group_leaves_the_similarity_feed(self, edition_client, seed_photos_prefix):
        vector = np.ones(768, dtype=np.float32)
        vector /= np.linalg.norm(vector)
        blob = vector.tobytes()
        seed_photos_prefix(PREFIX, [_photo("s1.jpg", clip_embedding=blob), _photo("s2.jpg", clip_embedding=blob)])
        with _db() as conn:
            before = compute_similarity_groups(conn, use_cache=False)
        assert any(_p("s1.jpg") in g["paths"] for g in before)
        _apply(edition_client, _group(["s1.jpg"], ["s2.jpg"], kind="similar"))
        with _db() as conn:
            after = compute_similarity_groups(conn, use_cache=False)
        assert not any(_p("s1.jpg") in g["paths"] for g in after)

    def test_an_applied_scene_with_nothing_rejected_is_still_a_scene(self, edition_client, seed_photos_prefix):
        seed_photos_prefix(PREFIX, [
            _photo(f"c{i}.jpg", date_taken=f"2026:04:01 09:00:{i:02d}") for i in range(3)])
        _apply(edition_client, _group(["c0.jpg", "c1.jpg", "c2.jpg"], [], kind="scene"))
        with _db() as conn:
            scenes = burst_culling._fetch_scene_groups(conn, user_id=None, use_cache=False)
        assert any(_p("c0.jpg") in {p["path"] for p in g["photos"]} for g in scenes)


class TestCacheInvalidation:
    def _seed_cache(self):
        with _db() as conn:
            conn.executemany("INSERT OR REPLACE INTO stats_cache (key, value, updated_at) VALUES (?, '{}', 0)",
                             [("scenes_apply_marks_test",), ("similarity_groups_apply_marks_test",)])

    def _cached(self):
        with _db() as conn:
            return sorted(r[0] for r in conn.execute(
                "SELECT key FROM stats_cache WHERE key IN ('scenes_apply_marks_test', "
                "'similarity_groups_apply_marks_test')"))

    def test_apply_and_undo_drop_the_scene_and_similarity_feed_caches(self, edition_client, burst):
        self._seed_cache()
        assert len(self._cached()) == 2
        body = _apply(edition_client, _group(["b1.jpg"], ["b2.jpg"]))
        assert self._cached() == []
        self._seed_cache()
        edition_client.post(UNDO, json={"receipt_id": body["groups"][0]["receipt_id"]})
        assert self._cached() == []


class TestPairsAndReceipts:
    def test_pairs_are_user_scoped_culling_rows_and_the_receipt_holds_exactly_their_ids(
            self, edition_client, burst):
        existing = len(_pairs())
        body = _apply(edition_client, _group(["b1.jpg"], ["b2.jpg", "b3.jpg"]))
        rows = _pairs()
        assert len(rows) - existing == body["pairs"] == 2
        assert {(r["source"], r["session_id"], r["user_id"]) for r in rows} == {("culling", "cull-review", "test")}
        receipt = burst_culling._receipt_peek("test", body["groups"][0]["receipt_id"])
        assert sorted(receipt["pair_ids"]) == sorted(r["id"] for r in rows)

    def test_pairs_are_capped_at_twelve(self, edition_client, seed_photos_prefix):
        seed_photos_prefix(PREFIX, [_photo(f"m{i:02d}.jpg", burst_group_id=BURST + 5) for i in range(20)])
        body = _apply(edition_client, _group(["m00.jpg", "m01.jpg"], [f"m{i:02d}.jpg" for i in range(2, 20)]))
        assert body["pairs"] == 12

    def test_the_receipt_id_is_opaque_and_unique_per_group(self, edition_client, burst):
        body = _apply(edition_client, _group(["b1.jpg"], ["b2.jpg"]), _group(["b3.jpg"], ["b4.jpg"], kind=None))
        ids = [g["receipt_id"] for g in body["groups"]]
        assert len(set(ids)) == 2 and all(len(i) >= 16 for i in ids)

    def test_receipts_expire_after_their_ttl(self, edition_client, burst, monkeypatch):
        clock = [1000.0]
        monkeypatch.setattr(burst_culling, "_receipt_clock", lambda: clock[0])
        body = _apply(edition_client, _group(["b1.jpg"], ["b2.jpg"]))
        rid = body["groups"][0]["receipt_id"]
        clock[0] += burst_culling.RECEIPT_TTL_S - 1
        assert burst_culling._receipt_peek("test", rid) is not None
        clock[0] += 2
        assert burst_culling._receipt_peek("test", rid) is None

    def test_the_per_user_receipt_count_evicts_oldest_first(self, monkeypatch):
        monkeypatch.setattr(burst_culling, "RECEIPT_MAX_PER_USER", 3)
        ids = [burst_culling._receipt_store("u", {"rejected": [], "unrejected": [], "pair_ids": [],
                                                   "burst": [], "similar": []}) for _ in range(5)]
        assert [burst_culling._receipt_peek("u", i) is not None for i in ids] == [False, False, True, True, True]

    def test_the_per_user_path_budget_evicts_oldest_first(self, monkeypatch):
        monkeypatch.setattr(burst_culling, "RECEIPT_MAX_PATHS", 10)
        ids = [burst_culling._receipt_store("u", {"rejected": [f"/x{n}-{i}" for i in range(4)], "unrejected": [],
                                                   "pair_ids": [], "burst": [], "similar": []}) for n in range(3)]
        assert [burst_culling._receipt_peek("u", i) is not None for i in ids] == [False, True, True]


class TestMarksOnlyAndValidation:
    def test_ungrouped_rejects_without_pairs_or_flags(self, edition_client, burst):
        body = _apply(edition_client, {"ungrouped": True, "kind": None, "keep_paths": [_p("b4.jpg")],
                                       "reject_paths": [_p("b2.jpg")]})
        assert body["rejected"] == 1 and body["unrejected"] == 1 and body["pairs"] == 0
        assert _pairs() == [] and _photo_row("b2.jpg")["burst_reviewed"] == 0

    def test_ungrouped_with_a_second_group_is_400(self, edition_client, burst):
        _apply(edition_client, {"ungrouped": True, "kind": None, "keep_paths": [], "reject_paths": [_p("b2.jpg")]},
               _group(["b1.jpg"], ["b3.jpg"]), status=400)
        assert _photo_row("b2.jpg")["is_rejected"] in (0, None)

    def test_ungrouped_with_a_kind_is_400(self, edition_client, burst):
        _apply(edition_client, {"ungrouped": True, "kind": "burst", "keep_paths": [],
                                "reject_paths": [_p("b2.jpg")]}, status=400)

    def test_an_invisible_or_unknown_path_is_400_and_nothing_is_written(self, edition_client, burst):
        _apply(edition_client, _group(["b1.jpg"], ["b2.jpg", "ghost.jpg"]), status=400)
        assert _photo_row("b2.jpg")["is_rejected"] in (0, None) and _pairs() == []

    def test_a_path_the_user_cannot_see_is_400(self, edition_client, burst, multi, seed_photos_prefix):
        seed_photos_prefix("/elsewhere-apply/", [{"path": "/elsewhere-apply/x.jpg", "filename": "x.jpg"}])
        resp = edition_client.post(APPLY, json={"groups": [{"kind": "burst", "keep_paths": [_p("b1.jpg")],
                                                            "reject_paths": ["/elsewhere-apply/x.jpg"]}]})
        assert resp.status_code == 400

    def test_a_duplicate_path_is_400(self, edition_client, burst):
        _apply(edition_client, _group(["b1.jpg"], ["b2.jpg"]), _group(["b3.jpg"], ["b2.jpg"]), status=400)
        _apply(edition_client, _group(["b1.jpg", "b1.jpg"], ["b2.jpg"]), status=400)

    def test_a_path_in_both_lists_is_400(self, edition_client, burst):
        _apply(edition_client, _group(["b1.jpg"], ["b1.jpg"]), status=400)

    def test_caps_are_422(self, edition_client, burst):
        assert edition_client.post(APPLY, json={"groups": []}).status_code == 422
        many = [{"kind": "burst", "keep_paths": [], "reject_paths": [f"/n/{i}.jpg"]} for i in range(201)]
        assert edition_client.post(APPLY, json={"groups": many}).status_code == 422
        big = {"kind": "burst", "keep_paths": [], "reject_paths": [f"/n/{i}.jpg" for i in range(1001)]}
        assert edition_client.post(APPLY, json={"groups": [big]}).status_code == 422


class TestGates:
    def test_anonymous_is_refused(self, anonymous_client, burst):
        assert anonymous_client.post(APPLY, json={"groups": [_group([], ["b2.jpg"])]}).status_code in (401, 403)
        assert _photo_row("b2.jpg")["is_rejected"] in (0, None)

    def test_a_non_edition_user_is_403(self, regular_client, burst):
        assert regular_client.post(APPLY, json={"groups": [_group([], ["b2.jpg"])]}).status_code == 403
        assert _photo_row("b2.jpg")["is_rejected"] in (0, None)

    def test_edition_and_superadmin_pass(self, edition_client, superadmin_client, burst):
        assert edition_client.post(APPLY, json={"groups": [_group(["b1.jpg"], ["b2.jpg"])]}).status_code == 200
        assert superadmin_client.post(APPLY, json={"groups": [_group(["b1.jpg"], ["b3.jpg"])]}).status_code == 200

    def test_undo_gates(self, anonymous_client, regular_client):
        assert anonymous_client.post(UNDO, json={"receipt_id": "x"}).status_code in (401, 403)
        assert regular_client.post(UNDO, json={"receipt_id": "x"}).status_code == 403


class TestUndo:
    def _undo(self, client, receipt_id, status=200):
        resp = client.post(UNDO, json={"receipt_id": receipt_id})
        assert resp.status_code == status, resp.text
        return resp.json()

    def test_undo_restores_rejects_and_unrejects_and_leaves_rating_and_favourite_alone(
            self, edition_client, burst):
        names = ("b1.jpg", "b2.jpg", "b3.jpg", "b4.jpg")
        before = {n: (_photo_row(n)["is_rejected"] or 0, _photo_row(n)["star_rating"], _photo_row(n)["is_favorite"])
                  for n in names}
        body = _apply(edition_client, _group(["b1.jpg", "b4.jpg"], ["b2.jpg", "b3.jpg"]))
        result = self._undo(edition_client, body["groups"][0]["receipt_id"])
        assert sorted(result["restored_rejected"]) == [_p("b2.jpg"), _p("b3.jpg")]
        assert result["restored_unrejected"] == [_p("b4.jpg")]
        assert {n: (_photo_row(n)["is_rejected"] or 0, _photo_row(n)["star_rating"], _photo_row(n)["is_favorite"])
                for n in names} == before

    def test_undo_restores_per_user_state_in_multi_user_mode(self, edition_client, burst, multi):
        with _db() as conn:
            conn.execute("INSERT INTO user_preferences (user_id, photo_path, is_rejected, star_rating, is_favorite) "
                         "VALUES ('test', ?, 1, 4, 1), ('other', ?, 1, 0, 0)", (_p("b4.jpg"), _p("b4.jpg")))
        body = _apply(edition_client, _group(["b1.jpg", "b4.jpg"], ["b2.jpg"]))
        self._undo(edition_client, body["groups"][0]["receipt_id"])
        assert _pref("test", "b4.jpg")["is_rejected"] == 1 and _pref("test", "b4.jpg")["star_rating"] == 4
        assert _pref("test", "b4.jpg")["is_favorite"] == 1
        assert _pref("test", "b2.jpg")["is_rejected"] == 0
        assert _pref("other", "b4.jpg")["is_rejected"] == 1

    def test_undo_deletes_this_groups_pairs_and_keeps_a_manual_comparison(self, edition_client, burst):
        with _db() as conn:
            conn.execute("INSERT INTO comparisons (photo_a_path, photo_b_path, winner, source, user_id) "
                         "VALUES (?, ?, 'a', 'rating', 'test')", (_p("b1.jpg"), _p("b4.jpg")))
        before = len(_pairs())
        body = _apply(edition_client, _group(["b1.jpg"], ["b2.jpg", "b3.jpg"]))
        assert len(_pairs()) == before + 2
        result = self._undo(edition_client, body["groups"][0]["receipt_id"])
        assert result["pairs_deleted"] == 2 and len(_pairs()) == before
        assert _pairs()[0]["source"] == "rating"

    def test_undo_restores_burst_flags_to_their_exact_before_values(self, edition_client, burst):
        before = {n: (_photo_row(n)["is_burst_lead"], _photo_row(n)["burst_reviewed"]) for n in
                  ("b1.jpg", "b2.jpg", "b3.jpg", "b4.jpg")}
        with _db() as conn:
            conn.execute("UPDATE photos SET burst_reviewed = 1 WHERE path = ?", (_p("b3.jpg"),))
        before["b3.jpg"] = (_photo_row("b3.jpg")["is_burst_lead"], 1)
        body = _apply(edition_client, _group(["b1.jpg"], ["b2.jpg", "b3.jpg"]))
        result = self._undo(edition_client, body["groups"][0]["receipt_id"])
        assert result["flags_restored"] >= 1
        assert {n: (_photo_row(n)["is_burst_lead"], _photo_row(n)["burst_reviewed"]) for n in before} == before

    def test_undo_restores_the_similarity_flag(self, edition_client, seed_photos_prefix):
        seed_photos_prefix(PREFIX, [_photo("s1.jpg"), _photo("s2.jpg", similarity_reviewed=0)])
        body = _apply(edition_client, _group(["s1.jpg"], ["s2.jpg"], kind="similar"))
        assert _photo_row("s1.jpg")["similarity_reviewed"] == 1
        self._undo(edition_client, body["groups"][0]["receipt_id"])
        assert {_photo_row(n)["similarity_reviewed"] or 0 for n in ("s1.jpg", "s2.jpg")} == {0}

    def test_a_photo_re_rejected_or_unrejected_after_the_apply_is_not_touched(self, edition_client, burst):
        body = _apply(edition_client, _group(["b1.jpg", "b4.jpg"], ["b2.jpg", "b3.jpg"]))
        with _db() as conn:
            conn.execute("UPDATE photos SET is_rejected = 0 WHERE path = ?", (_p("b2.jpg"),))
            conn.execute("UPDATE photos SET is_rejected = 1 WHERE path = ?", (_p("b4.jpg"),))
        result = self._undo(edition_client, body["groups"][0]["receipt_id"])
        assert result["skipped_changed"] == 2
        assert result["restored_rejected"] == [_p("b3.jpg")] and result["restored_unrejected"] == []
        assert _photo_row("b2.jpg")["is_rejected"] == 0 and _photo_row("b4.jpg")["is_rejected"] == 1

    def test_a_flag_moved_to_a_different_value_by_a_later_write_is_not_reverted(self, edition_client, burst):
        body = _apply(edition_client, _group(["b1.jpg"], ["b2.jpg"]))
        with _db() as conn:
            conn.execute("UPDATE photos SET burst_reviewed = 0, is_burst_lead = 1 WHERE path = ?", (_p("b2.jpg"),))
        self._undo(edition_client, body["groups"][0]["receipt_id"])
        assert (_photo_row("b2.jpg")["is_burst_lead"], _photo_row("b2.jpg")["burst_reviewed"]) == (1, 0)

    def test_an_identical_later_write_is_reverted_too(self, edition_client, burst):
        """Documented limit: compare-and-set sees values, not authorship."""
        body = _apply(edition_client, _group(["b1.jpg"], ["b2.jpg"]))
        with _db() as conn:
            conn.execute("UPDATE photos SET is_rejected = 1, burst_reviewed = 1, is_burst_lead = 0 WHERE path = ?",
                         (_p("b2.jpg"),))
        self._undo(edition_client, body["groups"][0]["receipt_id"])
        assert _photo_row("b2.jpg")["is_rejected"] == 0 and _photo_row("b2.jpg")["burst_reviewed"] == 0

    def test_a_pair_owned_by_another_user_or_from_another_source_is_not_deleted(self, edition_client, burst):
        body = _apply(edition_client, _group(["b1.jpg"], ["b2.jpg"]))
        rid = body["groups"][0]["receipt_id"]
        pair_id = burst_culling._receipt_peek("test", rid)["pair_ids"][0]
        with _db() as conn:
            conn.execute("UPDATE comparisons SET user_id = 'other' WHERE id = ?", (pair_id,))
        assert self._undo(edition_client, rid)["pairs_deleted"] == 0
        body = _apply(edition_client, _group(["b1.jpg"], ["b3.jpg"]))
        rid = body["groups"][0]["receipt_id"]
        pair_id = burst_culling._receipt_peek("test", rid)["pair_ids"][0]
        with _db() as conn:
            conn.execute("UPDATE comparisons SET source = 'rating' WHERE id = ?", (pair_id,))
        assert self._undo(edition_client, rid)["pairs_deleted"] == 0
        assert len(_pairs()) == 2

    def test_a_later_flag_change_is_counted_and_the_flag_is_left_alone(self, edition_client, burst):
        body = _apply(edition_client, _group(["b1.jpg"], ["b2.jpg"]))
        with _db() as conn:
            conn.execute("UPDATE photos SET burst_reviewed = 0, is_burst_lead = 1 WHERE path = ?", (_p("b1.jpg"),))
        result = self._undo(edition_client, body["groups"][0]["receipt_id"])
        assert result["skipped_changed"] == 1
        assert (_photo_row("b1.jpg")["is_burst_lead"], _photo_row("b1.jpg")["burst_reviewed"]) == (1, 0)

    def test_a_changed_similar_flag_is_counted(self, edition_client, seed_photos_prefix):
        seed_photos_prefix(PREFIX, [_photo("s1.jpg"), _photo("s2.jpg", similarity_reviewed=0)])
        body = _apply(edition_client, _group(["s1.jpg"], ["s2.jpg"], kind="similar"))
        with _db() as conn:
            conn.execute("UPDATE photos SET similarity_reviewed = 0 WHERE path = ?", (_p("s1.jpg"),))
        result = self._undo(edition_client, body["groups"][0]["receipt_id"])
        assert result["skipped_changed"] == 1 and result["flags_restored"] == 1

    def test_a_receipt_path_that_became_invisible_is_counted(self, edition_client, burst):
        body = _apply(edition_client, _group(["b1.jpg"], ["b2.jpg", "b3.jpg"]))
        with _db() as conn:
            conn.execute("DELETE FROM photos WHERE path = ?", (_p("b3.jpg"),))
        result = self._undo(edition_client, body["groups"][0]["receipt_id"])
        assert result["restored_rejected"] == [_p("b2.jpg")]
        assert result["skipped_changed"] == 1

    def test_a_photo_both_rejected_and_flagged_is_counted_once(self, edition_client, burst):
        body = _apply(edition_client, _group(["b1.jpg"], ["b2.jpg"]))
        with _db() as conn:
            conn.execute("UPDATE photos SET is_rejected = 0, burst_reviewed = 0 WHERE path = ?", (_p("b2.jpg"),))
        result = self._undo(edition_client, body["groups"][0]["receipt_id"])
        assert result["skipped_changed"] == 1

    def test_a_clean_undo_skips_nothing(self, edition_client, burst):
        body = _apply(edition_client, _group(["b1.jpg", "b4.jpg"], ["b2.jpg"]))
        assert self._undo(edition_client, body["groups"][0]["receipt_id"])["skipped_changed"] == 0

    def test_the_receipt_is_consumed_by_a_successful_undo(self, edition_client, burst):
        rid = _apply(edition_client, _group(["b1.jpg"], ["b2.jpg"]))["groups"][0]["receipt_id"]
        assert burst_culling._receipt_peek("test", rid) is not None
        self._undo(edition_client, rid)
        assert burst_culling._receipt_peek("test", rid) is None

    def test_a_failed_write_puts_the_receipt_back_so_a_retry_works(self, edition_client, burst, monkeypatch):
        rid = _apply(edition_client, _group(["b1.jpg"], ["b2.jpg"]))["groups"][0]["receipt_id"]
        stored_at = burst_culling._apply_receipts["test"][rid][0]
        real = burst_culling._after_marks_write

        during = []

        def boom(conn):
            during.append(burst_culling._receipt_peek("test", rid))
            raise sqlite3.OperationalError("injected")
        monkeypatch.setattr(burst_culling, "_after_marks_write", boom)
        self._undo(edition_client, rid, status=500)
        assert during == [None]
        assert burst_culling._apply_receipts["test"][rid][0] == stored_at
        assert _photo_row("b2.jpg")["is_rejected"] == 1
        monkeypatch.setattr(burst_culling, "_after_marks_write", real)
        assert self._undo(edition_client, rid)["restored_rejected"] == [_p("b2.jpg")]
        self._undo(edition_client, rid, status=404)

    def test_a_second_undo_is_404(self, edition_client, burst):
        rid = _apply(edition_client, _group(["b1.jpg"], ["b2.jpg"]))["groups"][0]["receipt_id"]
        self._undo(edition_client, rid)
        self._undo(edition_client, rid, status=404)

    def test_forged_and_expired_and_restarted_ids_are_404_and_change_nothing(self, edition_client, burst, monkeypatch):
        self._undo(edition_client, "forged-id-0123456789", status=404)
        clock = [1000.0]
        monkeypatch.setattr(burst_culling, "_receipt_clock", lambda: clock[0])
        rid = _apply(edition_client, _group(["b1.jpg"], ["b2.jpg"]))["groups"][0]["receipt_id"]
        clock[0] += burst_culling.RECEIPT_TTL_S + 1
        self._undo(edition_client, rid, status=404)
        assert _photo_row("b2.jpg")["is_rejected"] == 1
        monkeypatch.setattr(burst_culling, "_receipt_clock", lambda: 1000.0)
        rid = _apply(edition_client, _group(["b1.jpg"], ["b3.jpg"]))["groups"][0]["receipt_id"]
        burst_culling.reset_apply_receipts()
        self._undo(edition_client, rid, status=404)
        assert _photo_row("b3.jpg")["is_rejected"] == 1

    def test_another_users_receipt_is_404_and_nothing_changes(self, edition_client, burst):
        rid = _apply(edition_client, _group(["b1.jpg"], ["b2.jpg"]))["groups"][0]["receipt_id"]
        _, receipt = burst_culling._receipt_take("test", rid)
        foreign = burst_culling._receipt_store("someone-else", receipt)
        self._undo(edition_client, foreign, status=404)
        assert _photo_row("b2.jpg")["is_rejected"] == 1

    def test_undo_of_an_apply_that_recorded_no_pairs_or_flags(self, edition_client, burst):
        rid = _apply(edition_client, {"ungrouped": True, "kind": None, "keep_paths": [],
                                      "reject_paths": [_p("b2.jpg")]})["groups"][0]["receipt_id"]
        result = self._undo(edition_client, rid)
        assert result["pairs_deleted"] == 0 and result["flags_restored"] == 0
        assert _photo_row("b2.jpg")["is_rejected"] == 0

    def test_a_receipt_path_that_became_invisible_is_skipped(self, edition_client, burst, multi):
        rid = _apply(edition_client, _group(["b1.jpg"], ["b2.jpg", "b3.jpg"]))["groups"][0]["receipt_id"]
        receipt = burst_culling._receipt_peek("test", rid)
        receipt["rejected"].append("/elsewhere-undo/secret.jpg")
        with _db() as conn:
            conn.execute("INSERT OR REPLACE INTO photos (path, filename) VALUES ('/elsewhere-undo/secret.jpg', 's')")
            conn.execute("INSERT INTO user_preferences (user_id, photo_path, is_rejected) "
                         "VALUES ('test', '/elsewhere-undo/secret.jpg', 1)")
        try:
            result = self._undo(edition_client, rid)
            assert "/elsewhere-undo/secret.jpg" not in result["restored_rejected"]
            with _db() as conn:
                row = conn.execute("SELECT is_rejected FROM user_preferences WHERE user_id = 'test' "
                                   "AND photo_path = '/elsewhere-undo/secret.jpg'").fetchone()
            assert row["is_rejected"] == 1
        finally:
            with _db() as conn:
                conn.execute("DELETE FROM photos WHERE path LIKE '/elsewhere-undo/%'")
                conn.execute("DELETE FROM user_preferences WHERE photo_path LIKE '/elsewhere-undo/%'")
