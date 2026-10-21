"""Live UI updates on MCP writes: the path extractor, the write classification and the ``changed`` frame.

[REAL] ``agent_app`` (production auth chain and lifespan, no ``dependency_overrides``), real write routes
against seeded rows, and scripted browser tabs on the real bridge socket.
"""

import time

import pytest

from api.agent import live_updates
from api.agent.internal_client import ROUTE_ALLOWLIST
from api.agent.live_updates import (
    MAX_LIVE_PATHS, NO_PHOTO_EFFECT_TOOLS, PHOTO_EFFECT_TOOLS, changed_paths, frame_for,
)
from api.agent.tools_culling import CULLING_ROUTES
from tests import test_agent_write as write_tests
from tests.conftest import AGENT_DIR

P, ROWS = write_tests.P, write_tests.ROWS


def jwt_of(headers):
    return headers["Authorization"].split(" ", 1)[1]


class TestChangedPaths:
    @pytest.mark.parametrize("body,expected", [
        ({"photo_paths": ["/a", "/b"]}, ["/a", "/b"]),
        ({"photo_path": "/a", "rating": 3}, ["/a"]),
        ({"paths": ["/a"], "action": "move_rejects"}, ["/a"]),
        ({"path": "/a", "category": "x"}, ["/a"]),
        ({"photo_paths": ["/a", "/a", "/b", "/a"]}, ["/a", "/b"]),
        ({"filters": {"tag": "x"}}, None),
        ({}, None),
        ({"face_ids": [1, 2]}, None),
        ({"photo_paths": [f"/p{i}" for i in range(MAX_LIVE_PATHS + 1)]}, None),
        ({"paths": ["/a"], "include_sequence_siblings": True}, None),
    ])
    def test_body_shapes(self, body, expected):
        assert changed_paths("batch_reject", body) == expected

    def test_exactly_the_cap_is_kept(self):
        paths = [f"/p{i}" for i in range(MAX_LIVE_PATHS)]
        assert changed_paths("batch_reject", {"photo_paths": paths}) == paths

    def test_non_dict_body_is_none(self):
        assert changed_paths("batch_reject", None) is None
        assert changed_paths("batch_reject", ["x"]) is None


class TestFrameFor:
    def test_frame_shape(self):
        assert frame_for("set_rating", {"photo_path": "/a", "rating": 2}, {"success": True}) == {
            "type": "changed", "tool": "set_rating", "paths": ["/a"], "count": 1}

    def test_null_paths_take_the_response_affected_count(self):
        frame = frame_for("batch_reject", {"filters": {"x": 1}}, {"count": 7})
        assert frame == {"type": "changed", "tool": "batch_reject", "paths": None, "count": 7}

    def test_null_paths_without_a_response_count_is_none(self):
        assert frame_for("batch_reject", {"filters": {}}, None)["count"] is None

    def test_sibling_widening_is_null_with_the_response_count(self):
        frame = frame_for("cull_apply", {"paths": ["/a"], "include_sequence_siblings": True, "dry_run": False},
                          {"moved": 4})
        assert frame["paths"] is None and frame["count"] == 4

    def test_assign_faces_is_a_coarse_reload(self):
        frame = frame_for("assign_faces", {"face_ids": [1, 2]}, {"assigned": 2, "count": 2})
        assert frame["paths"] is None

    @pytest.mark.parametrize("tool", sorted(NO_PHOTO_EFFECT_TOOLS))
    def test_unrelated_writes_emit_nothing(self, tool):
        assert frame_for(tool, {"name": "x"}, {}) is None

    def test_unknown_tool_emits_nothing(self):
        assert frame_for("search_photos", {"photo_path": "/a"}, {}) is None

    def test_culling_auto_dry_run_emits_nothing(self):
        assert frame_for("culling.auto", {"dry_run": True}, {"rejected": 3}) is None

    def test_culling_auto_apply_emits(self):
        frame = frame_for("culling.auto", {"dry_run": False}, {"rejected": 3, "kept": 9})
        assert frame == {"type": "changed", "tool": "culling.auto", "paths": None, "count": 3}

    def test_culling_confirm_emits_its_paths(self):
        frame = frame_for("culling.confirm", {"group_id": 1, "type": "burst", "paths": ["/a", "/b"],
                                             "keep_paths": ["/a"]}, {})
        assert frame["paths"] == ["/a", "/b"]

    def test_cull_apply_dry_run_emits_nothing(self):
        assert frame_for("cull_apply", {"paths": ["/a"], "dry_run": True}, {}) is None

    def test_a_dry_run_flag_that_is_not_true_still_emits(self):
        assert frame_for("cull_apply", {"paths": ["/a"], "dry_run": False}, {})["paths"] == ["/a"]


class TestClassification:
    def test_every_write_route_is_classified_exactly_once(self):
        routes = {**ROUTE_ALLOWLIST, **CULLING_ROUTES}
        writes = {name for name, spec in routes.items() if spec.write}
        assert PHOTO_EFFECT_TOOLS.isdisjoint(NO_PHOTO_EFFECT_TOOLS)
        unclassified = writes - PHOTO_EFFECT_TOOLS - NO_PHOTO_EFFECT_TOOLS
        assert not unclassified, f"classify these write routes in api/agent/live_updates.py: {sorted(unclassified)}"
        stale = (PHOTO_EFFECT_TOOLS | NO_PHOTO_EFFECT_TOOLS) - writes
        assert not stale, f"classified names that are not write routes: {sorted(stale)}"

    def test_culling_routes_are_in_the_walk(self):
        assert {"culling.auto", "culling.confirm"} <= PHOTO_EFFECT_TOOLS

    def test_a_new_write_route_fails_the_walk(self, monkeypatch):
        from api.agent.internal_client import RouteSpec
        extra = {**ROUTE_ALLOWLIST, "brand_new": RouteSpec("POST", "/api/x", "edition", write=True)}
        writes = {name for name, spec in {**extra, **CULLING_ROUTES}.items() if spec.write}
        assert writes - PHOTO_EFFECT_TOOLS - NO_PHOTO_EFFECT_TOOLS == {"brand_new"}


def changed_frames(tab):
    return [m for m in tab.inbox if m.get("type") == "changed"]


def wait_frames(tab, count, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(changed_frames(tab)) >= count:
            break
        time.sleep(0.05)
    return changed_frames(tab)


def settle(tab, seconds=0.6):
    time.sleep(seconds)
    return changed_frames(tab)


@pytest.fixture()
def photos(seed_photos_prefix):
    write_tests.wipe_prefs()
    yield seed_photos_prefix(AGENT_DIR, ROWS)
    write_tests.wipe_prefs()


@pytest.fixture()
def edition(agent_app):
    env = agent_app("legacy", allow_destructive=True)
    headers = env.login(edition=True)
    return env, env.token(headers, "edition"), headers


class TestBroadcastOverMcp:
    def test_batch_write_puts_one_frame_on_the_owners_tab(self, edition, photos, fake_tab):
        env, token, headers = edition
        tab = fake_tab(env, jwt_of(headers))
        result = env.call(token, "batch_set_rejected", {"paths": P[:2]})
        assert result["ok"], result
        frames = wait_frames(tab, 1)
        assert len(settle(tab)) == 1
        assert frames[0] == {"type": "changed", "tool": "batch_reject", "paths": P[:2], "count": 2}

    def test_per_photo_write_sends_one_frame_per_path(self, edition, photos, fake_tab):
        env, token, headers = edition
        tab = fake_tab(env, jwt_of(headers))
        assert env.call(token, "set_rejected", {"paths": P[:4], "value": True})["ok"]
        frames = wait_frames(tab, 4)
        assert len(settle(tab)) == 4
        assert sorted(f["paths"][0] for f in frames) == sorted(P[:4])
        assert all(f["tool"] == "toggle_rejected" and f["count"] == 1 for f in frames)

    def test_another_principal_receives_nothing(self, agent_app, photos, fake_tab):
        env = agent_app("multi", allow_destructive=True)
        root = env.login("root")
        alice_tab = fake_tab(env, jwt_of(env.login("alice")), "tab-alice")
        root_tab = fake_tab(env, jwt_of(root), "tab-root")
        token = env.token(root, "edition")
        assert env.call(token, "batch_set_rejected", {"paths": P[:1]})["ok"]
        assert len(wait_frames(root_tab, 1)) == 1
        assert settle(alice_tab) == []

    def test_reads_emit_no_frame(self, edition, photos, fake_tab):
        env, token, headers = edition
        tab = fake_tab(env, jwt_of(headers))
        assert env.call(token, "search_photos", {})["ok"]
        assert env.call(token, "get_photo", {"path": P[0]})["ok"]
        assert settle(tab) == []

    def test_a_refused_write_emits_no_frame(self, agent_app, photos, fake_tab):
        env = agent_app("legacy")
        headers = env.login()
        token = env.token(headers, "readonly")
        tab = fake_tab(env, jwt_of(headers))
        result = env.call(token, "batch_set_rejected", {"paths": P[:1]})
        assert not result["ok"]
        assert settle(tab) == []

    def test_an_upstream_4xx_emits_no_frame(self, edition, photos, fake_tab):
        env, token, headers = edition
        tab = fake_tab(env, jwt_of(headers))
        result = env.call(token, "set_caption", {"path": AGENT_DIR + "does-not-exist.jpg", "caption": "x"})
        assert not result["ok"], result
        assert settle(tab) == []

    def test_a_filter_scoped_batch_is_null_with_the_affected_count(self, edition, photos, fake_tab):
        env, token, headers = edition
        tab = fake_tab(env, jwt_of(headers))
        result = env.call(token, "batch_set_rejected",
                          {"filters": {"path_prefix": AGENT_DIR}, "expected_count": len(P)})
        assert result["ok"], result
        frame = wait_frames(tab, 1)[0]
        assert frame["paths"] is None and frame["count"] == result["data"]["affected"] > 0

    def test_over_the_cap_is_null(self, edition, photos, fake_tab, monkeypatch):
        env, token, headers = edition
        monkeypatch.setattr(live_updates, "MAX_LIVE_PATHS", 2)
        tab = fake_tab(env, jwt_of(headers))
        assert env.call(token, "batch_set_rejected", {"paths": P[:3]})["ok"]
        frame = wait_frames(tab, 1)[0]
        assert frame["paths"] is None and frame["count"] == 3

    def test_a_closed_conn_does_not_break_the_write(self, edition, photos, fake_tab):
        env, token, headers = edition
        tab = fake_tab(env, jwt_of(headers))
        registry = env.app.state.tab_registry
        conn = registry.tabs_for("_legacy")[0]
        conn.closed = True
        tab.stop()
        assert env.call(token, "batch_set_rejected", {"paths": P[:1]})["ok"]

    def test_auto_cull_apply_emits_one_frame_and_its_dry_run_none(self, agent_app, seed_photos_prefix, fake_tab):
        from api.agent import nonce
        from tests import test_agent_culling as culling
        seed_photos_prefix(culling.PREFIX, culling.ROWS)
        nonce.reset()
        env = agent_app("legacy")
        headers = env.login(edition=True)
        token = env.token(headers, "edition")
        tab = fake_tab(env, jwt_of(headers))
        args = {"group_by": "burst", **culling.SCOPE}
        preview = env.call(token, "auto_cull", {**args, "strictness": 0})
        assert preview["ok"] and preview["confirm"], preview
        assert settle(tab) == []
        applied = env.call(token, "auto_cull", {**args, "strictness": 0, "dry_run": False,
                                                "confirm": preview["confirm"]})
        assert applied["ok"], applied
        frames = wait_frames(tab, 1)
        assert len(settle(tab)) == 1
        assert frames[0]["tool"] == "culling.auto" and frames[0]["paths"] is None
        assert frames[0]["count"] == applied["data"]["rejected"] > 0
