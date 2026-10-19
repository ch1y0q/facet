"""Agent write tools over /mcp: grants, SET semantics, scope checks, the confirmation nonce.

Real auth chain (``agent_app``), real routes, seeded rows in the shared session DB.
Moves happen in ``tmp_path``; ``send2trash`` is replaced by a delete so nothing
reaches the developer's trash.
"""

import os
import sqlite3
import time

import httpx
import pytest

from api import config as api_config
from api.agent import internal_client, limits, nonce
from api.agent.internal_client import ROUTE_ALLOWLIST
from api.agent.tools_write import WRITE_TOOL_LEVELS
from tests.conftest import _TEST_DB_FILE, AGENT_DIR

ROWS = [
    {"path": AGENT_DIR + f"w{i}.jpg", "filename": f"w{i}.jpg", "aggregate": 5.0 + i,
     "star_rating": 1, "is_favorite": 0, "is_rejected": 0} for i in range(4)
] + [{"path": AGENT_DIR + "junk1.jpg", "filename": "junk1.jpg", "aggregate": 1.0, "junk_kind": "blurry"}]
P = [row["path"] for row in ROWS]


@pytest.fixture()
def photos(seed_photos_prefix):
    wipe_prefs()
    yield seed_photos_prefix(AGENT_DIR, ROWS)
    wipe_prefs()


@pytest.fixture(autouse=True)
def fresh_clock():
    yield
    limits.set_clock(None)


def db_row(sql, *args):
    conn = sqlite3.connect(_TEST_DB_FILE.name)
    try:
        return conn.execute(sql, args).fetchone()
    finally:
        conn.close()


def wipe_prefs():
    conn = sqlite3.connect(_TEST_DB_FILE.name)
    conn.execute("DELETE FROM user_preferences WHERE photo_path LIKE ?", (AGENT_DIR + "%",))
    conn.commit()
    conn.close()


def photo_col(path, col):
    return db_row(f"SELECT {col} FROM photos WHERE path = ?", path)[0]


def pref(user, path):
    return db_row("SELECT star_rating, is_favorite, is_rejected FROM user_preferences "
                  "WHERE user_id = ? AND photo_path = ?", user, path)


@pytest.fixture()
def edition(agent_app):
    env = agent_app("legacy")
    return env, env.token(env.login(edition=True), "edition")


@pytest.fixture()
def counting(monkeypatch):
    """Record every upstream tool name the internal client is asked to call."""
    calls = []
    real = internal_client.InternalClient.call

    async def call(self, grant, tool, **kw):
        calls.append(tool)
        return await real(self, grant, tool, **kw)
    monkeypatch.setattr(internal_client.InternalClient, "call", call)
    return calls


class TestGrantMatrix:
    ARGS = {
        "set_rating": {"paths": [P[0]], "rating": 2}, "set_favorite": {"paths": [P[0]], "value": True},
        "set_rejected": {"paths": [P[0]], "value": True},
        "batch_set_rating": {"paths": [P[0]], "rating": 2}, "batch_set_favorite": {"paths": [P[0]]},
        "batch_set_rejected": {"paths": [P[0]]}, "create_album": {"name": "x"},
        "album_add_photos": {"album_id": 999999, "paths": [P[0]]},
        "album_remove_photos": {"album_id": 999999, "paths": [P[0]]},
        "add_tags": {"tags": ["t"], "paths": [P[0]]}, "remove_tags": {"tags": ["t"], "paths": [P[0]]},
        "junk_list": {}, "junk_reject": {"paths": [P[0]]}, "junk_clear": {"paths": [P[0]]},
        "cull_apply": {"action": "copy_keeps", "paths": [P[0]]}, "delete_photos": {"paths": [P[0]]},
    }

    def test_every_write_tool_has_args_and_a_level(self):
        assert set(self.ARGS) == set(WRITE_TOOL_LEVELS)

    def test_write_routes_never_default_to_readonly(self):
        for name, spec in ROUTE_ALLOWLIST.items():
            if spec.write:
                assert spec.min_level != "readonly", name

    def test_matrix_multi_user(self, agent_app, photos, counting):
        env = agent_app("multi")
        tokens = {
            "readonly": env.token(env.login("root"), "readonly"),
            "user": env.token(env.login("alice"), "user"),
            "edition": env.token(env.login("root"), "edition"),
        }
        for level, token in tokens.items():
            for tool, floor in WRITE_TOOL_LEVELS.items():
                counting.clear()
                result = env.call(token, tool, self.ARGS[tool])
                refused = result.get("error") == "forbidden_level" and "token's level" in result["message"]
                allowed = ("readonly", "user", "edition").index(level) >= \
                    ("readonly", "user", "edition").index(floor)
                assert refused is (not allowed), (level, tool, result)
                if refused:
                    assert counting == [], (level, tool, counting)

    def test_legacy_user_token_is_capped_to_readonly(self, agent_app, photos, counting):
        env = agent_app("legacy")
        resp = env.mint(env.login(), "user")
        token = resp.json()["token"] if resp.status_code == 200 else env.token(env.login(), "readonly")
        result = env.call(token, "set_rating", {"paths": [P[0]], "rating": 4})
        assert result["error"] == "forbidden_level" and counting == []
        assert photo_col(P[0], "star_rating") == 1

    def test_admin_readonly_token_cannot_rate(self, agent_app, photos):
        env = agent_app("multi")
        token = env.token(env.login("root"), "readonly")
        assert env.call(token, "set_rating", {"paths": [P[0]], "rating": 5})["error"] == "forbidden_level"
        assert pref("root", P[0]) is None

    def test_write_tools_are_not_read_only_and_destructive_hint_only_on_two(self, edition):
        env, token = edition
        tools = {t["name"]: t for t in env.rpc(token, "tools/list").json()["result"]["tools"]}
        for name in WRITE_TOOL_LEVELS:
            hints = tools[name]["annotations"]
            assert hints["readOnlyHint"] is (name == "junk_list"), name
            assert hints["destructiveHint"] is (name in ("cull_apply", "delete_photos")), name


class TestPerPhotoTools:
    def alice(self, agent_app):
        env = agent_app("multi")
        return env, env.token(env.login("alice"), "user")

    def test_rating_lands_in_user_preferences_not_photos(self, agent_app, photos):
        env, token = self.alice(agent_app)
        result = env.call(token, "set_rating", {"paths": [P[0]], "rating": 5})
        assert result["ok"] and result["data"]["affected"] == 1
        assert pref("alice", P[0])[0] == 5
        assert photo_col(P[0], "star_rating") == 1

    def test_set_is_idempotent(self, agent_app, photos):
        env, token = self.alice(agent_app)
        env.call(token, "set_rating", {"paths": [P[0]], "rating": 5})
        again = env.call(token, "set_rating", {"paths": [P[0]], "rating": 5})
        assert again["data"]["affected"] == 0 and again["data"]["already"] == 1
        assert again["data"]["results"] == [{"path": P[0], "outcome": "already"}]

    def test_unfavourite_of_a_non_favourite_does_not_toggle(self, agent_app, photos, counting):
        env, token = self.alice(agent_app)
        result = env.call(token, "set_favorite", {"paths": [P[0]], "value": False})
        assert result["data"]["already"] == 1 and "toggle_favorite" not in counting
        result = env.call(token, "set_favorite", {"paths": [P[0]], "value": True})
        assert result["data"]["affected"] == 1 and counting.count("toggle_favorite") == 1
        assert env.call(token, "set_favorite", {"paths": [P[0]], "value": True})["data"]["already"] == 1
        assert counting.count("toggle_favorite") == 1

    def test_reject_then_unreject(self, agent_app, photos):
        env, token = self.alice(agent_app)
        assert env.call(token, "set_rejected", {"paths": [P[1]], "value": True})["data"]["affected"] == 1
        assert pref("alice", P[1])[2] == 1
        assert env.call(token, "set_rejected", {"paths": [P[1]], "value": False})["data"]["affected"] == 1
        assert pref("alice", P[1])[2] == 0

    def test_cap_of_50(self, agent_app, photos):
        env, token = self.alice(agent_app)
        result = env.call(token, "set_rating", {"paths": [f"{AGENT_DIR}n{i}.jpg" for i in range(51)], "rating": 1})
        assert result["error"] == "too_large"
        assert env.call(token, "set_rating", {"paths": [], "rating": 1})["error"] == "invalid_input"

    def test_unknown_path_is_skipped_not_fatal(self, agent_app, photos):
        env, token = self.alice(agent_app)
        result = env.call(token, "set_rating", {"paths": [AGENT_DIR + "nope.jpg", P[0]], "rating": 4})
        assert result["ok"] and result["data"]["affected"] == 1
        assert result["data"]["skipped"] == [{"path": AGENT_DIR + "nope.jpg", "reason": "not_found"}]

    def test_one_users_agent_cannot_touch_anothers_ratings(self, agent_app, photos):
        env, token = self.alice(agent_app)
        env.call(token, "set_rating", {"paths": [P[0]], "rating": 5})
        assert pref("root", P[0]) is None
        root = env.token(env.login("root"), "user")
        assert env.call(root, "set_rating", {"paths": [P[0]], "rating": 2})["ok"]
        assert pref("alice", P[0])[0] == 5 and pref("root", P[0])[0] == 2

    def test_a_user_without_the_directory_cannot_rate_it(self, agent_app, photos):
        env = agent_app("multi")
        bob = env.token(env.login("bob"), "user")
        result = env.call(bob, "set_rating", {"paths": [P[0]], "rating": 5})
        assert result["data"]["skipped"][0]["reason"] == "not_found"
        assert pref("bob", P[0]) is None

    def test_write_timeout_is_outcome_unknown_and_stops(self, agent_app, photos, monkeypatch):
        env, token = self.alice(agent_app)
        real = httpx.AsyncClient.request

        async def request(self, method, url, **kw):
            if str(url).endswith("/api/photo/set_rating"):
                raise httpx.ReadTimeout("slow")
            return await real(self, method, url, **kw)
        monkeypatch.setattr(httpx.AsyncClient, "request", request)
        result = env.call(token, "set_rating", {"paths": [P[0], P[1]], "rating": 4})
        assert result["error"] == "outcome_unknown" and "do not blindly retry" in result["message"]
        assert result["in_doubt"] == P[0] and result["not_attempted"] == 1

    def test_busy_library_is_library_busy(self, agent_app, photos, monkeypatch):
        env, token = self.alice(agent_app)
        real = httpx.AsyncClient.request

        async def request(self, method, url, **kw):
            if str(url).endswith("/api/photo/set_rating"):
                return httpx.Response(503, json={"detail": "database is locked"})
            return await real(self, method, url, **kw)
        monkeypatch.setattr(httpx.AsyncClient, "request", request)
        assert env.call(token, "set_rating", {"paths": [P[0]], "rating": 4})["error"] == "library_busy"

    def test_write_rate_limit_is_separate_from_reads(self, agent_app, photos):
        env = agent_app("multi", write_rate_per_min=2)
        token = env.token(env.login("alice"), "user")
        for _ in range(2):
            assert env.call(token, "set_rating", {"paths": [P[0]], "rating": 3})["ok"]
        assert env.call(token, "set_rating", {"paths": [P[0]], "rating": 3})["error"] == "rate_limited"
        assert env.call(token, "status")["ok"]


class TestBatchTools:
    def test_paths_scope_sets_photos_in_single_password_mode(self, edition, photos):
        env, token = edition
        result = env.call(token, "batch_set_rating", {"paths": P[:2], "rating": 4})
        assert result["data"]["affected"] == 2
        assert [photo_col(p, "star_rating") for p in P[:3]] == [4, 4, 1]
        assert env.call(token, "batch_set_favorite", {"paths": [P[0]]})["data"]["affected"] == 1
        assert photo_col(P[0], "is_favorite") == 1
        assert env.call(token, "batch_set_rejected", {"paths": P[:2], "exclude": [P[1]]})["data"]["affected"] == 1
        assert photo_col(P[1], "is_rejected") == 0

    def view(self, env):
        return {"path_prefix": AGENT_DIR}

    def test_filter_scope_needs_a_matching_expected_count(self, edition, photos):
        env, token = edition
        headers = env.login(edition=True)
        total = env.client.get("/api/photos/count", params=self.view(env), headers=headers).json()["total"]
        assert total == 5
        args = {"filters": self.view(env), "rating": 5}
        assert env.call(token, "batch_set_rating", args)["error"] == "invalid_input"
        wrong = env.call(token, "batch_set_rating", {**args, "expected_count": total + 1})
        assert wrong["error"] == "invalid_input" and wrong["actual_count"] == total
        assert [photo_col(p, "star_rating") for p in P[:4]] == [1, 1, 1, 1]  # nothing written
        right = env.call(token, "batch_set_rating", {**args, "expected_count": total})
        assert right["ok"] and right["data"]["affected"] == total
        assert photo_col(P[0], "star_rating") == 5

    def test_both_or_neither_target_and_misspelled_filter(self, edition, photos):
        env, token = edition
        both = env.call(token, "batch_set_favorite", {"paths": [P[0]], "filters": {}, "expected_count": 1})
        assert both["error"] == "invalid_input"
        assert env.call(token, "batch_set_favorite", {})["error"] == "invalid_input"
        typo = env.call(token, "batch_set_favorite", {"filters": {"path_prefx": AGENT_DIR}, "expected_count": 1})
        assert typo["error"] == "invalid_input"
        assert env.call(token, "batch_set_favorite", {"paths": [f"/x/{i}" for i in range(1001)]})["error"] == "too_large"

    def test_albums(self, edition, photos):
        env, token = edition
        album = env.call(token, "create_album", {"name": "agent album"})["data"]
        added = env.call(token, "album_add_photos", {"album_id": album["id"], "paths": P[:2]})
        assert added["ok"] and added["data"]["added"] == 2
        removed = env.call(token, "album_remove_photos", {"album_id": album["id"], "paths": [P[0]]})
        assert removed["data"]["photo_count"] == 1
        assert env.call(token, "album_add_photos", {"album_id": 987654, "paths": [P[0]]})["error"] == "not_found"
        env.client.delete(f"/api/albums/{album['id']}", headers=env.login(edition=True))

    def test_manual_tags(self, edition, photos):
        env, token = edition
        assert env.call(token, "add_tags", {"tags": ["alpha", "beta"], "paths": P[:2]})["data"]["affected"] == 4
        assert db_row("SELECT COUNT(*) FROM photo_manual_tags WHERE photo_path = ?", P[0])[0] == 2
        assert env.call(token, "remove_tags", {"tags": ["alpha"], "paths": P[:2]})["data"]["affected"] == 2
        assert db_row("SELECT COUNT(*) FROM photo_manual_tags WHERE photo_path = ? AND tag = 'alpha'", P[0])[0] == 0
        env.call(token, "remove_tags", {"tags": ["beta"], "paths": P[:2]})

    def test_junk_sweep(self, edition, photos):
        env, token = edition
        listed = env.call(token, "junk_list", {"kind": "blurry"})
        assert [r["path"] for r in listed["data"]["rows"]] == [P[4]]
        assert env.call(token, "junk_reject", {"paths": [P[4]]})["data"]["affected"] == 1
        assert photo_col(P[4], "is_rejected") == 1
        assert env.call(token, "junk_clear", {"paths": [P[4]]})["data"]["affected"] == 1
        assert photo_col(P[4], "junk_kind") == "not_junk"
        assert env.call(token, "junk_clear", {"paths": [P[0]] * 51})["error"] == "too_large"


def test_user_floor_message_names_edition_on_a_single_password_install(agent_app, photos):
    env = agent_app("legacy")
    token = env.token(env.login(), "readonly")
    refused = env.call(token, "set_rejected", {"paths": [P[0]], "value": True})
    assert refused["error"] == "forbidden_level" and "needs edition" in refused["message"]
    multi = agent_app("multi")
    viewer = multi.token(multi.login("alice"), "readonly")
    assert "needs user" in multi.call(viewer, "set_rejected", {"paths": [P[0]], "value": True})["message"]


def test_filter_scope_resolves_the_same_set_as_search_photos(edition, photos, monkeypatch):
    env, token = edition
    monkeypatch.setitem(api_config.VIEWER_CONFIG["defaults"], "hide_blinks", True)
    conn = sqlite3.connect(_TEST_DB_FILE.name)
    conn.execute("UPDATE photos SET is_blink = 1 WHERE path = ?", (P[3],))
    conn.commit()
    conn.close()
    filters = {"path_prefix": AGENT_DIR}
    seen = env.call(token, "search_photos", {"filters": filters})["data"]["total"]
    assert seen == 4
    result = env.call(token, "batch_set_rating", {"filters": filters, "rating": 5, "expected_count": seen})
    assert result["ok"], result
    assert result["data"]["affected"] == 4 and photo_col(P[3], "star_rating") == 1


@pytest.fixture()
def panorama(edition, seed_photos_prefix, tmp_path, monkeypatch):
    """Three rejected frames of one panorama set on disk."""
    env, token = edition
    root = os.path.realpath(tmp_path)
    src = os.path.join(root, "pano")
    os.makedirs(src)
    rows = []
    for index in range(3):
        path = os.path.join(src, f"p{index}.jpg")
        with open(path, "wb") as handle:
            handle.write(b"JPG")
        rows.append({"path": path, "filename": f"p{index}.jpg", "is_rejected": 1,
                     "sequence_kind": "panorama", "sequence_group_id": 9,
                     "is_sequence_lead": 1 if index == 1 else 0})
    seed_photos_prefix(src + "/", rows)
    monkeypatch.setattr("api.routers.export._allowed_export_roots", lambda: [root])
    monkeypatch.setitem(api_config.VIEWER_CONFIG, "cull", {"allow_trash": True})
    monkeypatch.setattr("send2trash.send2trash", os.remove)
    return type("Pano", (), {"env": env, "token": token, "src": src, "target": os.path.join(root, "out"),
                             "lead": rows[1]["path"], "paths": [r["path"] for r in rows]})


class TestSequenceSiblingsAreBoundToTheNonce:
    def test_delete_lists_the_siblings_and_binds_the_flag(self, panorama):
        def call(**kw):
            return panorama.env.call(panorama.token, "delete_photos", {"paths": [panorama.lead], **kw})
        plain = call()["data"]
        assert plain["would_trash_count"] == 1
        wide = call(include_sequence_siblings=True)["data"]
        assert wide["would_trash_count"] == 3 and wide["sequence_siblings_count"] == 2
        flipped = call(dry_run=False, confirm=wide["confirm"])
        assert flipped["error"] == "confirmation_required"
        assert all(os.path.exists(p) for p in panorama.paths)
        fresh = call(include_sequence_siblings=True)["data"]
        done = call(include_sequence_siblings=True, dry_run=False, confirm=fresh["confirm"])
        assert done["ok"] and len(done["data"]["deleted"]) == 3
        assert not any(os.path.exists(p) for p in panorama.paths)

    def test_cull_apply_binds_the_flag(self, panorama):
        def call(**kw):
            return panorama.env.call(panorama.token, "cull_apply", {
                "action": "move_rejects", "target_dir": panorama.target, "paths": [panorama.lead], **kw})
        plain = call()["data"]
        assert plain["would_move_count"] == 1
        wide = call(include_sequence_siblings=True)["data"]
        assert wide["would_move_count"] == 3 and wide["sequence_siblings"] == 2
        assert call(dry_run=False, confirm=wide["confirm"])["error"] == "confirmation_required"
        assert all(os.path.exists(p) for p in panorama.paths)
        fresh = call(include_sequence_siblings=True)["data"]
        done = call(include_sequence_siblings=True, dry_run=False, confirm=fresh["confirm"])
        assert done["ok"] and done["data"]["moved"] == 3


@pytest.fixture()
def library(edition, seed_photos_prefix, tmp_path, monkeypatch):
    """Four photos on disk: r1, r2 rejected, k1 kept (r1 has a RAW companion)."""
    env, token = edition
    root = os.path.realpath(tmp_path)
    src = os.path.join(root, "src")
    os.makedirs(src)
    names = {"r1": 1, "r2": 1, "k1": 0}
    rows = []
    for name, rejected in names.items():
        with open(os.path.join(src, name + ".jpg"), "wb") as handle:
            handle.write(b"JPG")
        rows.append({"path": os.path.join(src, name + ".jpg"), "filename": name + ".jpg",
                     "is_rejected": rejected})
    with open(os.path.join(src, "r1.CR2"), "wb") as handle:
        handle.write(b"RAW")
    seed_photos_prefix(src + "/", rows)
    target = os.path.join(root, "out")
    monkeypatch.setattr("api.routers.export._allowed_export_roots", lambda: [root])
    monkeypatch.setitem(api_config.VIEWER_CONFIG, "cull", {"allow_trash": True})

    def fake_trash(path):
        os.remove(path)
    monkeypatch.setattr("send2trash.send2trash", fake_trash)
    return type("Lib", (), {
        "env": env, "token": token, "src": src, "target": target,
        "r1": rows[0]["path"], "r2": rows[1]["path"], "k1": rows[2]["path"],
        "listing": staticmethod(lambda d: sorted(os.listdir(d)) if os.path.isdir(d) else [])})


class TestCullApply:
    def args(self, lib, **extra):
        return {"action": "move_rejects", "target_dir": lib.target, "paths": [lib.r1, lib.r2], **extra}

    def dry(self, lib, **extra):
        result = lib.env.call(lib.token, "cull_apply", self.args(lib, **extra))
        assert result["ok"], result
        return result["data"]

    def test_dry_run_moves_nothing_and_issues_a_nonce(self, library):
        data = self.dry(library)
        assert data["dry_run"] is True and data["would_move_count"] == 2 and data["confirm"]
        assert library.listing(library.target) == []

    def test_apply_without_a_dry_run_is_refused(self, library):
        result = library.env.call(library.token, "cull_apply", self.args(library, dry_run=False))
        assert result["error"] == "confirmation_required"
        assert library.listing(library.src) == ["k1.jpg", "r1.CR2", "r1.jpg", "r2.jpg"]

    def test_dry_run_then_apply_moves_files_without_companions_by_default(self, library):
        confirm = self.dry(library)["confirm"]
        done = library.env.call(library.token, "cull_apply", self.args(library, dry_run=False, confirm=confirm))
        assert done["ok"] and done["data"]["moved"] == 2
        assert library.listing(library.target) == ["r1.jpg", "r2.jpg"]
        assert library.listing(library.src) == ["k1.jpg", "r1.CR2"]

    def test_companions_follow_only_when_asked(self, library):
        data = self.dry(library, include_companions=True)
        assert data["would_move_count"] == 3
        done = library.env.call(library.token, "cull_apply", self.args(
            library, include_companions=True, dry_run=False, confirm=data["confirm"]))
        assert done["ok"] and "r1.CR2" in library.listing(library.target)

    def test_nonce_is_single_use(self, library):
        confirm = self.dry(library)["confirm"]
        args = self.args(library, dry_run=False, confirm=confirm)
        assert library.env.call(library.token, "cull_apply", args)["ok"]
        assert library.env.call(library.token, "cull_apply", args)["error"] == "confirmation_required"

    def test_garbage_nonce_is_refused(self, library):
        result = library.env.call(library.token, "cull_apply", self.args(library, dry_run=False, confirm="nope"))
        assert result["error"] == "confirmation_required"
        assert library.listing(library.target) == []

    def test_target_set_changed_since_the_dry_run(self, library):
        confirm = self.dry(library)["confirm"]
        headers = library.env.login(edition=True)
        resp = library.env.client.post("/api/photo/toggle_rejected", json={"photo_path": library.r2}, headers=headers)
        assert resp.status_code == 200
        result = library.env.call(library.token, "cull_apply", self.args(
            library, dry_run=False, confirm=confirm))
        assert result["error"] == "confirmation_required"
        assert library.listing(library.target) == [] and os.path.exists(library.r1)

    def test_nonce_is_bound_to_the_request_options_and_the_token(self, library):
        confirm = self.dry(library)["confirm"]
        other_set = library.env.call(library.token, "cull_apply", {
            "action": "move_rejects", "target_dir": library.target, "paths": [library.r1],
            "dry_run": False, "confirm": confirm})
        assert other_set["error"] == "confirmation_required"
        confirm = self.dry(library)["confirm"]
        env = library.env
        second = env.token(env.login(edition=True), "edition", name="other")
        stolen = env.call(second, "cull_apply", self.args(library, dry_run=False, confirm=confirm))
        assert stolen["error"] == "confirmation_required"
        # A stranger presenting it did not burn the owner's.
        assert env.call(library.token, "cull_apply", self.args(library, dry_run=False, confirm=confirm))["ok"]

    def test_nonce_expires(self, library):
        confirm = self.dry(library)["confirm"]
        later = time.monotonic() + nonce.TTL_SECONDS + 1
        limits.set_clock(lambda: later)
        result = library.env.call(library.token, "cull_apply", self.args(library, dry_run=False, confirm=confirm))
        assert result["error"] == "confirmation_required"
        assert os.path.exists(library.r1)

    def test_kept_photo_is_excluded_by_state_and_not_moved(self, library):
        data = self.dry(library, paths=[library.r1, library.k1])
        assert data["excluded_by_state"] == 1 and data["would_move_count"] == 1
        library.env.call(library.token, "cull_apply", self.args(
            library, paths=[library.r1, library.k1], dry_run=False, confirm=data["confirm"]))
        assert os.path.exists(library.k1) and not os.path.exists(library.r1)

    def test_copy_keeps_needs_no_nonce(self, library):
        done = library.env.call(library.token, "cull_apply", {
            "action": "copy_keeps", "target_dir": library.target, "paths": [library.k1], "dry_run": False})
        assert done["ok"] and done["data"]["copied"] == 1
        assert library.listing(library.target) == ["k1.jpg"]

    def test_trash_is_refused_upstream_when_disabled(self, library, monkeypatch):
        monkeypatch.setitem(api_config.VIEWER_CONFIG, "cull", {"allow_trash": False})
        result = library.env.call(library.token, "cull_apply", {"action": "trash_rejects", "paths": [library.r1]})
        assert result["ok"] is False and "allow_trash" in result["message"]
        assert os.path.exists(library.r1)

    def test_filter_scope_requires_expected_count(self, library):
        filters = {"path_prefix": library.src + "/"}
        result = library.env.call(library.token, "cull_apply", {
            "action": "move_rejects", "target_dir": library.target, "filters": filters})
        assert result["error"] == "invalid_input"
        wrong = library.env.call(library.token, "cull_apply", {
            "action": "move_rejects", "target_dir": library.target, "filters": filters, "expected_count": 7})
        assert wrong["error"] == "invalid_input" and wrong["actual_count"] == 3
        ok_run = library.env.call(library.token, "cull_apply", {
            "action": "move_rejects", "target_dir": library.target, "filters": filters, "expected_count": 3})
        assert ok_run["ok"] and ok_run["data"]["would_move_count"] == 2

    def test_a_file_missing_on_disk_is_skipped_with_a_reason(self, library):
        os.remove(library.r2)
        data = self.dry(library)
        assert data["skipped"] == [library.r2] and "skipped_reason" in data
        assert "disk" in data["skipped_reason"]

    def test_non_edition_tokens_are_refused(self, library, agent_app):
        env = agent_app("multi")
        for level in ("readonly", "user"):
            token = env.token(env.login("alice"), level)
            result = env.call(token, "cull_apply", self.args(library))
            assert result["error"] == "forbidden_level"

    def test_real_run_timeout_is_outcome_unknown(self, library, monkeypatch):
        confirm = self.dry(library)["confirm"]
        real = httpx.AsyncClient.request

        async def request(self, method, url, **kw):
            if str(url).endswith("/api/cull/apply") and kw.get("json", {}).get("dry_run") is False:
                raise httpx.ReadTimeout("slow")
            return await real(self, method, url, **kw)
        monkeypatch.setattr(httpx.AsyncClient, "request", request)
        result = library.env.call(library.token, "cull_apply", self.args(library, dry_run=False, confirm=confirm))
        assert result["error"] == "outcome_unknown"


class TestDeletePhotos:
    def count(self, lib):
        return db_row("SELECT COUNT(*) FROM photos WHERE path LIKE ?", lib.src + "/%")[0]

    def test_dry_run_deletes_nothing_then_apply_deletes_exactly_the_confirmed_set(self, library):
        def call(**kw):
            return library.env.call(library.token, "delete_photos", {"paths": [library.r1, library.k1], **kw})
        dry = call()["data"]
        assert dry["dry_run"] is True and dry["would_trash_count"] == 2 and self.count(library) == 3
        done = call(dry_run=False, confirm=dry["confirm"])
        assert done["ok"] and sorted(done["data"]["deleted"]) == sorted([library.r1, library.k1])
        assert self.count(library) == 1 and os.path.exists(library.r2)
        assert not os.path.exists(library.r1) and os.path.exists(os.path.join(library.src, "r1.CR2"))

    def test_apply_without_confirm_or_after_the_set_changed(self, library):
        def call(paths, **kw):
            return library.env.call(library.token, "delete_photos", {"paths": paths, **kw})
        assert call([library.r1], dry_run=False)["error"] == "confirmation_required"
        dry = call([library.r1, library.r2])["data"]
        os.remove(library.r2)
        again = call([library.r1, library.r2], dry_run=False, confirm=dry["confirm"])
        assert again["error"] == "confirmation_required" and self.count(library) == 3

    def test_user_token_is_refused(self, library, agent_app):
        env = agent_app("multi")
        token = env.token(env.login("alice"), "user")
        assert env.call(token, "delete_photos", {"paths": [library.r1]})["error"] == "forbidden_level"
        assert os.path.exists(library.r1)


class TestNonceModule:
    def test_digest_ignores_order_and_binds_options(self):
        assert nonce.digest(["b", "a"], {"x": 1}) == nonce.digest(["a", "b"], {"x": 1})
        assert nonce.digest(["a"], {"x": 1}) != nonce.digest(["a"], {"x": 2})

    def test_consume_semantics(self):
        digest = nonce.digest(["a"], {})
        value = nonce.issue(1, "act", digest)
        assert not nonce.consume(2, "act", digest, value)
        assert not nonce.consume(1, "other", digest, value)
        assert nonce.consume(1, "act", digest, value)
        assert not nonce.consume(1, "act", digest, value)
        burnt = nonce.issue(1, "act", digest)
        assert not nonce.consume(1, "act", nonce.digest(["b"], {}), burnt)
        assert not nonce.consume(1, "act", digest, burnt)

    def test_store_is_bounded(self):
        for _ in range(nonce.MAX_PENDING + 20):
            nonce.issue(1, "act", "h")
        assert len(nonce._pending) <= nonce.MAX_PENDING

    def test_one_token_cannot_flush_another_tokens_pending_nonce(self):
        nonce.reset()
        digest = nonce.digest(["a"], {})
        victim = nonce.issue(1, "act", digest)
        for _ in range(nonce.MAX_PENDING * 2):
            nonce.issue(2, "act", "h")
        assert nonce.consume(1, "act", digest, victim)
        assert sum(1 for entry in nonce._pending.values() if entry[0] == 2) <= nonce.MAX_PENDING_PER_TOKEN

    def test_global_cap_evicts_the_issuers_own_entries_first(self):
        nonce.reset()
        others = nonce.MAX_PENDING // nonce.MAX_PENDING_PER_TOKEN - 1
        for token in range(2, 2 + others):
            for _ in range(nonce.MAX_PENDING_PER_TOKEN):
                nonce.issue(token, "act", "h")
        for _ in range(30):
            nonce.issue(1, "act", "h")
        assert len(nonce._pending) == nonce.MAX_PENDING
        assert sum(1 for entry in nonce._pending.values() if entry[0] != 1) == others * nonce.MAX_PENDING_PER_TOKEN

    def test_global_cap_full_of_other_tokens_refuses_instead_of_evicting(self):
        nonce.reset()
        others = nonce.MAX_PENDING // nonce.MAX_PENDING_PER_TOKEN
        for token in range(2, 2 + others):
            for _ in range(nonce.MAX_PENDING_PER_TOKEN):
                nonce.issue(token, "act", "h")
        before = dict(nonce._pending)
        with pytest.raises(nonce.NonceCapacityError):
            nonce.issue(1, "act", "h")
        assert nonce._pending == before
