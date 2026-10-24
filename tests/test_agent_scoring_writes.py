"""Scoring tools, phase 2 (apply, snapshots, recompute, learned weights, category fixes) over /mcp.

[REAL] ``agent_app`` (real auth chain), the real comparison / scan / critique routes, rows seeded into the shared
session DB. Redirected, never mocked: the server's scoring-config PATH (a module-level path, not an auth dependency)
to a scratch file, so the real ``update_weights`` / ``restore_weights`` routes write it instead of the install's;
the scan router's ``Popen`` (the OS boundary); and the optimizer class the learned-weights route constructs.
"""

import importlib
import json
import pathlib
import sqlite3
import subprocess
from collections import deque
from types import SimpleNamespace

import pytest

from tests.conftest import _TEST_DB_FILE, AGENT_DIR, agent_db as db, intercept_internal_call

PREFIX = AGENT_DIR + "scorew/"
scan = importlib.import_module("api.routers.scan")
METRICS = {"aesthetic": 7.0, "face_quality": 6.0, "eye_sharpness": 6.0, "tech_sharpness": 6.5, "comp_score": 5.5,
           "exposure_score": 8.0, "color_score": 6.0, "contrast_score": 6.0, "quality_score": 6.0,
           "liqe_score": 6.0, "aesthetic_iaa": 6.0, "face_quality_iqa": 6.0, "isolation_bonus": 1.5,
           "face_count": 0, "face_ratio": 0.0, "category": "base", "aggregate": 6.5}
# Two categories, so the written file and the signals are fully determined: `wide` wins on face_ratio >= 0.10.
CATEGORIES = [
    {"name": "wide", "priority": 10, "filters": {"face_ratio_min": 0.10},
     "weights": {"aesthetic_percent": 50, "composition_percent": 50}},
    {"name": "base", "priority": 999, "filters": {},
     "weights": {"aesthetic_percent": 60, "composition_percent": 40}},
]


def row(name, **extra):
    return {"path": PREFIX + name, "filename": name, **METRICS, **extra}


PHOTOS = [row(f"b{i}.jpg", aesthetic=3.0 + i, aggregate=3.0 + i, comp_score=9.0 - 1.5 * i) for i in range(5)]


def write_config(cfg, categories=None, **extra):
    cfg.write_text(json.dumps({"categories": categories if categories is not None else CATEGORIES, **extra}))


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """A scratch scoring_config.json the real routes read and write instead of the install's."""
    from api import config as api_config
    from api.routers import comparison
    cfg = tmp_path / "scoring_config.json"
    write_config(cfg)
    monkeypatch.setattr(api_config, "_CONFIG_PATH", str(cfg))
    monkeypatch.setattr(comparison, "_CONFIG_PATH", str(cfg))
    monkeypatch.setattr(comparison, "reload_config", lambda: None)
    first = db("SELECT COALESCE(MAX(id), 0) FROM weight_config_snapshots")[0][0]
    yield cfg
    db("DELETE FROM weight_config_snapshots WHERE id > ?", first)
    db("DELETE FROM photo_scoring_overrides WHERE photo_path LIKE ?", PREFIX + "%")


@pytest.fixture()
def world(agent_app, seed_photos_prefix, sandbox):
    seed_photos_prefix(PREFIX, PHOTOS)
    env = agent_app("legacy")
    return env, env.token(env.login(edition=True), "edition"), env.token(env.login(), "readonly"), sandbox


def stored_weights(cfg, category="base"):
    from config_resolve import load_resolved
    return next(c for c in load_resolved(str(cfg))["categories"] if c["name"] == category)["weights"]


def edit_by_hand(cfg, category="base", **changed):
    from api.config import write_user_config
    from config_resolve import load_resolved
    data = load_resolved(str(cfg))
    next(c for c in data["categories"] if c["name"] == category)["weights"].update(changed)
    write_user_config(str(cfg), data)


def snapshots():
    return db("SELECT COUNT(*) FROM weight_config_snapshots")[0][0]


def snap(category, weights, *, by="manual", bonus=None, when="2026-01-01 00:00:00"):
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        return conn.execute(
            "INSERT INTO weight_config_snapshots (category, timestamp, weights, created_by, category_bonus) "
            "VALUES (?, ?, ?, ?, ?)", (category, when, json.dumps(weights), by, bonus)).lastrowid


DELTAS = {"aesthetic": -10, "color": 10}


def preview(env, token, deltas=None, category="base"):
    got = env.call(token, "preview_weights", {"category": category, "deltas": deltas or DELTAS, "sample": 5})
    assert got["ok"], got
    return got["data"]["preview_digest"]


def apply(env, token, digest, deltas=None, category="base", **extra):
    return env.call(token, "apply_weights", {"category": category, "deltas": deltas or DELTAS,
                                             "preview_digest": digest, **extra})


class TestApplyWeights:
    def test_without_a_digest_nothing_is_written(self, world, monkeypatch):
        env, edition, _, cfg = world
        seen = []
        intercept_internal_call(monkeypatch, lambda tool, kw: seen.append(tool))
        before = cfg.read_bytes(), snapshots()
        for digest in (None, "not-a-digest"):
            args = {"category": "base", "deltas": DELTAS, **({} if digest is None else {"preview_digest": digest})}
            assert env.call(edition, "apply_weights", args)["error"] == "confirmation_required"
        assert "update_weights" not in seen and (cfg.read_bytes(), snapshots()) == before

    def test_a_config_edited_after_the_preview_makes_it_stale(self, world):
        env, edition, _, cfg = world
        digest = preview(env, edition)
        edit_by_hand(cfg, aesthetic_percent=55)
        refused = apply(env, edition, digest)
        assert refused["error"] == "confirmation_required" and "preview again" in refused["message"]
        assert stored_weights(cfg)["aesthetic_percent"] == 55

    def test_preview_then_apply_changes_the_weights_and_snapshots_the_old_ones(self, world):
        env, edition, _, cfg = world
        digest = preview(env, edition)
        aggregates = db("SELECT path, aggregate FROM photos WHERE path LIKE ? ORDER BY path", PREFIX + "%")
        result = apply(env, edition, digest)
        assert result["ok"], result
        data = result["data"]
        assert data["verified"] is True and data["scores_stale"] is True and data["next"] == "recompute_scores"
        assert data["previous"] == {"aesthetic_percent": 60, "color_percent": 0}
        assert data["applied"] == {"aesthetic_percent": 50, "color_percent": 10}
        assert data["reload_compare"] is True and "reload /compare" in data["note"]
        assert data["snapshot"]["created_by"] == "auto:edit"
        saved = db("SELECT weights, created_by FROM weight_config_snapshots WHERE id = ?", data["snapshot"]["id"])
        assert json.loads(saved[0][0]) == {"aesthetic_percent": 60, "composition_percent": 40}
        assert saved[0][1] == "auto:edit"
        assert stored_weights(cfg) == {"aesthetic_percent": 50, "composition_percent": 40, "color_percent": 10}
        assert db("SELECT path, aggregate FROM photos WHERE path LIKE ? ORDER BY path", PREFIX + "%") == aggregates

    def test_a_read_back_that_differs_from_the_proposal_is_not_verified(self, world, monkeypatch):
        from api.agent.internal_client import ok
        env, edition, _, _ = world
        digest = preview(env, edition)
        written = []

        def stale_read_back(tool, kw):
            if tool == "update_weights":
                written.append(True)
            if tool == "category_weights" and written:
                return ok({"weights": {"aesthetic_percent": 60, "composition_percent": 40}})
            return None

        intercept_internal_call(monkeypatch, stale_read_back)
        result = apply(env, edition, digest)
        assert result["ok"] and written, result
        assert result["data"]["verified"] is False

    def test_a_failed_read_back_is_not_verified(self, world, monkeypatch):
        from api.agent.internal_client import err
        env, edition, _, _ = world
        digest = preview(env, edition)
        written = []

        def failing_read_back(tool, kw):
            if tool == "update_weights":
                written.append(True)
            if tool == "category_weights" and written:
                return err("upstream_error", "boom")
            return None

        intercept_internal_call(monkeypatch, failing_read_back)
        result = apply(env, edition, digest)
        assert result["ok"] and result["data"]["verified"] is False

    def test_a_write_with_no_new_snapshot_warns_that_undo_is_not_guaranteed(self, world, monkeypatch):
        from api.agent.internal_client import ok
        env, edition, _, cfg = world
        digest = preview(env, edition)
        intercept_internal_call(monkeypatch, lambda tool, kw: ok({"snapshots": []}) if tool == "weight_snapshots" else None)
        result = apply(env, edition, digest)
        assert result["ok"], result
        assert result["data"]["snapshot"] is None
        assert "no_undo_snapshot" in [w["code"] for w in result["data"]["warnings"]]
        assert stored_weights(cfg)["aesthetic_percent"] == 50

    def test_only_the_configured_keys_and_the_changed_ones_are_sent_never_the_zero_padding(self, world, monkeypatch):
        env, edition, _, cfg = world
        sent = []
        intercept_internal_call(monkeypatch, lambda tool, kw: sent.append(kw.get("json")) if tool == "update_weights" else None)
        digest = preview(env, edition)
        assert apply(env, edition, digest)["ok"]
        assert sent == [{"category": "base", "recalculate": False,
                         "weights": {"aesthetic_percent": 50, "composition_percent": 40, "color_percent": 10}}]
        assert "modifiers" not in sent[0] and "filters" not in sent[0]

    def test_the_written_file_resolves_to_the_intended_config(self, world):
        from config_resolve import load_resolved
        env, edition, _, cfg = world
        digest = preview(env, edition)
        assert apply(env, edition, digest)["ok"]
        resolved = load_resolved(str(cfg))
        base = next(c for c in resolved["categories"] if c["name"] == "base")
        assert base["weights"] == {"aesthetic_percent": 50, "composition_percent": 40, "color_percent": 10}
        assert [c["name"] for c in resolved["categories"]] == ["wide", "base"]
        assert resolved["viewer"] is not None

    def test_a_digest_for_another_category_is_refused(self, world):
        env, edition, _, cfg = world
        # Both categories start from the same weights, so only the category can tell the two proposals apart.
        write_config(cfg, [{**CATEGORIES[0], "weights": CATEGORIES[1]["weights"]}, CATEGORIES[1]])
        digest = preview(env, edition, category="base")
        before = cfg.read_bytes(), snapshots()
        refused = apply(env, edition, digest, category="wide")
        assert refused["error"] == "confirmation_required" and (cfg.read_bytes(), snapshots()) == before

    def test_a_digest_for_other_deltas_of_the_same_category_is_refused(self, world):
        env, edition, _, cfg = world
        digest = preview(env, edition)
        before = cfg.read_bytes(), snapshots()
        refused = apply(env, edition, digest, deltas={"aesthetic": -5, "color": 5})
        assert refused["error"] == "confirmation_required" and (cfg.read_bytes(), snapshots()) == before
        same_total_other_keys = apply(env, edition, digest, deltas={"aesthetic": -10, "contrast": 10})
        assert same_total_other_keys["error"] == "confirmation_required" and cfg.read_bytes() == before[0]

    def test_a_digest_is_single_use(self, world):
        env, edition, _, cfg = world
        digest = preview(env, edition)
        assert apply(env, edition, digest)["ok"]
        edit_by_hand(cfg, aesthetic_percent=60, color_percent=0)
        again = apply(env, edition, digest)
        assert again["error"] == "confirmation_required"
        assert stored_weights(cfg)["aesthetic_percent"] == 60

    def test_another_tokens_digest_is_refused_and_not_burned(self, world):
        env, edition, _, cfg = world
        other = env.token(env.login(edition=True), "edition", "second")
        digest = preview(env, edition)
        assert apply(env, other, digest)["error"] == "confirmation_required"
        assert stored_weights(cfg)["aesthetic_percent"] == 60
        assert apply(env, edition, digest)["ok"]

    def test_a_readonly_token_is_refused_before_any_route_call(self, world, monkeypatch):
        env, _, readonly, cfg = world
        calls = []
        intercept_internal_call(monkeypatch, lambda tool, kw: calls.append(tool))
        before = cfg.read_bytes()
        refused = env.call(readonly, "apply_weights", {"category": "base", "deltas": DELTAS, "preview_digest": "x"})
        assert refused["error"] == "forbidden_level" and calls == [] and cfg.read_bytes() == before

    def test_bonus_and_bad_values_are_refused_before_the_digest_is_looked_at(self, world, monkeypatch):
        env, edition, _, cfg = world
        seen = []
        intercept_internal_call(monkeypatch, lambda tool, kw: seen.append(tool))
        digest = preview(env, edition)
        bad = env.call(edition, "apply_weights", {"category": "base", "weights": {"bonus": 1, "aesthetic": 500},
                                                  "preview_digest": digest})
        assert bad["error"] == "invalid_input" and len(bad["issues"]) == 2 and "update_weights" not in seen
        assert apply(env, edition, digest)["ok"]

    def test_warnings_for_an_odd_sum_and_a_typo_travel_into_the_result(self, world):
        env, edition, _, cfg = world
        deltas = {"aesthetic": -30, "aestethic": 3}
        digest = preview(env, edition, deltas)
        data = apply(env, edition, digest, deltas)["data"]
        assert {w["code"] for w in data["warnings"]} == {"sum_outside_95_105", "unknown_key"}
        assert stored_weights(cfg)["aestethic_percent"] == 3

    def test_a_timeout_is_reported_as_unknown_and_the_digest_is_spent(self, world, monkeypatch):
        from api.agent.internal_client import err
        env, edition, _, cfg = world
        digest = preview(env, edition)
        intercept_internal_call(monkeypatch, lambda tool, kw: err("outcome_unknown", "timed out")
                                if tool == "update_weights" else None)
        assert apply(env, edition, digest)["error"] == "outcome_unknown"
        assert apply(env, edition, digest)["error"] == "confirmation_required"

    def test_an_apply_records_no_comparison_and_arms_no_retrain(self, world, monkeypatch):
        from api import db_helpers
        from api.routers import comparison
        env, edition, _, cfg = world
        nudges = []
        for module in (db_helpers, comparison):
            if hasattr(module, "trigger_auto_retrain"):
                monkeypatch.setattr(module, "trigger_auto_retrain", lambda *a, **k: nudges.append(a))
        before = db("SELECT COUNT(*) FROM comparisons")
        assert apply(env, edition, preview(env, edition))["ok"]
        assert db("SELECT COUNT(*) FROM comparisons") == before and nudges == []


class TestSnapshots:
    def test_the_list_is_paginated_newest_first_and_flags_what_can_be_restored(self, world):
        env, edition, _, _ = world
        first = snap("base", {"aesthetic_percent": 10, "composition_percent": 0}, when="2026-01-01 00:00:00")
        second = snap("base", {"aesthetic": 0.4, "bonus": 0.1}, when="2026-01-02 00:00:00")
        third = snap("base", {"aesthetic_percent": 30}, when="2026-01-03 00:00:00", bonus=0.5)
        snap("wide", {"aesthetic_percent": 99}, when="2026-01-04 00:00:00")
        page = env.call(edition, "list_weight_snapshots", {"category": "base", "limit": 2})["data"]
        assert [s["id"] for s in page["snapshots"]] == [third, second] and page["has_more"] is True
        assert page["snapshots"][0]["weights"] == {"aesthetic_percent": 30}
        assert page["snapshots"][0]["category_bonus"] == 0.5 and page["snapshots"][0]["restorable"] is True
        assert page["snapshots"][1]["restorable"] is False and "_percent" in page["snapshots"][1]["not_restorable_reason"]
        assert page["snapshots"][0]["weights"] and set(page["snapshots"][0]) >= {
            "id", "category", "timestamp", "created_by", "description", "accuracy_before", "accuracy_after",
            "comparisons_used"}
        last = env.call(edition, "list_weight_snapshots", {"category": "base", "limit": 2, "offset": 2})["data"]
        assert [s["id"] for s in last["snapshots"]] == [first] and last["has_more"] is False
        assert env.call(edition, "list_weight_snapshots", {"limit": 101})["error"] == "invalid_input"
        # a zero weight is not listed
        assert "composition_percent" not in last["snapshots"][0]["weights"]

    def test_a_dry_run_writes_nothing_and_a_real_run_needs_its_confirm(self, world):
        env, edition, _, cfg = world
        sid = snap("base", {"aesthetic_percent": 20, "composition_percent": 80})
        before = cfg.read_bytes(), snapshots()
        dry = env.call(edition, "restore_weight_snapshot", {"snapshot_id": sid})
        assert dry["ok"], dry
        data = dry["data"]
        assert data["would_change"] == {"aesthetic_percent": {"from": 60, "to": 20},
                                        "composition_percent": {"from": 40, "to": 80}}
        assert data["confirm"] and data["snapshot"]["id"] == sid and data["weights_sum_after"] == 100
        assert (cfg.read_bytes(), snapshots()) == before
        refused = env.call(edition, "restore_weight_snapshot", {"snapshot_id": sid, "dry_run": False})
        assert refused["error"] == "confirmation_required" and (cfg.read_bytes(), snapshots()) == before
        wrong = env.call(edition, "restore_weight_snapshot", {"snapshot_id": sid, "dry_run": False, "confirm": "zz"})
        assert wrong["error"] == "confirmation_required"

    def test_a_confirmed_restore_round_trips_through_its_own_undo_snapshot(self, world):
        env, edition, _, cfg = world
        sid = snap("base", {"aesthetic_percent": 20, "composition_percent": 80})
        confirm = env.call(edition, "restore_weight_snapshot", {"snapshot_id": sid})["data"]["confirm"]
        done = env.call(edition, "restore_weight_snapshot",
                        {"snapshot_id": sid, "dry_run": False, "confirm": confirm})
        assert done["ok"], done
        assert done["data"]["verified"] is True and done["data"]["scores_stale"] is True
        assert stored_weights(cfg) == {"aesthetic_percent": 20, "composition_percent": 80}
        undo = done["data"]["undo_snapshot_id"]
        saved = db("SELECT weights, created_by FROM weight_config_snapshots WHERE id = ?", undo)
        assert saved[0][1] == "auto:pre_restore"
        assert json.loads(saved[0][0]) == {"aesthetic_percent": 60, "composition_percent": 40}
        back = env.call(edition, "restore_weight_snapshot", {"snapshot_id": undo})["data"]["confirm"]
        assert env.call(edition, "restore_weight_snapshot",
                        {"snapshot_id": undo, "dry_run": False, "confirm": back})["ok"]
        assert stored_weights(cfg) == {"aesthetic_percent": 60, "composition_percent": 40}

    def test_a_restore_whose_weights_moved_since_the_dry_run_is_refused(self, world):
        env, edition, _, cfg = world
        sid = snap("base", {"aesthetic_percent": 20, "composition_percent": 80})
        confirm = env.call(edition, "restore_weight_snapshot", {"snapshot_id": sid})["data"]["confirm"]
        edit_by_hand(cfg, aesthetic_percent=61)
        refused = env.call(edition, "restore_weight_snapshot", {"snapshot_id": sid, "dry_run": False, "confirm": confirm})
        assert refused["error"] == "confirmation_required" and stored_weights(cfg)["aesthetic_percent"] == 61

    def test_a_null_bonus_leaves_the_bonus_and_a_recorded_one_gives_it_back(self, world):
        env, edition, _, cfg = world
        write_config(cfg, [CATEGORIES[0], {**CATEGORIES[1], "modifiers": {"bonus": 0.5}}])

        def bonus():
            return env.call(edition, "category_weights", {"category": "base"})["data"]["modifiers"].get("bonus")

        def restore(sid):
            dry = env.call(edition, "restore_weight_snapshot", {"snapshot_id": sid})["data"]
            done = env.call(edition, "restore_weight_snapshot",
                            {"snapshot_id": sid, "dry_run": False, "confirm": dry["confirm"]})
            assert done["ok"], done
            return dry

        restore(snap("base", {"aesthetic_percent": 70, "composition_percent": 30}, bonus=None))
        assert bonus() == 0.5
        dry = restore(snap("base", {"aesthetic_percent": 80, "composition_percent": 20}, bonus=1.0))
        assert bonus() == 1.0 and dry["bonus_change"] == {"from": 0.5, "to": 1.0}

    def test_a_decimal_or_unknown_key_snapshot_is_refused_on_both_runs_and_nothing_changes(self, world):
        env, edition, _, cfg = world
        before = cfg.read_bytes(), snapshots()
        for weights in ({"aesthetic": 0.4, "composition": 0.6, "bonus": 0.5},
                        {"aesthetic_percent": 40, "aestethic_percent": 60}):
            sid = snap("base", weights)
            dry = env.call(edition, "restore_weight_snapshot", {"snapshot_id": sid})
            real = env.call(edition, "restore_weight_snapshot", {"snapshot_id": sid, "dry_run": False, "confirm": "x"})
            assert dry["error"] == real["error"] == "unsupported_snapshot", (dry, real)
            assert "confirm" not in json.dumps(dry)
            db("DELETE FROM weight_config_snapshots WHERE id = ?", sid)
        assert (cfg.read_bytes(), snapshots()) == before

    def test_a_corrupt_snapshot_is_refused_before_the_route_is_asked(self, world):
        env, edition, _, cfg = world
        with sqlite3.connect(_TEST_DB_FILE.name) as conn:
            sid = conn.execute("INSERT INTO weight_config_snapshots (category, timestamp, weights, created_by) "
                               "VALUES ('base', '2026-01-01 00:00:00', 'not json', 'manual')").lastrowid
        before = cfg.read_bytes()
        out = env.call(edition, "restore_weight_snapshot", {"snapshot_id": sid, "dry_run": False, "confirm": "x"})
        assert out["error"] == "unsupported_snapshot" and cfg.read_bytes() == before

    def test_a_snapshot_of_a_removed_category_is_not_found(self, world):
        env, edition, _, cfg = world
        sid = snap("zzz-gone", {"aesthetic_percent": 100})
        dry = env.call(edition, "restore_weight_snapshot", {"snapshot_id": sid})
        assert dry["error"] == "not_found" and "zzz-gone" in dry["message"]

    def test_an_id_beyond_the_searched_window_is_not_found_and_says_so(self, world, monkeypatch):
        from api.agent import tools_scoring
        env, edition, _, _ = world
        monkeypatch.setattr(tools_scoring, "SNAPSHOT_PAGE_SIZE", 1)
        monkeypatch.setattr(tools_scoring, "SNAPSHOT_PAGES", 2)
        oldest = snap("base", {"aesthetic_percent": 1}, when="2026-01-01 00:00:00")
        snap("base", {"aesthetic_percent": 2}, when="2026-01-02 00:00:00")
        snap("base", {"aesthetic_percent": 3}, when="2026-01-03 00:00:00")
        missing = env.call(edition, "restore_weight_snapshot", {"snapshot_id": oldest})
        assert missing["error"] == "not_found" and "newest 2" in missing["message"] and missing["nearest_ids"]
        absent = env.call(edition, "restore_weight_snapshot", {"snapshot_id": 987654})
        assert absent["error"] == "not_found"

    def test_not_found_offers_the_newest_ids_not_the_oldest(self, world, monkeypatch):
        from api.agent import tools_scoring
        env, edition, _, _ = world
        monkeypatch.setattr(tools_scoring, "SNAPSHOT_PAGE_SIZE", 3)
        monkeypatch.setattr(tools_scoring, "SNAPSHOT_PAGES", 2)
        ids = [snap("base", {"aesthetic_percent": i + 1}, when=f"2026-01-0{i + 1} 00:00:00") for i in range(8)]
        missing = env.call(edition, "restore_weight_snapshot", {"snapshot_id": 987654})
        assert missing["nearest_ids"] == ids[::-1][:5]

    def test_a_recorded_bonus_of_zero_over_a_category_without_one_is_no_change_and_writes_none(self, world):
        env, edition, _, cfg = world
        sid = snap("base", {"aesthetic_percent": 20, "composition_percent": 80}, bonus=0.0)
        dry = env.call(edition, "restore_weight_snapshot", {"snapshot_id": sid})["data"]
        assert dry["bonus_change"] is None
        done = env.call(edition, "restore_weight_snapshot", {"snapshot_id": sid, "dry_run": False, "confirm": dry["confirm"]})
        assert done["ok"] and done["data"]["verified"] is True
        raw = json.loads(cfg.read_text())
        assert "bonus" not in (next(c for c in raw["categories"] if c["name"] == "base").get("modifiers") or {})

    def test_a_restore_that_cannot_read_the_snapshot_list_reports_the_undo_as_unknown(self, world, monkeypatch):
        from api.agent.internal_client import err
        env, edition, _, cfg = world
        sid = snap("base", {"aesthetic_percent": 20, "composition_percent": 80})
        dry = env.call(edition, "restore_weight_snapshot", {"snapshot_id": sid})["data"]
        reads = []

        def fail_after_the_first(tool, kw):
            if tool == "weight_snapshots":
                reads.append(kw.get("query", {}).get("limit"))
                return err("upstream_error", "boom") if len(reads) >= 1 and kw.get("query", {}).get("limit") == 10 else None
            return None

        intercept_internal_call(monkeypatch, fail_after_the_first)
        done = env.call(edition, "restore_weight_snapshot", {"snapshot_id": sid, "dry_run": False, "confirm": dry["confirm"]})
        assert done["ok"] and stored_weights(cfg) == {"aesthetic_percent": 20, "composition_percent": 80}
        assert done["data"]["undo_snapshot_id"] is None and done["data"]["warnings"][0]["code"] == "no_undo_snapshot"

    def test_readonly_neither_lists_nor_restores(self, world, monkeypatch):
        env, _, readonly, cfg = world
        calls = []
        intercept_internal_call(monkeypatch, lambda tool, kw: calls.append(tool))
        for tool, args in (("list_weight_snapshots", {}), ("restore_weight_snapshot", {"snapshot_id": 1})):
            assert env.call(readonly, tool, args)["error"] == "forbidden_level"
        assert calls == []


class FakeProc:
    pid = 4242
    stdout = iter(())


@pytest.fixture()
def spawned(world, monkeypatch):
    """The scan router with its OS boundary replaced: the recorder is what proves a refused call spawned nothing."""
    started = []
    monkeypatch.setattr(scan, "subprocess", SimpleNamespace(
        Popen=lambda cmd, **kw: (started.append(cmd), FakeProc())[1],
        SubprocessError=subprocess.SubprocessError, PIPE=-1, STDOUT=-2))
    monkeypatch.setattr(scan, "_read_scan_output", lambda proc: None)
    monkeypatch.setattr(scan, "_recompute_conflict_detail", lambda: None)
    for key, value in (("running", False), ("kind", None), ("process", None), ("started_at", None),
                       ("directories", []), ("exit_code", None), ("progress", None), ("scope", None),
                       ("output_lines", deque(maxlen=500))):
        monkeypatch.setitem(scan._scan_state, key, value)
    return started


class TestRecompute:
    def test_a_category_starts_at_once_and_names_the_job(self, world, spawned):
        env, edition, _, _ = world
        out = env.call(edition, "recompute_scores", {"category": "base"})
        assert out["ok"], out
        data = out["data"]
        assert data["started"] is True and data["kind"] == "recompute" and data["scope"] == "category:base"
        assert isinstance(data["started_at"], float) and data["poll"] == "recompute_status"
        assert "burst" in data["note"] and "percentile" in data["note"]
        assert len(spawned) == 1 and spawned[0][spawned[0].index("--recompute-category") + 1] == "base"
        assert "--recompute-average" not in spawned[0]

    def test_all_runs_the_whole_library_job(self, world, spawned):
        env, edition, _, _ = world
        data = env.call(edition, "recompute_scores", {"all": True})["data"]
        assert data["scope"] == "all" and "--recompute-average" in spawned[0]

    def test_exactly_one_of_category_and_all(self, world, spawned):
        env, edition, _, _ = world
        for args in ({}, {"category": "base", "all": True}, {"all": False}):
            assert env.call(edition, "recompute_scores", args)["error"] == "invalid_input", args
        assert spawned == []

    def test_an_unknown_category_spawns_nothing(self, world, spawned):
        env, edition, _, _ = world
        assert env.call(edition, "recompute_scores", {"category": "zzz-nope"})["error"] == "invalid_input"
        assert spawned == []

    def test_a_second_call_while_one_runs_is_a_conflict(self, world, spawned):
        env, edition, _, _ = world
        assert env.call(edition, "recompute_scores", {"category": "base"})["ok"]
        assert env.call(edition, "recompute_scores", {"all": True})["error"] == "conflict"
        assert len(spawned) == 1

    def test_a_held_library_lock_is_a_conflict(self, world, spawned, monkeypatch):
        env, edition, _, _ = world
        monkeypatch.setattr(scan, "_recompute_conflict_detail", lambda: "A scan is already running from the command line.")
        refused = env.call(edition, "recompute_scores", {"category": "base"})
        assert refused["error"] == "conflict" and spawned == []

    def test_a_job_that_never_exits_does_not_make_the_tool_unknown(self, world, spawned):
        env, edition, _, _ = world
        started = env.call(edition, "recompute_scores", {"category": "base"})
        assert started["ok"] and scan._scan_state["running"] is True
        status = env.call(edition, "recompute_status", {"started_at": started["data"]["started_at"]})["data"]
        assert status["state"] == "running" and status["matches_started_job"] is True and status["reason"] is None

    @pytest.mark.parametrize("exit_code, state, reason", [(0, "succeeded", "ok"), (1, "failed", "failed"),
                                                          (75, "busy", "lock_held")])
    def test_the_status_maps_exit_codes(self, world, spawned, monkeypatch, exit_code, state, reason):
        env, edition, _, _ = world
        for key, value in (("running", False), ("kind", "recompute"), ("exit_code", exit_code),
                           ("started_at", 111.0), ("scope", "all")):
            monkeypatch.setitem(scan._scan_state, key, value)
        out = env.call(edition, "recompute_status", {"started_at": 111.0})["data"]
        assert (out["state"], out["reason"], out["matches_started_job"]) == (state, reason, True)
        other = env.call(edition, "recompute_status", {"started_at": 5.0})["data"]
        assert other["reason"] == "not_this_job" and other["matches_started_job"] is False

    def test_no_job_is_idle(self, world, spawned):
        env, edition, _, _ = world
        out = env.call(edition, "recompute_status", {})["data"]
        assert out["state"] == "idle" and out["reason"] == "no_job"

    def test_readonly_neither_starts_nor_polls(self, world, spawned, monkeypatch):
        env, _, readonly, _ = world
        calls = []
        intercept_internal_call(monkeypatch, lambda tool, kw: calls.append(tool))
        for tool, args in (("recompute_scores", {"all": True}), ("recompute_status", {})):
            assert env.call(readonly, tool, args)["error"] == "forbidden_level"
        assert spawned == [] and calls == []


class FakeOptimizer:
    result: dict = {}
    confidence: dict = {}

    def __init__(self, *args, **kwargs):
        pass

    def optimize_weights_direct(self, **kwargs):
        return type(self).result

    def compute_weight_confidence(self, **kwargs):
        return type(self).confidence


AVAILABLE = {"old_weights": {"aesthetic": 0.6, "composition": 0.4, "contrast": 0.1},
             "new_weights": {"aesthetic": 0.5, "composition": 0.3, "color": 0.2, "contrast": 0.1},
             "accuracy_before": 0.6, "accuracy_after": 0.7, "improvement": 0.1, "suggest_changes": True,
             "comparisons_used": 60, "ties_included": 3,
             "per_comparison": [{"predicted_correct": False}, {"predicted_correct": True}]}


@pytest.fixture()
def optimizer(world, monkeypatch):
    import optimization
    from api.routers import comparison
    monkeypatch.setattr(optimization, "WeightOptimizer", FakeOptimizer)
    monkeypatch.setattr(comparison, "get_comparison_mode_settings", lambda: {"min_comparisons_for_optimization": 0})
    FakeOptimizer.result = dict(AVAILABLE)
    FakeOptimizer.confidence = {"weights": {"aesthetic": 0.5}, "lower_bounds": {"aesthetic": 0.4},
                                "upper_bounds": {"aesthetic": 0.6}, "confidence_intervals": {"aesthetic": 0.2},
                                "stable_components": ["aesthetic"], "n_bootstrap": 50, "comparisons_used": 60}
    return world


class TestLearnedWeights:
    def test_an_available_suggestion_lists_non_zero_changes_and_a_proposal_preview_accepts(self, optimizer):
        env, edition, _, cfg = optimizer
        before = db("SELECT COUNT(*) FROM comparisons"), cfg.read_bytes(), snapshots()
        out = env.call(edition, "learned_weights", {"category": "base"})
        assert out["ok"], out
        data = out["data"]
        assert data["available"] is True and data["suggest_changes"] is True and data["comparisons_used"] == 60
        assert data["changes"] == [
            {"key": "aesthetic_percent", "current": 60, "suggested": 50, "delta": -10},
            {"key": "color_percent", "current": 0, "suggested": 20, "delta": 20},
            {"key": "composition_percent", "current": 40, "suggested": 30, "delta": -10}]
        assert data["proposal"] == {"aesthetic_percent": 50, "color_percent": 20, "composition_percent": 30}
        assert data["mispredicted_count"] == 1 and "preview_weights" in data["next"]
        accepted = env.call(edition, "preview_weights", {"category": "base", "weights": data["proposal"], "sample": 5})
        assert accepted["ok"] and accepted["data"]["preview_digest"]
        assert (db("SELECT COUNT(*) FROM comparisons"), cfg.read_bytes(), snapshots()) == before

    def test_no_improvement_drops_the_changes_and_says_not_to_propose(self, optimizer):
        env, edition, _, _ = optimizer
        FakeOptimizer.result = {**AVAILABLE, "suggest_changes": False}
        data = env.call(edition, "learned_weights", {"category": "base"})["data"]
        assert data["suggest_changes"] is False and "do not propose" in data["note"]
        assert "changes" not in data and "proposal" not in data

    def test_too_few_comparisons_is_passed_through_not_invented(self, world, monkeypatch):
        import optimization
        env, edition, _, _ = world
        monkeypatch.setattr(optimization, "WeightOptimizer", FakeOptimizer)
        data = env.call(edition, "learned_weights", {"category": "base"})["data"]
        assert data["available"] is False and data["reason"] == "not_enough_comparisons"
        assert data["min_required"] > 0 and data["comparisons"] == 0 and "proposal" not in data

    def test_an_external_backend_is_unavailable(self, world, monkeypatch):
        import optimization
        env, edition, _, cfg = world
        monkeypatch.setattr(optimization, "WeightOptimizer", FakeOptimizer)
        write_config(cfg, auto_retrain={"backend": "external"})
        data = env.call(edition, "learned_weights", {"category": "base"})["data"]
        assert data["available"] is False and data["reason"] == "unavailable_if_external"
        assert "proposal" not in data

    def test_an_optimizer_error_is_unavailable(self, optimizer):
        env, edition, _, _ = optimizer
        FakeOptimizer.result = {"error": "not enough pairs"}
        data = env.call(edition, "learned_weights", {"category": "base"})["data"]
        assert data["available"] is False and data["reason"] == "optimizer_unavailable"

    def test_ties_are_included_unless_the_caller_leaves_them_out(self, optimizer, monkeypatch):
        env, edition, _, _ = optimizer
        seen = []
        original = FakeOptimizer.optimize_weights_direct
        monkeypatch.setattr(FakeOptimizer, "optimize_weights_direct",
                            lambda self, **kw: (seen.append(kw["include_ties"]), original(self, **kw))[1])
        env.call(edition, "learned_weights", {"category": "base"})
        env.call(edition, "learned_weights", {"category": "base", "include_ties": False})
        assert seen == [True, False]

    def test_confidence_is_opt_in(self, optimizer):
        env, edition, _, _ = optimizer
        assert "confidence" not in env.call(edition, "learned_weights", {"category": "base"})["data"]
        data = env.call(edition, "learned_weights", {"category": "base", "with_confidence": True})["data"]
        assert data["confidence"]["stable_components"] == ["aesthetic"] and data["confidence"]["n_bootstrap"] == 50

    def test_an_unavailable_confidence_carries_the_reason(self, optimizer):
        env, edition, _, _ = optimizer
        FakeOptimizer.confidence = {"error": "too few comparisons for a bootstrap"}
        data = env.call(edition, "learned_weights", {"category": "base", "with_confidence": True})["data"]
        assert data["confidence"] == {"available": False, "message": "too few comparisons for a bootstrap"}

    def test_a_failed_confidence_call_is_unavailable_with_the_error_message(self, optimizer, monkeypatch):
        from api.agent.internal_client import err
        env, edition, _, _ = optimizer
        intercept_internal_call(monkeypatch, lambda tool, kw: err("upstream_error", "bootstrap blew up")
                                if tool == "weight_confidence" else None)
        data = env.call(edition, "learned_weights", {"category": "base", "with_confidence": True})["data"]
        assert data["confidence"] == {"available": False, "message": "bootstrap blew up"}
        assert data["available"] is True

    def test_the_category_is_required_and_readonly_is_refused(self, optimizer, monkeypatch):
        env, edition, readonly, _ = optimizer
        assert env.call(edition, "learned_weights", {})["error"] == "invalid_input"
        calls = []
        intercept_internal_call(monkeypatch, lambda tool, kw: calls.append(tool))
        assert env.call(readonly, "learned_weights", {"category": "base"})["error"] == "forbidden_level"
        assert calls == []


CRITIQUE_ROWS = [
    row("stale.jpg", face_ratio=0.2, face_count=1, aggregate=9.0),
    row("near.jpg", face_ratio=0.095, face_count=1, aggregate=8.0),
    row("far.jpg", face_ratio=0.02, face_count=1, aggregate=7.0),
    row("pinned.jpg", face_ratio=0.2, face_count=1, aggregate=6.0),
]


@pytest.fixture()
def fixing(agent_app, seed_photos_prefix, sandbox):
    seed_photos_prefix(PREFIX, CRITIQUE_ROWS)
    env = agent_app("legacy")
    edition = env.token(env.login(edition=True), "edition")
    return env, edition, env.token(env.login(), "readonly"), sandbox


class TestMisassigned:
    def test_stale_and_near_miss_are_listed_with_their_signal_and_the_pinned_one_is_skipped(self, fixing):
        env, edition, _, _ = fixing
        assert env.call(edition, "override_category", {"path": PREFIX + "pinned.jpg", "category": "base"})["ok"]
        out = env.call(edition, "misassigned_categories", {"category": "base"})
        assert out["ok"], out
        data = out["data"]
        assert [(c["path"].rsplit("/", 1)[1], c["signal"], c["stored"], c["suggested"]) for c in data["candidates"]] == [
            ("stale.jpg", "stale", "base", "wide"), ("near.jpg", "near_miss", "base", "wide")]
        assert data["candidates"][1]["mismatch"]["key"] == "face_ratio_min"
        assert data["scanned"] == 4 and data["of_total"] == 4 and data["partial"] is False
        assert data["skipped_overridden"] == 1 and data["confidence_basis"] == "heuristic"
        assert "worth a look" in data["note"]

    def test_scanned_is_honest_when_the_scan_is_capped(self, fixing):
        env, edition, _, _ = fixing
        data = env.call(edition, "misassigned_categories", {"category": "base", "scan": 1})["data"]
        assert data["scanned"] == 1 and data["of_total"] == 4 and data["partial"] is True
        assert "partial" in data["note"]

    def test_failed_critiques_are_counted_apart_and_make_the_scan_partial(self, fixing, monkeypatch):
        from api.agent.internal_client import err
        env, edition, _, _ = fixing
        intercept_internal_call(monkeypatch, lambda tool, kw: err("upstream_error", "boom")
                                if tool == "critique" and kw["query"]["path"].endswith("far.jpg") else None)
        data = env.call(edition, "misassigned_categories", {"category": "base"})["data"]
        assert data["failed"] == 1 and data["scanned"] == 3 and data["of_total"] == 4
        assert data["partial"] is True and "could not be examined" in data["note"]

    def test_when_every_critique_fails_the_upstream_error_is_returned_not_an_empty_scan(self, fixing, monkeypatch):
        from api.agent.internal_client import err
        env, edition, _, _ = fixing
        intercept_internal_call(monkeypatch, lambda tool, kw: err("upstream_error", "boom") if tool == "critique" else None)
        out = env.call(edition, "misassigned_categories", {"category": "base"})
        assert out["ok"] is False and out["error"] == "upstream_error", out

    def test_the_limit_caps_the_list_and_reports_the_total(self, fixing):
        env, edition, _, _ = fixing
        data = env.call(edition, "misassigned_categories", {"category": "base", "limit": 1})["data"]
        assert len(data["candidates"]) == 1 and data["candidates_total"] >= 2

    def test_nothing_is_written(self, fixing):
        env, edition, _, cfg = fixing
        before = cfg.read_bytes(), db("SELECT COUNT(*) FROM photo_scoring_overrides"), \
            db("SELECT path, category, aggregate FROM photos WHERE path LIKE ? ORDER BY path", PREFIX + "%")
        env.call(edition, "misassigned_categories", {"category": "base"})
        assert (cfg.read_bytes(), db("SELECT COUNT(*) FROM photo_scoring_overrides"),
                db("SELECT path, category, aggregate FROM photos WHERE path LIKE ? ORDER BY path", PREFIX + "%")) == before

    def test_the_critique_switch_hides_it_and_refuses_a_call(self, fixing):
        from api import config as api_config
        env, edition, _, _ = fixing
        features = api_config.VIEWER_CONFIG.setdefault("features", {})
        was = features.get("show_critique", "unset")
        features["show_critique"] = False
        try:
            assert "misassigned_categories" not in env.tool_names(edition)
            assert env.call(edition, "misassigned_categories", {"category": "base"})["error"] == "feature_disabled"
        finally:
            if was == "unset":
                features.pop("show_critique")
            else:
                features["show_critique"] = was

    def test_readonly_is_refused(self, fixing, monkeypatch):
        env, _, readonly, _ = fixing
        calls = []
        intercept_internal_call(monkeypatch, lambda tool, kw: calls.append(tool))
        assert env.call(readonly, "misassigned_categories", {"category": "base"})["error"] == "forbidden_level"
        assert calls == []


def overrides():
    return db("SELECT COUNT(*) FROM photo_scoring_overrides WHERE photo_path LIKE ?", PREFIX + "%")[0][0]


def category_of(name):
    return db("SELECT category, aggregate FROM photos WHERE path = ?", PREFIX + name)[0]


class TestOverrideCategories:
    PATHS = [PREFIX + "stale.jpg", PREFIX + "near.jpg"]

    def run(self, env, token, **extra):
        return env.call(token, "override_categories", {"category": "wide", "paths": self.PATHS, **extra})

    def test_a_dry_run_writes_nothing_and_binds_a_confirm_to_what_it_saw(self, fixing):
        env, edition, _, _ = fixing
        dry = self.run(env, edition)
        assert dry["ok"], dry
        data = dry["data"]
        assert data["would_change"] == 2 and data["already"] == [] and data["missing"] == []
        assert {p["path"] for p in data["photos"]} == set(self.PATHS) and data["confirm"]
        assert overrides() == 0 and category_of("stale.jpg")[0] == "base"

    def test_already_and_missing_are_reported_apart(self, fixing):
        env, edition, _, _ = fixing
        db("UPDATE photos SET category = 'wide' WHERE path = ?", self.PATHS[0])
        data = env.call(edition, "override_categories",
                        {"category": "wide", "paths": [*self.PATHS, PREFIX + "ghost.jpg"]})["data"]
        assert data["would_change"] == 1 and data["already"] == [self.PATHS[0]] and data["missing"] == [PREFIX + "ghost.jpg"]

    def test_a_photo_already_in_the_category_is_pinned_too(self, fixing):
        env, edition, _, _ = fixing
        db("UPDATE photos SET category = 'wide' WHERE path = ?", self.PATHS[0])
        dry = self.run(env, edition)["data"]
        assert dry["would_change"] == 1 and dry["would_pin"] == 2 and dry["already"] == [self.PATHS[0]]
        done = self.run(env, edition, dry_run=False, confirm=dry["confirm"], expected_count=2)
        assert done["ok"], done
        assert done["data"]["affected"] == 2 and done["data"]["recategorised"] == 1
        assert overrides() == 2

    def test_a_real_run_needs_the_confirm_and_the_matching_expected_count(self, fixing):
        env, edition, _, _ = fixing
        confirm = self.run(env, edition)["data"]["confirm"]
        assert self.run(env, edition, dry_run=False, expected_count=2)["error"] == "confirmation_required"
        wrong = self.run(env, edition, dry_run=False, confirm=confirm, expected_count=3)
        assert wrong["error"] == "invalid_input" and "expected_count" in wrong["message"]
        assert self.run(env, edition, dry_run=False, confirm=confirm)["error"] == "invalid_input"
        assert overrides() == 0

    def test_a_category_that_moved_since_the_dry_run_is_refused(self, fixing):
        env, edition, _, _ = fixing
        confirm = self.run(env, edition)["data"]["confirm"]
        db("UPDATE photos SET category = 'wide' WHERE path = ?", self.PATHS[0])
        refused = self.run(env, edition, dry_run=False, confirm=confirm, expected_count=2)
        assert refused["error"] == "confirmation_required" and overrides() == 0

    def test_success_pins_the_category_and_recomputes_the_aggregate(self, fixing):
        env, edition, _, _ = fixing
        before = category_of("near.jpg")
        confirm = self.run(env, edition)["data"]["confirm"]
        done = self.run(env, edition, dry_run=False, confirm=confirm, expected_count=2)
        assert done["ok"], done
        assert done["data"]["affected"] == 2 and done["data"]["remaining"] == 0
        assert done["data"]["category"] == "wide" and "clear_category_override" in done["data"]["note"]
        assert overrides() == 2
        assert category_of("near.jpg")[0] == "wide" and category_of("near.jpg")[1] != before[1]
        assert db("SELECT category_override FROM photo_scoring_overrides WHERE photo_path = ?", self.PATHS[0]) == [("wide",)]

    def test_the_first_failure_stops_the_batch_and_reports_what_remains(self, fixing, monkeypatch):
        from api.agent.internal_client import err
        env, edition, _, _ = fixing
        confirm = self.run(env, edition)["data"]["confirm"]
        calls = []

        def fail_second(tool, kw):
            if tool != "override_category":
                return None
            calls.append(kw["json"]["path"])
            return err("upstream_error", "boom") if len(calls) == 2 else None

        intercept_internal_call(monkeypatch, fail_second)
        stopped = self.run(env, edition, dry_run=False, confirm=confirm, expected_count=2)
        assert stopped["error"] == "upstream_error"
        assert stopped["affected"] == 1 and stopped["remaining"] == 0 and stopped["failed_path"] == self.PATHS[1]
        assert overrides() == 1

    def test_an_unknown_category_the_cap_and_readonly_are_refused(self, fixing, monkeypatch):
        env, edition, readonly, _ = fixing
        assert env.call(edition, "override_categories", {"category": "zzz-nope", "paths": self.PATHS}
                        )["error"] == "invalid_input"
        too_many = env.call(edition, "override_categories",
                            {"category": "wide", "paths": [PREFIX + f"{i}.jpg" for i in range(51)]})
        assert too_many["error"] == "too_large"
        calls = []
        intercept_internal_call(monkeypatch, lambda tool, kw: calls.append(tool))
        assert self.run(env, readonly)["error"] == "forbidden_level" and calls == []


class TestDocsPhaseTwo:
    LANGS = ["", "fr", "de", "it", "es", "pt", "zh"]
    DOCS = pathlib.Path(__file__).resolve().parent.parent / "docs"

    @pytest.mark.parametrize("lang", LANGS)
    def test_every_language_names_every_phase_two_tool(self, lang):
        text = (self.DOCS / lang / "AGENTS.md").read_text(encoding="utf-8")
        for name in ("apply_weights", "list_weight_snapshots", "restore_weight_snapshot", "recompute_scores",
                     "recompute_status", "learned_weights", "misassigned_categories", "override_categories",
                     "auto:pre_restore", "unsupported_snapshot"):
            assert name in text, (lang, name)
