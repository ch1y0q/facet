"""Searches are shown in the user's tab: the pure mappers and the relay through a scripted tab.

[REAL] ``agent_app`` (real auth chain, real lifespan) and a ``FakeTab`` on the real bridge.
"""

import pytest

from api import config as api_config
from api.agent import show
from api.agent.tools_read import HIDE_DEFAULT_KEYS
from tests.conftest import AGENT_DIR

ROWS = [{"path": AGENT_DIR + f"show/{i}.jpg", "filename": f"{i}.jpg", "aggregate": 5.0 + i,
         "aesthetic": 4.0 + i, "caption": "a red sunset" if i == 0 else "a street"} for i in range(3)]
PREFIX = AGENT_DIR + "show/"


@pytest.fixture()
def photos(seed_photos_prefix):
    return seed_photos_prefix(PREFIX, ROWS)


def reply_total(total=7):
    return lambda call: {"ok": True, "data": {"applied": list(call["args"]["patch"]), "total": total}}


def sort_pair():
    return show.effective_sort(None, None)


def hide_patch():
    defaults = api_config.VIEWER_CONFIG["defaults"]
    return {key: True for key in HIDE_DEFAULT_KEYS if defaults.get(key)}


class TestMappers:
    def test_search_patch_is_the_filters_plus_the_effective_sort(self):
        patch, reason = show.search_patch({"camera": "Canon", "min_aesthetic": 7.0, "hide_bursts": True},
                                          "date_taken", "asc")
        assert reason is None
        assert patch == {"camera": "Canon", "min_aesthetic": 7.0, "hide_bursts": True,
                         "sort": "date_taken", "sort_direction": "asc"}

    def test_sort_falls_back_to_the_viewer_default(self, monkeypatch):
        monkeypatch.setitem(api_config.VIEWER_CONFIG, "defaults", {"sort": "aesthetic", "sort_direction": "ASC"})
        assert show.effective_sort(None, None) == {"sort": "aesthetic", "sort_direction": "asc"}

    def test_unsupported_keys_are_listed_not_partially_applied(self):
        patch, reason = show.search_patch({"camera": "Canon", "min_rating": 3, "junk_kind": "blurry"}, None, None)
        assert patch == {}
        assert reason == {"applied": False, "reason": "unsupported_filters", "keys": ["junk_kind", "min_rating"]}

    def test_show_rejected_false_is_the_normal_listing_not_unsupported(self):
        patch, reason = show.search_patch({"show_rejected": False, "camera": "Canon"}, None, None)
        assert reason is None and "show_rejected" not in patch
        assert show.search_patch({"show_rejected": True}, None, None)[1]["keys"] == ["show_rejected"]

    @pytest.mark.parametrize("ignored", [
        {"is_silhouette": False}, {"exclude_tags": ""}, {"require_tags": "  "},
        {"min_rating": 0}, {"min_rating": 6}, {"min_rating": "x"}])
    def test_a_value_the_route_ignores_is_not_unsupported(self, ignored):
        patch, reason = show.search_patch({**ignored, "camera": "X"}, None, None)
        assert reason is None and patch["camera"] == "X" and not set(ignored) & set(patch)

    def test_type_together_with_category_is_an_invalid_combination(self):
        assert show.search_patch({"type": "portrait", "category": "macro"}, None, None)[1]["reason"] == "invalid_combination"

    def test_semantic_patch_always_sends_the_knobs(self):
        patch, reason = show.semantic_patch("red sunset", 0.25, None, "aggregate", "desc")
        assert reason is None
        assert patch == {"semantic_query": "red sunset", "semantic_threshold": 0.25, "similar_to": None,
                         "similarity_mode": None, "min_similarity": None,
                         "sort": "aggregate", "sort_direction": "desc"}

    def test_semantic_text_scope_and_a_threshold_over_the_slider_are_unsupported(self):
        assert show.semantic_patch("x", None, "text")[1] == {
            "applied": False, "reason": "unsupported_filters", "keys": ["scope"]}
        assert show.semantic_patch("x", 0.9, None)[1]["keys"] == ["threshold"]

    @pytest.mark.parametrize("mode,floor", [("visual", 0.40), ("color", 0.40), ("person", 0.0)])
    def test_similar_patch_sends_the_floor_the_route_used(self, mode, floor):
        patch = show.similar_patch("/a.jpg", mode, None, "aggregate", "desc")
        assert patch["min_similarity"] == floor and patch["similarity_mode"] == mode
        assert show.similar_patch("/a.jpg", mode, 0.8)["min_similarity"] == 0.8


class TestSearchRelay:
    def test_the_tab_gets_one_replace_frame_with_the_exact_patch(self, agent_app, fake_tab, photos):
        env = agent_app("open")
        assert hide_patch(), "the shipped defaults hide sets; the hide toggles must reach the patch"
        tab = fake_tab(env, None, reply=reply_total(7))
        result = env.call(env.token(env.login()), "search_photos", {
            "filters": {"min_aesthetic": 4.0, "path_prefix": PREFIX}})
        assert result["ok"] is True and len(tab.calls) == 1
        assert tab.calls[0]["tool"] == "ui_set_gallery_filters"
        assert tab.calls[0]["args"] == {
            "patch": {"min_aesthetic": 4.0, "path_prefix": PREFIX, **hide_patch(), **sort_pair()},
            "replace": True}
        shown = result["shown_in_tab"]
        assert shown["applied"] is True and shown["tab_id"] == "tab-1" and shown["total"] == 7
        assert "min_aesthetic" in shown["keys"] and "filters" not in shown

    def test_show_false_sends_nothing(self, agent_app, fake_tab, photos):
        env = agent_app("open")
        tab = fake_tab(env, None, reply=reply_total())
        token = env.token(env.login())
        args = {"filters": {"path_prefix": PREFIX}}
        assert "shown_in_tab" in env.call(token, "search_photos", args)
        assert len(tab.calls) == 1
        quiet = env.call(token, "search_photos", {**args, "show": False})
        assert quiet["ok"] is True and "shown_in_tab" not in quiet
        assert len(tab.calls) == 1

    def test_a_later_page_is_not_reapplied(self, agent_app, fake_tab, photos):
        env = agent_app("open")
        tab = fake_tab(env, None, reply=reply_total())
        result = env.call(env.token(env.login()), "search_photos", {
            "filters": {"path_prefix": PREFIX}, "per_page": 1, "page": 2})
        assert result["ok"] is True
        assert result["shown_in_tab"] == {"applied": False, "reason": "page_not_first"}
        assert tab.calls == []

    def test_an_empty_result_keeps_the_users_view(self, agent_app, fake_tab, photos):
        env = agent_app("open")
        tab = fake_tab(env, None, reply=reply_total())
        result = env.call(env.token(env.login()), "search_photos", {"filters": {"path_prefix": "/nowhere/"}})
        assert result["ok"] is True and result["shown_in_tab"]["reason"] == "empty_result"
        assert tab.calls == []

    def test_unsupported_filters_skip_the_whole_show(self, agent_app, fake_tab, photos):
        env = agent_app("open")
        tab = fake_tab(env, None, reply=reply_total())
        result = env.call(env.token(env.login()), "search_photos", {
            "filters": {"path_prefix": PREFIX, "exclude_tags": "zzz"}})
        assert result["ok"] is True
        assert result["shown_in_tab"] == {"applied": False, "reason": "unsupported_filters", "keys": ["exclude_tags"]}
        assert tab.calls == []

    def test_no_tab_never_fails_the_search(self, agent_app, photos):
        env = agent_app("open")
        result = env.call(env.token(env.login()), "search_photos", {"filters": {"path_prefix": PREFIX}})
        assert result["ok"] is True and len(result["data"]["rows"]) == 3
        assert result["shown_in_tab"]["applied"] is False and result["shown_in_tab"]["reason"] == "no_tab"

    def test_bridge_off_reports_it(self, agent_app, photos):
        env = agent_app("open", bridge=False)
        result = env.call(env.token(env.login()), "search_photos", {"filters": {"path_prefix": PREFIX}})
        assert result["ok"] is True and result["shown_in_tab"]["reason"] == "bridge_disabled"

    def test_an_outdated_tab_is_reported(self, agent_app, fake_tab, photos):
        env = agent_app("open")
        fake_tab(env, None, version="old")
        result = env.call(env.token(env.login()), "search_photos", {"filters": {"path_prefix": PREFIX}})
        assert result["ok"] is True and result["shown_in_tab"]["reason"] == "tab_outdated"

    def test_a_tab_refusal_is_reported_faithfully(self, agent_app, fake_tab, photos):
        env = agent_app("open")
        fake_tab(env, None, reply=lambda call: {"ok": False, "error": "forbidden_level", "message": "no"})
        result = env.call(env.token(env.login()), "search_photos", {"filters": {"path_prefix": PREFIX}})
        assert result["ok"] is True and result["shown_in_tab"] == {"applied": False, "reason": "forbidden"}

    def test_a_silent_tab_times_out_but_the_search_stands(self, agent_app, fake_tab, photos):
        env = agent_app("open", call_timeout_s=1)
        fake_tab(env, None, reply=lambda call: None)
        result = env.call(env.token(env.login()), "search_photos", {"filters": {"path_prefix": PREFIX}})
        assert result["ok"] is True
        assert result["shown_in_tab"]["reason"] == "tab_timeout" and "may still apply" in result["shown_in_tab"]["note"]

    def test_tab_id_routes_to_that_tab(self, agent_app, fake_tab, photos):
        env = agent_app("open")
        first = fake_tab(env, None, "tab-a", reply=reply_total())
        second = fake_tab(env, None, "tab-b", reply=reply_total())
        result = env.call(env.token(env.login()), "search_photos", {
            "filters": {"path_prefix": PREFIX}, "tab_id": "tab-a"})
        assert result["shown_in_tab"]["tab_id"] == "tab-a"
        assert len(first.calls) == 1 and second.calls == []

    def test_a_bad_tab_id_is_invalid_input(self, agent_app, photos):
        env = agent_app("open")
        result = env.call(env.token(env.login()), "search_photos", {"tab_id": "bad id!"})
        assert result["ok"] is False and result["error"] == "invalid_input"


class TestSemanticAndSimilarRelay:
    def test_semantic_search_shows_the_query(self, agent_app, fake_tab, photos, monkeypatch):
        from api.agent.internal_client import InternalClient, ok
        original = InternalClient.call

        async def call(self, grant, tool, **kwargs):
            if tool == "semantic_search":
                return ok({"photos": [{"path": ROWS[0]["path"], "filename": "0.jpg"}], "total": 1})
            return await original(self, grant, tool, **kwargs)

        monkeypatch.setattr(InternalClient, "call", call)
        env = agent_app("open")
        tab = fake_tab(env, None, reply=reply_total(1))
        result = env.call(env.token(env.login()), "semantic_search", {"query": "red sunset", "threshold": 0.2})
        assert result["ok"] is True and result["shown_in_tab"]["applied"] is True
        assert tab.calls[0]["args"] == {"patch": {
            "semantic_query": "red sunset", "semantic_threshold": 0.2, "similar_to": None,
            "similarity_mode": None, "min_similarity": None, **sort_pair()}, "replace": True}

    def test_text_scope_is_reported_not_shown(self, agent_app, fake_tab, photos):
        env = agent_app("open")
        tab = fake_tab(env, None, reply=reply_total())
        result = env.call(env.token(env.login()), "semantic_search", {"query": "sunset", "scope": "text"})
        assert result["ok"] is True
        assert result["shown_in_tab"] == {"applied": False, "reason": "unsupported_filters", "keys": ["scope"]}
        assert tab.calls == []

    def test_similar_photos_shows_with_the_floor_the_route_used(self, agent_app, fake_tab, photos, monkeypatch):
        from api.routers import gallery
        seen = []

        def find(conn, source, path, min_similarity, *rest):
            seen.append(min_similarity)
            return [{"path": ROWS[1]["path"], "filename": "1.jpg", "similarity": 0.9}], None

        monkeypatch.setattr(gallery, "_find_similar_visual", find)
        env = agent_app("open")
        tab = fake_tab(env, None, reply=reply_total(1))
        token = env.token(env.login())
        result = env.call(token, "similar_photos", {"path": ROWS[0]["path"]})
        assert result["ok"] is True and result["shown_in_tab"]["applied"] is True
        assert seen == [0.4]
        assert tab.calls[0]["args"] == {"patch": {
            "similar_to": ROWS[0]["path"], "similarity_mode": "visual", "min_similarity": 0.4,
            "semantic_query": None, "semantic_threshold": None, **sort_pair()}, "replace": True}
        env.call(token, "similar_photos", {"path": ROWS[0]["path"], "min_similarity": 0.8})
        assert seen == [0.4, 0.8] and tab.calls[1]["args"]["patch"]["min_similarity"] == 0.8

    def test_similar_photos_rows_carry_the_default_keys(self, agent_app, photos, seed_photos_prefix, monkeypatch):
        from api.routers import gallery
        seed_photos_prefix(AGENT_DIR + "simkeys/", [{
            "path": AGENT_DIR + "simkeys/h.jpg", "filename": "h.jpg", "camera_model": "X100", "iso": 200}])
        monkeypatch.setattr(gallery, "_find_similar_visual", lambda *a, **k: (
            [{"path": AGENT_DIR + "simkeys/h.jpg", "filename": "h.jpg", "similarity": 0.9}], None))
        env = agent_app("open")
        row = env.call(env.token(env.login()), "similar_photos", {
            "path": ROWS[0]["path"], "show": False})["data"]["rows"][0]
        assert row["camera_model"] == "X100" and row["iso"] == 200 and row["similarity"] == 0.9

    def test_a_later_similar_page_is_not_reapplied(self, agent_app, fake_tab, photos, monkeypatch):
        from api.routers import gallery
        monkeypatch.setattr(gallery, "_find_similar_visual", lambda *a, **k: (
            [{"path": ROWS[1]["path"], "filename": "1.jpg", "similarity": 0.9},
             {"path": ROWS[2]["path"], "filename": "2.jpg", "similarity": 0.8}], None))
        env = agent_app("open")
        tab = fake_tab(env, None, reply=reply_total())
        result = env.call(env.token(env.login()), "similar_photos", {
            "path": ROWS[0]["path"], "limit": 1, "offset": 1})
        assert result["shown_in_tab"]["reason"] == "page_not_first" and tab.calls == []


class TestSemanticTimeout:
    def test_the_semantic_show_waits_on_semantic_timeout_not_call_timeout(self, agent_app, fake_tab, photos, monkeypatch):
        import time

        from api.agent.internal_client import InternalClient, ok
        original = InternalClient.call

        async def call(self, grant, tool, **kwargs):
            if tool == "semantic_search":
                return ok({"photos": [{"path": ROWS[0]["path"], "filename": "0.jpg"}], "total": 1})
            return await original(self, grant, tool, **kwargs)

        monkeypatch.setattr(InternalClient, "call", call)
        env = agent_app("open", call_timeout_s=1, semantic_timeout_s=10)

        def slow(call):
            time.sleep(1.6)
            return {"ok": True, "data": {"applied": [], "total": 1}}

        fake_tab(env, None, reply=slow)
        result = env.call(env.token(env.login()), "semantic_search", {"query": "sunset"})
        assert result["ok"] is True and result["shown_in_tab"]["applied"] is True
