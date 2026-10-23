"""``target: "selection"``: the tab's selection as the scope of a write tool.

[REAL] ``agent_app`` (real auth chain), the real routes and a ``FakeTab`` on the real bridge;
the tab's ``ui_get_selection`` reply is scripted per test.
"""

import json
import os
import sqlite3

import pytest

from api import config as api_config
from api.agent.target import view_filters
from tests.conftest import _TEST_DB_FILE, AGENT_DIR, intercept_internal_call
from tests import test_agent_write

# The on-disk library of test_agent_write, reused as fixtures (the nonce tests need real files).
edition = test_agent_write.edition
library = test_agent_write.library

PFX = AGENT_DIR + "tgt/"
NAMES = [f"t{i}.jpg" for i in range(11)]
PATHS = [PFX + n for n in NAMES]


def jwt_of(headers):
    return headers["Authorization"].split(" ", 1)[1]


@pytest.fixture()
def rows(seed_photos_prefix):
    return seed_photos_prefix(PFX, [
        {"path": p, "filename": os.path.basename(p), "aggregate": 5.0, "star_rating": 1} for p in PATHS])


@pytest.fixture()
def setup(agent_app, fake_tab, rows):
    """``make(selection)`` -> ``(env, edition token, tab)`` with a tab answering ui_get_selection."""
    def make(selection, mode="legacy", level="edition"):
        env = agent_app(mode)
        headers = env.login(edition=True)
        tab = fake_tab(env, jwt_of(headers), reply=lambda call: (
            selection(call) if callable(selection) else {"ok": True, "data": selection}))
        return env, env.token(headers, level), tab
    return make


def paths_selection(paths, **extra):
    return {"scope": "paths", "count": len(paths), "paths": list(paths), **extra}


def view_selection(count, filters=None, excluded=(), **extra):
    return {"scope": "view", "count": count, "filters": {"path_prefix": PFX, "page": 1, "per_page": 64,
                                                         "sort": "aggregate", "sort_direction": "DESC",
                                                         "hide_bursts": "1"} if filters is None else filters,
            "excluded_paths": list(excluded), "excluded_count": len(excluded), "excluded_truncated": False, **extra}


def ratings():
    conn = sqlite3.connect(_TEST_DB_FILE.name)
    try:
        return dict(conn.execute("SELECT path, star_rating FROM photos WHERE path LIKE ?", (PFX + "%",)).fetchall())
    finally:
        conn.close()


class TestPathsSelection:
    def test_three_selected_paths_are_exactly_what_is_written(self, setup):
        env, token, tab = setup(paths_selection(PATHS[:3]))
        result = env.call(token, "batch_set_rating", {"target": "selection", "rating": 4})
        assert result["ok"], result
        assert result["data"]["affected"] == 3 and result["data"]["target"] == {
            "source": "tab_selection", "tab_id": "tab-1", "scope": "paths", "count": 3}
        assert [r for r in ratings().values()].count(4) == 3
        assert all(ratings()[p] == 4 for p in PATHS[:3])
        assert [c["tool"] for c in tab.calls] == ["ui_get_selection"]

    def test_a_truncated_selection_writes_nothing(self, setup):
        env, token, _ = setup({"scope": "paths", "count": 500, "paths": PATHS[:3], "truncated": True})
        result = env.call(token, "batch_set_rating", {"target": "selection", "rating": 4})
        assert result["error"] == "too_large"
        assert set(ratings().values()) == {1}

    def test_a_string_cut_by_the_bridge_is_refused_not_written(self, setup):
        env, token, _ = setup({"scope": "paths", "count": 1, "paths": ["x" * 3000]})
        result = env.call(token, "batch_set_rating", {"target": "selection", "rating": 4})
        assert result["error"] == "too_large" and "cut" in result["message"]
        assert set(ratings().values()) == {1}

    def test_an_exclusion_count_that_disagrees_with_the_list_is_refused(self, setup):
        longer = view_selection(9, excluded=PATHS[:2])
        longer["excluded_count"] = 1
        env, token, _ = setup(longer)
        assert env.call(token, "batch_set_rating", {"target": "selection", "rating": 3})["error"] == "too_large"
        assert set(ratings().values()) == {1}

    def test_a_count_that_disagrees_with_the_paths_writes_nothing(self, setup):
        env, token, _ = setup({"scope": "paths", "count": 5, "paths": PATHS[:3]})
        assert env.call(token, "batch_set_rating", {"target": "selection", "rating": 4})["error"] == "invalid_input"
        assert set(ratings().values()) == {1}

    def test_an_oversize_tab_reply_is_an_explicit_error_naming_the_frame_limit(self, setup):
        env, token, _ = setup({"ok": True, "data": {"scope": "paths", "count": 1, "paths": ["x" * 300000]}})
        result = env.call(token, "batch_set_rating", {"target": "selection", "rating": 4})
        assert result["error"] == "too_large" and "256 KB" in result["message"]
        assert set(ratings().values()) == {1}

    def test_album_add_and_tags_take_the_selection(self, setup):
        env, token, _ = setup(paths_selection(PATHS[:2]))
        album = env.call(token, "create_album", {"name": "from selection"})["data"]
        added = env.call(token, "album_add_photos", {"album_id": album["id"], "target": "selection"})
        assert added["ok"], added
        tagged = env.call(token, "add_tags", {"tags": ["picked"], "target": "selection"})
        assert tagged["ok"] and tagged["data"]["target"]["count"] == 2


class TestViewSelection:
    def test_matching_counts_write_the_whole_view(self, setup):
        env, token, _ = setup(view_selection(11))
        result = env.call(token, "batch_set_rating", {"target": "selection", "rating": 3})
        assert result["ok"], result
        assert result["data"]["affected"] == 11 and set(ratings().values()) == {3}

    def test_exclusions_are_carried_to_the_route(self, setup):
        env, token, _ = setup(view_selection(9, excluded=PATHS[:2]))
        result = env.call(token, "batch_set_rating", {"target": "selection", "rating": 3})
        assert result["ok"], result
        assert ratings()[PATHS[0]] == 1 and ratings()[PATHS[1]] == 1 and ratings()[PATHS[5]] == 3

    def test_a_view_that_grew_is_selection_changed_and_nothing_is_written(self, setup):
        # The tab says 10, the server counts 11.
        env, token, _ = setup(view_selection(10))
        result = env.call(token, "batch_set_rating", {"target": "selection", "rating": 3})
        assert result["error"] == "invalid_input" and "selection_changed" in result["message"]
        assert set(ratings().values()) == {1}

    def test_truncated_or_short_exclusion_lists_are_refused(self, setup):
        env, token, _ = setup(view_selection(9, excluded=PATHS[:2], excluded_truncated=True))
        assert env.call(token, "batch_set_rating", {"target": "selection", "rating": 3})["error"] == "too_large"
        short = view_selection(9, excluded=PATHS[:1])
        short["excluded_count"] = 2
        env2, token2, _ = setup(short)
        assert env2.call(token2, "batch_set_rating", {"target": "selection", "rating": 3})["error"] == "too_large"
        assert set(ratings().values()) == {1}

    def test_a_view_without_filters_cannot_be_targeted(self, setup):
        env, token, _ = setup({"scope": "view", "count": 11, "filters": None, "excluded_paths": [],
                               "excluded_count": 0, "excluded_truncated": False})
        result = env.call(token, "batch_set_rating", {"target": "selection", "rating": 3})
        assert result["error"] == "invalid_input" and "as a whole" in result["message"]
        assert set(ratings().values()) == {1}

    def test_a_key_outside_the_gallery_filters_is_refused(self, setup):
        env, token, _ = setup(view_selection(11, filters={"path_prefix": PFX, "drop": "1"}))
        assert env.call(token, "batch_set_rating", {"target": "selection", "rating": 3})["error"] == "invalid_input"
        assert set(ratings().values()) == {1}

    def test_a_person_filtered_view_writes_only_that_persons_photos(self, setup):
        conn = sqlite3.connect(_TEST_DB_FILE.name)
        conn.execute("INSERT INTO persons(id, name, auto_clustered, face_count) VALUES (987101, 'Bo', 0, 2)")
        for index in (0, 1):
            conn.execute("INSERT INTO faces(photo_path, face_index, embedding, person_id) VALUES (?, 0, ?, 987101)",
                         (PATHS[index], b"\x00" * 8))
        conn.commit()
        try:
            env, token, _ = setup(view_selection(2, filters={"path_prefix": PFX, "person_id": 987101,
                                                              "sort_direction": "DESC"}))
            result = env.call(token, "batch_set_rating", {"target": "selection", "rating": 5})
            assert result["ok"], result
            assert result["data"]["affected"] == 2
            assert ratings()[PATHS[0]] == 5 and ratings()[PATHS[1]] == 5 and ratings()[PATHS[2]] == 1
        finally:
            conn.execute("DELETE FROM faces WHERE person_id = 987101")
            conn.execute("DELETE FROM persons WHERE id = 987101")
            conn.commit()
            conn.close()

    def test_a_path_only_tool_expands_the_view_minus_exclusions(self, setup):
        env, token, _ = setup(view_selection(9, excluded=PATHS[:2]))
        album = env.call(token, "create_album", {"name": "view album"})["data"]
        added = env.call(token, "album_add_photos", {"album_id": album["id"], "target": "selection"})
        assert added["ok"], added
        assert added["data"]["target"]["scope"] == "view"
        listed = env.call(token, "list_albums", {})
        assert [a["photo_count"] for a in listed["data"]["rows"] if a["id"] == album["id"]] == [9]

    def test_hide_toggles_are_not_added_to_the_tabs_payload(self, setup, monkeypatch):
        seen = []

        def spy(tool, kw):
            if tool == "photos_count":
                seen.append(dict(kw["query"]))

        intercept_internal_call(monkeypatch, spy)
        monkeypatch.setitem(api_config.VIEWER_CONFIG["defaults"], "hide_bursts", True)
        monkeypatch.setitem(api_config.VIEWER_CONFIG["defaults"], "hide_panoramas", True)
        env, token, _ = setup(view_selection(11, filters={"path_prefix": PFX}))
        assert env.call(token, "batch_set_rating", {"target": "selection", "rating": 3})["ok"]
        assert seen == [{"path_prefix": PFX}]


class TestArguments:
    def test_exactly_one_scope(self, setup):
        env, token, tab = setup(paths_selection(PATHS[:1]))
        both = env.call(token, "batch_set_rating", {"target": "selection", "paths": PATHS[:1], "rating": 2})
        assert both["error"] == "invalid_input"
        neither = env.call(token, "album_add_photos", {"album_id": 1})
        assert neither["error"] == "invalid_input"
        extra = env.call(token, "batch_set_rating", {"target": "selection", "rating": 2, "exclude": PATHS[:1]})
        assert extra["error"] == "invalid_input"
        assert tab.calls == [] and set(ratings().values()) == {1}

    def test_no_tab_is_no_tab_and_writes_nothing(self, agent_app, rows):
        env = agent_app("legacy")
        token = env.token(env.login(edition=True), "edition")
        result = env.call(token, "batch_set_rating", {"target": "selection", "rating": 2})
        assert result["error"] == "no_tab"
        assert set(ratings().values()) == {1}

    def test_a_readonly_token_is_refused_before_any_tab_call(self, setup):
        env, token, tab = setup(paths_selection(PATHS[:1]), level="readonly")
        result = env.call(token, "batch_set_rating", {"target": "selection", "rating": 2})
        assert result["error"] == "forbidden_level"
        assert tab.calls == []

    def test_view_filters_helper(self):
        assert view_filters(None)[0]["error"] == "invalid_input"
        assert view_filters({"camera": "X", "page": 3, "hide_bursts": True}) == (None, {"camera": "X", "hide_bursts": "1"})
        assert view_filters({"camera": ["x"]})[0] is not None


class TestDeleteConfirmationFollowsTheSelection:
    def test_changing_the_selection_between_dry_run_and_confirm_voids_it(self, library, fake_tab):
        state = {"paths": [library.r1]}
        headers = library.env.login(edition=True)
        fake_tab(library.env, jwt_of(headers), reply=lambda call: {
            "ok": True, "data": paths_selection(state["paths"])})
        token = library.env.token(headers, "edition")
        dry = library.env.call(token, "delete_photos", {"target": "selection"})
        assert dry["ok"] and dry["data"]["would_trash_count"] == 1 and dry["data"]["confirm"]
        state["paths"] = [library.r1, library.r2]
        again = library.env.call(token, "delete_photos", {"target": "selection", "dry_run": False,
                                                          "confirm": dry["data"]["confirm"]})
        assert again["error"] == "confirmation_required"
        assert os.path.exists(library.r1) and os.path.exists(library.r2)
        final = library.env.call(token, "delete_photos", {"target": "selection"})
        assert final["data"]["would_trash_count"] == 2
        done = library.env.call(token, "delete_photos", {"target": "selection", "dry_run": False,
                                                         "confirm": final["data"]["confirm"]})
        assert done["ok"], done
        assert not os.path.exists(library.r1) and not os.path.exists(library.r2)


class TestExportMetadataTarget:
    def test_the_selection_of_two_is_what_is_exported(self, setup):
        env, token, tab = setup(paths_selection(PATHS[:2]))
        result = env.call(token, "export_metadata", {"target": "selection"})
        assert result["ok"], result
        # The seeded rows have no file on disk, so both are counted as skipped.
        assert result["data"]["skipped"] == 2 and result["data"]["target"]["count"] == 2
        assert [c["tool"] for c in tab.calls] == ["ui_get_selection"]


ALBUM_PREFIX = "tgt-album "


@pytest.fixture()
def made_albums():
    yield
    conn = sqlite3.connect(_TEST_DB_FILE.name)
    ids = [r[0] for r in conn.execute("SELECT id FROM albums WHERE name LIKE ?", (ALBUM_PREFIX + "%",))]
    for album_id in ids:
        conn.execute("DELETE FROM album_photos WHERE album_id = ?", (album_id,))
        conn.execute("DELETE FROM albums WHERE id = ?", (album_id,))
    conn.commit()
    conn.close()


def albums_named(name):
    conn = sqlite3.connect(_TEST_DB_FILE.name)
    try:
        return conn.execute("SELECT id, is_smart, smart_filter_json FROM albums WHERE name = ?", (name,)).fetchall()
    finally:
        conn.close()


def gallery_view(stored=None, total=11, **over):
    """What the tab's ``ui_get_gallery_view`` reports: its contract filters plus the smart-album JSON of its store."""
    stored = {"path_prefix": PFX, "sort": "aggregate", "sort_direction": "DESC"} if stored is None else stored
    return {"route": "/", "filters": {"path_prefix": PFX, "hide_bursts": "1", "sort": "aggregate"},
            "total": total, "loaded": 11, "has_more": False, "photos": [], "selection_count": 0, "loading": False,
            "album_filter_json": json.dumps(stored), "filters_scopable": True, **over}


class TestCreateAlbumFromTheView:
    def test_the_views_store_form_filters_become_a_smart_album_as_the_tab_wrote_them(self, setup, made_albums):
        view = gallery_view()
        env, token, tab = setup(view)
        result = env.call(token, "create_album", {"name": ALBUM_PREFIX + "view", "target": "view"})
        assert result["ok"], result
        data = result["data"]
        assert data["is_smart"] is True and data["photo_count"] == 11
        assert data["smart_filter_json"] == view["album_filter_json"]
        assert data["target"] == {"source": "tab_view", "tab_id": "tab-1", "count": 11}
        assert [(c["tool"], c["args"]) for c in tab.calls] == [("ui_get_gallery_view", {"limit": 1})]
        assert len(albums_named(ALBUM_PREFIX + "view")) == 1

    def test_a_top_picks_view_is_stored_with_its_type(self, setup, made_albums):
        env, token, _ = setup(gallery_view({"type": "top_picks", "path_prefix": PFX}, total=0))
        result = env.call(token, "create_album", {"name": ALBUM_PREFIX + "picks", "target": "view"})
        assert result["ok"], result
        assert json.loads(result["data"]["smart_filter_json"])["type"] == "top_picks"
        assert result["data"]["photo_count"] == 0 and "warning" in result["data"]

    def test_a_total_the_stored_filters_do_not_reproduce_creates_nothing(self, setup, made_albums):
        env, token, _ = setup(gallery_view(total=5))
        result = env.call(token, "create_album", {"name": ALBUM_PREFIX + "mismatch", "target": "view"})
        assert result["error"] == "invalid_input" and "would list 11" in result["message"]
        assert albums_named(ALBUM_PREFIX + "mismatch") == []

    @pytest.mark.parametrize("over, fragment", [
        ({"loading": True}, "still loading"),
        ({"filters_scopable": False}, "cannot be saved"),
        ({"route": "/album/3"}, "main gallery"),
        ({"album_filter_json": "not json"}, "unusable"),
        ({"album_filter_json": json.dumps({"path_prefix": 5})}, "unusable"),
        ({"album_filter_json": json.dumps(["path_prefix"])}, "unusable"),
        ({"album_filter_json": json.dumps({"drop": "1"})}, "does not know"),
    ])
    def test_a_view_a_stored_album_cannot_hold_is_refused(self, setup, made_albums, over, fragment):
        env, token, _ = setup(gallery_view(**over))
        result = env.call(token, "create_album", {"name": ALBUM_PREFIX + "refused", "target": "view"})
        assert result["error"] == "invalid_input" and fragment in result["message"]
        assert albums_named(ALBUM_PREFIX + "refused") == []

    @pytest.mark.parametrize("key", ["hide_bursts", "gps_lat", "album_id", "similar_to", "per_page"])
    def test_a_display_only_or_album_key_in_the_stored_json_is_unsupported(self, setup, made_albums, key):
        env, token, _ = setup(gallery_view({"path_prefix": PFX, key: "1"}))
        result = env.call(token, "create_album", {"name": ALBUM_PREFIX + "keys", "target": "view"})
        assert result["error"] in ("unsupported_filters", "invalid_input"), result
        assert albums_named(ALBUM_PREFIX + "keys") == []

    def test_view_cannot_be_combined_with_paths(self, setup, made_albums):
        env, token, _ = setup(gallery_view())
        result = env.call(token, "create_album", {"name": ALBUM_PREFIX + "both", "target": "view", "paths": PATHS[:1]})
        assert result["error"] == "invalid_input" and albums_named(ALBUM_PREFIX + "both") == []

    def test_other_write_tools_do_not_offer_the_view_target(self, setup):
        env, token, _ = setup(gallery_view())
        result = env.call(token, "batch_set_rating", {"target": "view", "rating": 3})
        assert result["error"] == "invalid_input"
        assert set(ratings().values()) == {1}

    def test_in_page_the_calls_own_snapshot_is_the_view(self, agent_app, rows, made_albums):
        env = agent_app("legacy")
        headers = env.login(edition=True)
        view = gallery_view()
        resp = env.client.post(
            "/api/mcp/call", headers={**headers, "X-Facet-Agent-Session": "tab-a"},
            json={"tool": "create_album", "arguments": {"name": ALBUM_PREFIX + "inpage", "target": "view"},
                  "selection_snapshot": view})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"], body
        assert body["data"]["smart_filter_json"] == view["album_filter_json"] and body["data"]["photo_count"] == 11
        refused = env.client.post(
            "/api/mcp/call", headers={**headers, "X-Facet-Agent-Session": "tab-a"},
            json={"tool": "create_album", "arguments": {"name": ALBUM_PREFIX + "nosnap", "target": "view"}})
        assert refused.json()["error"] == "invalid_input"
        assert albums_named(ALBUM_PREFIX + "nosnap") == []


class TestCreateAlbumFromTheSelection:
    def album_paths(self, album_id):
        conn = sqlite3.connect(_TEST_DB_FILE.name)
        try:
            return sorted(r[0] for r in conn.execute("SELECT photo_path FROM album_photos WHERE album_id = ?", (album_id,)))
        finally:
            conn.close()

    def test_selected_paths_fill_a_new_fixed_album(self, setup, made_albums):
        env, token, _ = setup(paths_selection(PATHS[:3]))
        result = env.call(token, "create_album", {"name": ALBUM_PREFIX + "picked", "target": "selection"})
        assert result["ok"], result
        assert result["data"]["added"] == 3 and result["data"]["skipped"] == []
        assert result["data"]["target"]["scope"] == "paths"
        assert self.album_paths(result["data"]["id"]) == sorted(PATHS[:3])

    def test_a_whole_view_selection_is_expanded_minus_its_exclusions(self, setup, made_albums):
        env, token, _ = setup(view_selection(9, excluded=PATHS[:2]))
        result = env.call(token, "create_album", {"name": ALBUM_PREFIX + "wholeview", "target": "selection"})
        assert result["ok"], result
        assert self.album_paths(result["data"]["id"]) == sorted(PATHS[2:])

    def test_an_empty_selection_creates_no_album(self, setup, made_albums):
        env, token, _ = setup(paths_selection([]))
        result = env.call(token, "create_album", {"name": ALBUM_PREFIX + "nothing", "target": "selection"})
        assert result["error"] == "invalid_input" and albums_named(ALBUM_PREFIX + "nothing") == []
