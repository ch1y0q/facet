"""The auto-cull state guard: per-photo exclusion instead of a whole 412.

Route core (``run_auto_cull`` with ``state_guard=True``, what ``POST /api/culling/auto`` passes for an agent
request) on databases built with ``db.schema.init_database``; the HTTP cases use the shared session DB
through ``seed_photos_prefix``.
"""

from __future__ import annotations

import os
import sqlite3

import pytest

import api.config
from api.routers import burst_culling
from api.routers.burst_culling import AutoCullPlanChanged, run_auto_cull
from db.schema import init_database
from tests.conftest import AGENT_DIR

BURST = 4242
SCORES = {"b1.jpg": 9.0, "b2.jpg": 3.0, "b3.jpg": 1.0}


@pytest.fixture(autouse=True)
def _no_retrain(monkeypatch):
    monkeypatch.setattr("api.routers.burst_culling.trigger_auto_retrain", lambda *a, **k: None)
    burst_culling.reset_state_guard()


@pytest.fixture()
def clock(monkeypatch):
    """A settable monotonic clock for the guard's TTL."""
    now = [1000.0]
    monkeypatch.setattr(burst_culling, "_guard_clock", lambda: now[0])
    return now


def _kwargs(**over):
    return {"group_by": "burst", "strictness": 0, "min_keep": 1, **over}


def _library(tmp_path, extra=0):
    db = str(tmp_path / "lib.db")
    init_database(db)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    names = dict(SCORES)
    names.update({f"x{i:03d}.jpg": 1.0 - i / 1000 for i in range(extra)})
    for second, (name, score) in enumerate(names.items()):
        conn.execute(
            "INSERT INTO photos (path, filename, date_taken, aggregate, aesthetic, tech_sharpness, is_blink, "
            "burst_group_id, is_burst_lead) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)",
            (str(tmp_path / name), name, f"2024:06:15 10:{second // 60:02d}:{second % 60:02d}", score, score,
             score, BURST, 1 if name == "b1.jpg" else 0))
    conn.commit()
    return db, conn


def _similar_library(tmp_path):
    """Two unrelated similar pairs (a1/a2 and b1/b2) with distinct embeddings, no burst ids."""
    import numpy as np
    db = str(tmp_path / "similar.db")
    init_database(db)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    for second, (name, score, axis) in enumerate([("a1.jpg", 9.0, 0), ("a2.jpg", 3.0, 0),
                                                   ("b1.jpg", 9.0, 1), ("b2.jpg", 3.0, 1)]):
        vector = np.zeros(768, dtype=np.float32)
        vector[axis] = 1.0
        conn.execute(
            "INSERT INTO photos (path, filename, date_taken, aggregate, aesthetic, tech_sharpness, is_blink, "
            "clip_embedding) VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
            (str(tmp_path / name), name, f"2024:06:15 1{axis}:00:{second:02d}", score, score, score,
             vector.tobytes()))
    conn.commit()
    return db, conn


def _p(tmp_path, name):
    return str(tmp_path / name)


def _rejected(conn):
    return {os.path.basename(r[0]) for r in conn.execute("SELECT path FROM photos WHERE is_rejected = 1")}


def _preview(conn, db, user="_anonymous", **over):
    return run_auto_cull(conn, db, user, **_kwargs(**over), dry_run=True, state_guard=True)


def _apply(conn, db, preview, user="_anonymous", **over):
    return run_auto_cull(conn, db, user, **_kwargs(**over), dry_run=False, state_guard=True,
                         expected_digest=preview.plan_digest)


class TestPerPhotoExclusion:
    def test_a_five_star_after_the_preview_is_skipped_and_the_rest_rejected(self, tmp_path):
        db, conn = _library(tmp_path)
        preview = _preview(conn, db)
        assert {os.path.basename(p) for p in preview.reject_paths} == {"b2.jpg", "b3.jpg"}
        conn.execute("UPDATE photos SET star_rating = 5 WHERE path = ?", (_p(tmp_path, "b2.jpg"),))
        conn.commit()
        result = _apply(conn, db, preview)
        assert _rejected(conn) == {"b3.jpg"}
        assert result.skipped_user_changed == [_p(tmp_path, "b2.jpg")]
        assert result.skipped_user_changed_count == 1

    def test_a_favourite_after_the_preview_is_skipped(self, tmp_path):
        db, conn = _library(tmp_path)
        preview = _preview(conn, db)
        conn.execute("UPDATE photos SET is_favorite = 1 WHERE path = ?", (_p(tmp_path, "b3.jpg"),))
        conn.commit()
        result = _apply(conn, db, preview)
        assert _rejected(conn) == {"b2.jpg"}
        assert result.skipped_user_changed == [_p(tmp_path, "b3.jpg")]

    def test_a_manual_reject_after_the_preview_is_tolerated_and_listed(self, tmp_path):
        db, conn = _library(tmp_path)
        preview = _preview(conn, db)
        conn.execute("UPDATE photos SET is_rejected = 1 WHERE path = ?", (_p(tmp_path, "b2.jpg"),))
        conn.commit()
        result = _apply(conn, db, preview)
        assert _rejected(conn) == {"b2.jpg", "b3.jpg"}
        assert result.skipped_user_changed == [_p(tmp_path, "b2.jpg")]

    def test_a_change_to_an_untouched_photo_still_refuses(self, tmp_path):
        db, conn = _library(tmp_path)
        preview = _preview(conn, db)
        conn.execute("UPDATE photos SET aggregate = 9.9, aesthetic = 9.9, tech_sharpness = 9.9 WHERE path = ?",
                     (_p(tmp_path, "b3.jpg"),))
        conn.commit()
        with pytest.raises(AutoCullPlanChanged):
            _apply(conn, db, preview)
        assert _rejected(conn) == set()

    def test_a_user_change_plus_an_unrelated_change_still_refuses(self, tmp_path):
        db, conn = _library(tmp_path)
        preview = _preview(conn, db)
        conn.execute("UPDATE photos SET is_rejected = 1 WHERE path = ?", (_p(tmp_path, "b2.jpg"),))
        conn.execute("UPDATE photos SET aggregate = 9.9, aesthetic = 9.9, tech_sharpness = 9.9 WHERE path = ?",
                     (_p(tmp_path, "b3.jpg"),))
        conn.commit()
        with pytest.raises(AutoCullPlanChanged):
            _apply(conn, db, preview)

    def test_a_different_option_part_still_refuses_even_with_a_user_change(self, tmp_path):
        db, conn = _library(tmp_path)
        preview = _preview(conn, db)
        conn.execute("UPDATE photos SET is_rejected = 1 WHERE path = ?", (_p(tmp_path, "b2.jpg"),))
        conn.commit()
        with pytest.raises(AutoCullPlanChanged):
            run_auto_cull(conn, db, "_anonymous", **_kwargs(highlights_album="Best"), dry_run=False,
                          state_guard=True, expected_digest=preview.plan_digest)

    def test_nothing_changed_reports_nothing(self, tmp_path):
        db, conn = _library(tmp_path)
        preview = _preview(conn, db)
        result = _apply(conn, db, preview)
        assert _rejected(conn) == {"b2.jpg", "b3.jpg"}
        assert result.skipped_user_changed == [] and result.skipped_user_changed_count == 0
        assert result.state_guard is None


class TestSnapshotStore:
    def test_the_first_snapshot_wins_a_later_dry_run_never_overwrites(self, tmp_path):
        db, conn = _library(tmp_path)
        preview = _preview(conn, db)
        conn.execute("UPDATE photos SET star_rating = 5 WHERE path = ?", (_p(tmp_path, "b2.jpg"),))
        conn.commit()
        _preview(conn, db)
        result = _apply(conn, db, preview)
        assert result.skipped_user_changed == [_p(tmp_path, "b2.jpg")]
        assert _rejected(conn) == {"b3.jpg"}

    def test_an_expired_snapshot_reports_unavailable_and_keeps_the_legacy_refusal(self, tmp_path, clock):
        db, conn = _library(tmp_path)
        preview = _preview(conn, db)
        clock[0] += burst_culling.GUARD_TTL_S + 1
        conn.execute("UPDATE photos SET is_rejected = 1 WHERE path = ?", (_p(tmp_path, "b2.jpg"),))
        conn.commit()
        with pytest.raises(AutoCullPlanChanged):
            _apply(conn, db, preview)

    def test_an_expired_snapshot_with_an_equal_plan_applies_and_says_unavailable(self, tmp_path, clock):
        db, conn = _library(tmp_path)
        preview = _preview(conn, db)
        clock[0] += burst_culling.GUARD_TTL_S + 1
        conn.execute("UPDATE photos SET star_rating = 5 WHERE path = ?", (_p(tmp_path, "b2.jpg"),))
        conn.commit()
        result = _apply(conn, db, preview)
        assert result.state_guard == "unavailable"
        assert result.skipped_user_changed == []
        assert _rejected(conn) == {"b2.jpg", "b3.jpg"}

    def test_a_user_keeps_at_most_eight_snapshots_least_recently_used_first(self, tmp_path):
        db, conn = _library(tmp_path)
        digests = []
        for album in range(burst_culling.GUARD_MAX_PER_USER + 1):
            digests.append(_preview(conn, db, highlights_album=f"A{album}").plan_digest)
        assert burst_culling.state_guard_size("_anonymous") == burst_culling.GUARD_MAX_PER_USER
        assert not burst_culling.state_guard_has("_anonymous", digests[0])
        assert burst_culling.state_guard_has("_anonymous", digests[-1])

    def test_the_cli_passes_no_guard_and_stores_nothing(self, tmp_path):
        db, conn = _library(tmp_path)
        preview = run_auto_cull(conn, db, "_anonymous", **_kwargs(), dry_run=True)
        assert not burst_culling.state_guard_has("_anonymous", preview.plan_digest)
        conn.execute("UPDATE photos SET is_rejected = 1 WHERE path = ?", (_p(tmp_path, "b2.jpg"),))
        conn.commit()
        with pytest.raises(AutoCullPlanChanged):
            run_auto_cull(conn, db, "_anonymous", **_kwargs(), dry_run=False,
                          expected_digest=preview.plan_digest)


class TestEmptiedAndCapped:
    def test_a_group_whose_keepers_were_all_touched_is_skipped_whole(self, tmp_path):
        db, conn = _library(tmp_path)
        preview = _preview(conn, db)
        conn.execute("UPDATE photos SET star_rating = 3 WHERE path = ?", (_p(tmp_path, "b1.jpg"),))
        conn.commit()
        result = _apply(conn, db, preview)
        assert _rejected(conn) == set()
        assert result.skipped_user_changed_groups == 1
        assert result.skipped_user_changed == [_p(tmp_path, "b1.jpg")]

    def test_sixty_changed_paths_list_fifty_and_count_sixty(self, tmp_path):
        db, conn = _library(tmp_path, extra=70)
        preview = _preview(conn, db)
        rejected = [p for p in preview.reject_paths if os.path.basename(p).startswith("x")]
        assert len(rejected) == 70
        for path in rejected[:60]:
            conn.execute("UPDATE photos SET star_rating = 4 WHERE path = ?", (path,))
        conn.commit()
        result = _apply(conn, db, preview)
        assert result.skipped_user_changed_count == 60 and len(result.skipped_user_changed) == 50
        assert len(_rejected(conn)) == 12


class TestSkipPaths:
    def test_skip_paths_are_not_part_of_the_digest_and_are_dropped_from_the_apply(self, tmp_path):
        db, conn = _library(tmp_path)
        preview = _preview(conn, db)
        result = run_auto_cull(conn, db, "_anonymous", **_kwargs(), dry_run=False, state_guard=True,
                               expected_digest=preview.plan_digest, skip_paths=[_p(tmp_path, "b2.jpg")])
        assert result.plan_digest == preview.plan_digest
        assert _rejected(conn) == {"b3.jpg"}
        assert result.skipped_user_changed == [_p(tmp_path, "b2.jpg")]

    def test_a_skip_path_outside_the_plan_is_not_reported(self, tmp_path):
        db, conn = _library(tmp_path)
        preview = _preview(conn, db)
        result = run_auto_cull(conn, db, "_anonymous", **_kwargs(), dry_run=False, state_guard=True,
                               expected_digest=preview.plan_digest, skip_paths=["/elsewhere.jpg"])
        assert result.skipped_user_changed == [] and _rejected(conn) == {"b2.jpg", "b3.jpg"}


class TestMultiUser:
    @pytest.fixture()
    def multi(self, tmp_path, monkeypatch):
        monkeypatch.setitem(api.config._FULL_CONFIG, "users", {
            "alice": {"role": "user", "directories": [str(tmp_path)]},
            "bob": {"role": "user", "directories": [str(tmp_path)]}})
        monkeypatch.setattr("api.db_helpers.is_multi_user_enabled", lambda: True)
        monkeypatch.setattr("api.routers.burst_culling.is_multi_user_enabled", lambda: True)
        return _library(tmp_path)

    @staticmethod
    def _rate(conn, user, path, stars):
        conn.execute("INSERT INTO user_preferences (user_id, photo_path, star_rating) VALUES (?, ?, ?) "
                     "ON CONFLICT(user_id, photo_path) DO UPDATE SET star_rating = excluded.star_rating",
                     (user, path, stars))
        conn.commit()

    def test_another_users_rating_does_not_skip_my_apply(self, tmp_path, multi):
        db, conn = multi
        preview = _preview(conn, db, user="alice")
        self._rate(conn, "bob", _p(tmp_path, "b2.jpg"), 5)
        result = _apply(conn, db, preview, user="alice")
        assert result.skipped_user_changed == []
        assert {r[0] for r in conn.execute(
            "SELECT photo_path FROM user_preferences WHERE user_id = 'alice' AND is_rejected = 1")
        } == {_p(tmp_path, "b2.jpg"), _p(tmp_path, "b3.jpg")}

    def test_my_own_rating_skips_my_apply(self, tmp_path, multi):
        db, conn = multi
        preview = _preview(conn, db, user="alice")
        self._rate(conn, "alice", _p(tmp_path, "b2.jpg"), 5)
        result = _apply(conn, db, preview, user="alice")
        assert result.skipped_user_changed == [_p(tmp_path, "b2.jpg")]
        assert {r[0] for r in conn.execute(
            "SELECT photo_path FROM user_preferences WHERE user_id = 'alice' AND is_rejected = 1")
        } == {_p(tmp_path, "b3.jpg")}


class TestLenientOverrides:
    def test_offending_marks_are_dropped_and_named_instead_of_refused(self, tmp_path):
        db, conn = _library(tmp_path)
        all_three = [_p(tmp_path, n) for n in SCORES]
        with pytest.raises(burst_culling.AutoCullOverrideError):
            run_auto_cull(conn, db, "_anonymous", **_kwargs(), dry_run=True, remove_override=all_three)
        result = run_auto_cull(conn, db, "_anonymous", **_kwargs(), dry_run=True, remove_override=all_three,
                               lenient_overrides=True)
        assert [d["path"] for d in result.dropped_overrides] == [all_three[0]]
        assert result.dropped_overrides[0]['reason'] == 'would_leave_no_keeper'
        plain = run_auto_cull(conn, db, "_anonymous", **_kwargs(), dry_run=True)
        assert result.plan_digest == plain.plan_digest

    def test_a_path_in_both_lists_is_dropped_from_both(self, tmp_path):
        db, conn = _library(tmp_path)
        b2 = _p(tmp_path, "b2.jpg")
        result = run_auto_cull(conn, db, "_anonymous", **_kwargs(), dry_run=True, keep_override=[b2],
                               remove_override=[b2], lenient_overrides=True)
        assert result.dropped_overrides == [{"path": b2, "reason": "in_both_lists"}]


    def test_a_keep_whole_frame_removal_is_dropped_and_reported(self):
        photos = [{"path": "/b/k0.jpg", "sequence_ev_offset": 0},
                  {"path": "/b/k-2.jpg", "sequence_ev_offset": -2},
                  {"path": "/b/k+2.jpg", "sequence_ev_offset": 2}]
        plan = burst_culling._plan_auto_cull_groups(
            [{"type": "bracket", "group_id": 9, "sequence_kind": "bracket", "photos": photos}], set(), 50, 1)
        dropped = []
        effective, ignored = burst_culling._apply_plan_overrides(plan, [], ["/b/k0.jpg"], dropped)
        assert dropped == [{"path": "/b/k0.jpg", "reason": "keep_whole_set"}]
        assert effective == {"keep": [], "remove": []} and ignored == []


class TestPlanChangedByApply:
    """The user applied groups from the tab after the assistant's preview: refused with its own reason."""

    @staticmethod
    def _apply_in_the_tab(conn, keep, reject, kind, user="_anonymous"):
        """What ``POST /api/culling/apply_marks`` does for one group, on this test's connection."""
        group = burst_culling.ApplyGroup(kind=kind, keep_paths=keep, reject_paths=reject)
        by_path = burst_culling._mark_rows(conn, keep + reject, user)
        burst_culling._write_apply_group(conn, group, by_path, user, "1=1", [])
        burst_culling._after_marks_write(conn)
        conn.commit()

    @staticmethod
    def _second_burst(conn, tmp_path):
        for second, (name, score) in enumerate({"c1.jpg": 9.0, "c2.jpg": 3.0}.items()):
            conn.execute(
                "INSERT INTO photos (path, filename, date_taken, aggregate, aesthetic, tech_sharpness, is_blink, "
                "burst_group_id, is_burst_lead) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)",
                (str(tmp_path / name), name, f"2024:06:16 10:00:{second:02d}", score, score, score, BURST + 1,
                 1 if name == "c1.jpg" else 0))
        conn.commit()

    def test_a_burst_group_applied_after_the_preview_is_refused_for_that_reason(self, tmp_path):
        db, conn = _library(tmp_path)
        self._second_burst(conn, tmp_path)
        preview = _preview(conn, db)
        mine = [_p(tmp_path, n) for n in SCORES]
        self._apply_in_the_tab(conn, mine[:1], mine[1:], "burst")
        with pytest.raises(AutoCullPlanChanged) as refusal:
            run_auto_cull(conn, db, "_anonymous", **_kwargs(), dry_run=False, state_guard=True,
                          expected_digest=preview.plan_digest, skip_paths=mine, applied_paths=mine)
        assert str(refusal.value) == burst_culling.PLAN_CHANGED_BY_APPLY
        assert _rejected(conn) == {"b2.jpg", "b3.jpg"}

    def test_the_re_preview_leaves_the_applied_group_out_and_the_rest_applies(self, tmp_path):
        db, conn = _library(tmp_path)
        self._second_burst(conn, tmp_path)
        preview = _preview(conn, db)
        mine = [_p(tmp_path, n) for n in SCORES]
        self._apply_in_the_tab(conn, mine[:1], mine[1:], "burst")
        fresh = _preview(conn, db)
        assert {os.path.basename(p) for p in fresh.reject_paths} == {"c2.jpg"}
        result = run_auto_cull(conn, db, "_anonymous", **_kwargs(), dry_run=False, state_guard=True,
                               expected_digest=fresh.plan_digest, skip_paths=mine, applied_paths=mine)
        assert _rejected(conn) == {"b2.jpg", "b3.jpg", "c2.jpg"}
        assert result.skipped_user_changed == []
        assert preview.plan_digest != fresh.plan_digest

    def test_a_similar_group_applied_after_the_preview_is_refused_even_though_the_others_renumber(self, tmp_path):
        db, conn = _similar_library(tmp_path)
        preview = _preview(conn, db, group_by="similar")
        assert len(preview.preview) == 2
        group_a = [_p(tmp_path, "a1.jpg"), _p(tmp_path, "a2.jpg")]
        self._apply_in_the_tab(conn, group_a[:1], group_a[1:], "similar")
        with pytest.raises(AutoCullPlanChanged) as refusal:
            run_auto_cull(conn, db, "_anonymous", **_kwargs(group_by="similar"), dry_run=False, state_guard=True,
                          expected_digest=preview.plan_digest, skip_paths=group_a, applied_paths=group_a)
        assert str(refusal.value) == burst_culling.PLAN_CHANGED_BY_APPLY
        fresh = _preview(conn, db, group_by="similar")
        assert len(fresh.preview) == 1
        run_auto_cull(conn, db, "_anonymous", **_kwargs(group_by="similar"), dry_run=False, state_guard=True,
                      expected_digest=fresh.plan_digest, skip_paths=group_a, applied_paths=group_a)
        assert _rejected(conn) == {"a2.jpg", "b2.jpg"}

    def test_without_a_snapshot_the_existing_refusal_text_is_returned(self, tmp_path, clock):
        db, conn = _library(tmp_path)
        preview = _preview(conn, db)
        clock[0] += burst_culling.GUARD_TTL_S + 1
        mine = [_p(tmp_path, n) for n in SCORES]
        self._apply_in_the_tab(conn, mine[:1], mine[1:], "burst")
        with pytest.raises(AutoCullPlanChanged) as refusal:
            run_auto_cull(conn, db, "_anonymous", **_kwargs(), dry_run=False, state_guard=True,
                          expected_digest=preview.plan_digest, applied_paths=mine)
        assert str(refusal.value) != burst_culling.PLAN_CHANGED_BY_APPLY
        assert str(refusal.value).startswith("The plan changed since it was previewed")

    def test_applied_paths_outside_the_preview_do_not_change_the_refusal(self, tmp_path):
        db, conn = _library(tmp_path)
        preview = _preview(conn, db)
        conn.execute("UPDATE photos SET aggregate = 9.9, aesthetic = 9.9, tech_sharpness = 9.9 WHERE path = ?",
                     (_p(tmp_path, "b3.jpg"),))
        conn.commit()
        with pytest.raises(AutoCullPlanChanged) as refusal:
            run_auto_cull(conn, db, "_anonymous", **_kwargs(), dry_run=False, state_guard=True,
                          expected_digest=preview.plan_digest, applied_paths=["/elsewhere.jpg"])
        assert str(refusal.value).startswith("The plan changed since it was previewed")

    def test_the_route_accepts_applied_paths_and_caps_them(self, edition_client, seed_photos_prefix):
        prefix = AGENT_DIR + "guard-applied/"
        rows = [{"path": prefix + n, "filename": n, "date_taken": f"1997:01:01 10:00:0{i}", "aggregate": s,
                 "aesthetic": s, "tech_sharpness": s, "burst_group_id": 5252, "is_burst_lead": 1 if i == 1 else 0}
                for i, (n, s) in enumerate(SCORES.items(), start=1)]
        seed_photos_prefix(prefix, rows)
        body = {"group_by": "burst", "strictness": 0, "date_from": "1997:01:01 00:00:00",
                "date_to": "1997:01:01 23:59:59"}
        preview = edition_client.post("/api/culling/auto", json=body)
        assert preview.status_code == 200, preview.text
        applied = edition_client.post("/api/culling/auto", json={
            **body, "dry_run": False, "expected_digest": preview.json()["plan_digest"],
            "applied_paths": [prefix + "b2.jpg"]})
        assert applied.status_code == 200, applied.text
        assert applied.json()["skipped_user_changed"] == [prefix + "b2.jpg"]
        too_many = edition_client.post("/api/culling/auto", json={**body, "applied_paths": ["/x"] * 1001})
        assert too_many.status_code == 422


class TestAppliedInPlan:
    """A dry run sent ``applied_paths`` counts the planned keeps / rejects the user already applied."""

    def test_the_counts_cover_the_full_plan_and_the_digest_ignores_applied_paths(self, tmp_path):
        db, conn = _library(tmp_path)
        mine = [_p(tmp_path, n) for n in SCORES]
        plain = _preview(conn, db)
        with_applied = _preview(conn, db, applied_paths=[mine[0], mine[2], "/elsewhere.jpg"])
        assert with_applied.applied_in_plan == {"kept": 1, "rejected": 2}
        assert (with_applied.kept, with_applied.rejected) == (plain.kept, plain.rejected)
        assert with_applied.plan_digest == plain.plan_digest

    def test_none_of_them_in_the_plan_leaves_the_field_unset(self, tmp_path):
        db, conn = _library(tmp_path)
        assert _preview(conn, db, applied_paths=["/elsewhere.jpg"]).applied_in_plan is None
        assert _preview(conn, db).applied_in_plan is None

    def test_the_route_returns_applied_in_plan_on_a_dry_run_and_omits_it_otherwise(
            self, edition_client, seed_photos_prefix):
        prefix = AGENT_DIR + "guard-in-plan/"
        rows = [{"path": prefix + n, "filename": n, "date_taken": f"1996:01:01 10:00:0{i}", "aggregate": s,
                 "aesthetic": s, "tech_sharpness": s, "burst_group_id": 5353, "is_burst_lead": 1 if i == 1 else 0}
                for i, (n, s) in enumerate(SCORES.items(), start=1)]
        seed_photos_prefix(prefix, rows)
        body = {"group_by": "burst", "strictness": 0, "date_from": "1996:01:01 00:00:00",
                "date_to": "1996:01:01 23:59:59"}
        plain = edition_client.post("/api/culling/auto", json=body)
        assert plain.status_code == 200, plain.text
        assert "applied_in_plan" not in plain.json()
        sent = edition_client.post("/api/culling/auto", json={
            **body, "applied_paths": [prefix + "b3.jpg", prefix + "b1.jpg"]})
        assert sent.status_code == 200, sent.text
        assert sent.json()["applied_in_plan"] == {"kept": 1, "rejected": 2}
        assert sent.json()["plan_digest"] == plain.json()["plan_digest"]
        assert sent.json()["kept"] == plain.json()["kept"] and sent.json()["rejected"] == plain.json()["rejected"]
        elsewhere = edition_client.post("/api/culling/auto", json={**body, "applied_paths": ["/x.jpg"]})
        assert "applied_in_plan" not in elsewhere.json()


class TestHttp:
    def test_skip_paths_and_the_report_ride_the_route(self, edition_client, seed_photos_prefix):
        prefix = AGENT_DIR + "guard/"
        rows = [{"path": prefix + n, "filename": n, "date_taken": f"1998:01:01 10:00:0{i}", "aggregate": s,
                 "aesthetic": s, "tech_sharpness": s, "burst_group_id": 5151, "is_burst_lead": 1 if i == 1 else 0}
                for i, (n, s) in enumerate(SCORES.items(), start=1)]
        seed_photos_prefix(prefix, rows)
        body = {"group_by": "burst", "strictness": 0, "date_from": "1998:01:01 00:00:00",
                "date_to": "1998:01:01 23:59:59"}
        preview = edition_client.post("/api/culling/auto", json=body)
        assert preview.status_code == 200, preview.text
        applied = edition_client.post("/api/culling/auto", json={
            **body, "dry_run": False, "expected_digest": preview.json()["plan_digest"],
            "skip_paths": [prefix + "b2.jpg"]})
        assert applied.status_code == 200, applied.text
        assert applied.json()["skipped_user_changed"] == [prefix + "b2.jpg"]
        assert applied.json()["skipped_user_changed_count"] == 1


class TestRejectedPathsOnTheRoute:
    """``rejected_paths`` feeds the tab's "Show photos"; the frame's ``paths`` stays null so the tab reloads."""

    PREFIX = AGENT_DIR + "showpaths/"
    BODY = {"group_by": "burst", "strictness": 0, "date_from": "1997:01:01 00:00:00",
            "date_to": "1997:01:01 23:59:59"}

    @pytest.fixture()
    def library(self, seed_photos_prefix):
        scores = {"s1.jpg": 9.0, "s2.jpg": 5.0, "s3.jpg": 3.0, "s4.jpg": 1.0}
        seed_photos_prefix(self.PREFIX, [
            {"path": self.PREFIX + n, "filename": n, "date_taken": f"1997:01:01 10:00:0{i}", "aggregate": s,
             "aesthetic": s, "tech_sharpness": s, "burst_group_id": 6161, "is_burst_lead": 1 if i == 1 else 0}
            for i, (n, s) in enumerate(scores.items(), start=1)])
        return [self.PREFIX + n for n in ("s3.jpg", "s4.jpg")]

    def _apply(self, client):
        preview = client.post("/api/culling/auto", json=self.BODY)
        assert preview.status_code == 200, preview.text
        assert "rejected_paths" not in preview.json()
        return preview, client.post("/api/culling/auto", json={
            **self.BODY, "dry_run": False, "expected_digest": preview.json()["plan_digest"]})

    def test_an_apply_lists_the_rejected_paths_and_the_frame_carries_show_paths(self, edition_client, library):
        from api.agent.live_updates import frame_for
        _, applied = self._apply(edition_client)
        assert applied.status_code == 200, applied.text
        body = applied.json()
        assert sorted(body["rejected_paths"]) == sorted(library)
        frame = frame_for("culling.auto", {"dry_run": False}, body)
        assert frame["paths"] is None and sorted(frame["show_paths"]) == sorted(library)

    def test_over_the_cap_the_route_lists_nothing(self, edition_client, library, monkeypatch):
        from api.agent import live_updates
        from api.agent.live_updates import frame_for
        monkeypatch.setattr(live_updates, "MAX_LIVE_PATHS", 1)
        _, applied = self._apply(edition_client)
        assert applied.status_code == 200, applied.text
        body = applied.json()
        assert body["rejected"] == 2 and body.get("rejected_paths") is None
        assert frame_for("culling.auto", {"dry_run": False}, body)["show_paths"] is None

    def test_exactly_at_the_cap_the_route_still_lists_the_paths(self, edition_client, library, monkeypatch):
        from api.agent import live_updates
        monkeypatch.setattr(live_updates, "MAX_LIVE_PATHS", 2)
        _, applied = self._apply(edition_client)
        assert applied.status_code == 200, applied.text
        assert sorted(applied.json()["rejected_paths"]) == sorted(library)

    def test_an_apply_that_rejects_nothing_has_no_show_paths(self, edition_client, library):
        from api.agent.live_updates import frame_for
        preview = edition_client.post("/api/culling/auto", json=self.BODY)
        assert preview.status_code == 200, preview.text
        applied = edition_client.post("/api/culling/auto", json={
            **self.BODY, "dry_run": False, "expected_digest": preview.json()["plan_digest"],
            "skip_paths": library})
        assert applied.status_code == 200, applied.text
        body = applied.json()
        assert body["rejected"] == 0
        frame = frame_for("culling.auto", {"dry_run": False}, body)
        assert frame["paths"] is None and frame["show_paths"] is None


class TestGuardBuild:
    """The snapshot is built outside ``_guard_lock``, tags once, capped, through the shared label reader."""

    def test_a_slow_label_read_does_not_block_another_threads_lookup(self, tmp_path, monkeypatch):
        import threading
        import api.db_helpers as helpers
        db, conn = _library(tmp_path)
        started, release = threading.Event(), threading.Event()
        original = helpers._read_label_tuples

        def slow(*args, **kwargs):
            started.set()
            assert release.wait(10)
            return original(*args, **kwargs)
        monkeypatch.setattr(helpers, "_read_label_tuples", slow)

        def preview_in_thread():
            own = sqlite3.connect(db)
            own.row_factory = sqlite3.Row
            _preview(own, db)
        worker = threading.Thread(target=preview_in_thread)
        worker.start()
        try:
            assert started.wait(10)
            probe = threading.Thread(target=lambda: burst_culling.state_guard_has("_anonymous", "x"))
            probe.start()
            probe.join(2)
            assert not probe.is_alive(), "state_guard_has blocked behind a label read"
        finally:
            release.set()
            worker.join(10)

    def test_plan_tags_is_computed_once_per_remember_and_per_reconcile(self, tmp_path, monkeypatch):
        db, conn = _library(tmp_path)
        calls = []
        original = burst_culling._plan_tags
        monkeypatch.setattr(burst_culling, "_plan_tags", lambda plan: calls.append(1) or original(plan))
        preview = _preview(conn, db)
        assert len(calls) == 1
        del calls[:]
        _apply(conn, db, preview)
        assert len(calls) == 1

    def test_a_later_page_with_a_live_snapshot_reads_no_labels(self, tmp_path, monkeypatch):
        import api.db_helpers as helpers
        db, conn = _library(tmp_path)
        _preview(conn, db)
        reads = []
        original = helpers._read_label_tuples
        monkeypatch.setattr(helpers, "_read_label_tuples", lambda *a, **k: reads.append(1) or original(*a, **k))
        _preview(conn, db)
        assert reads == []

    def test_a_plan_above_the_cap_stores_nothing_and_says_unavailable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(burst_culling, "GUARD_MAX_PATHS", 2)
        db, conn = _library(tmp_path)
        preview = _preview(conn, db)
        assert preview.state_guard == "unavailable"
        assert not burst_culling.state_guard_has("_anonymous", preview.plan_digest)
        assert _apply(conn, db, preview).state_guard == "unavailable"

    def test_a_plan_at_the_cap_is_stored(self, tmp_path, monkeypatch):
        monkeypatch.setattr(burst_culling, "GUARD_MAX_PATHS", len(SCORES))
        db, conn = _library(tmp_path)
        preview = _preview(conn, db)
        assert preview.state_guard is None
        assert burst_culling.state_guard_has("_anonymous", preview.plan_digest)

    def test_the_private_label_reader_is_gone(self):
        import pathlib
        root = pathlib.Path(burst_culling.__file__).resolve().parents[1]
        hits = [str(p) for p in root.rglob("*.py") if "_label_fingerprints" in p.read_text()]
        assert hits == []
