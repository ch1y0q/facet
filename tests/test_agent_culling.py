"""Darkroom agent tools (``list_culling_groups`` ... ``confirm_culling_groups``) over /mcp.

Seeds a burst, a similar-free library slice and a bracket set under ``AGENT_DIR`` with
a unique capture-date window so ``date_from``/``date_to`` scope every call to them.
"""

import sqlite3

import pytest

from api.agent import nonce, tools_culling
from tests.conftest import _TEST_DB_FILE, AGENT_DIR

PREFIX = AGENT_DIR + "cull/"
DATE_FROM, DATE_TO = "1999:01:01 00:00:00", "1999:01:01 23:59:59"
SCOPE = {"date_from": DATE_FROM, "date_to": DATE_TO}


def _burst(name, second, score, gid, lead):
    return {"path": PREFIX + name, "filename": name, "date_taken": f"1999:01:01 10:00:{second:02d}",
            "aggregate": score, "aesthetic": score, "tech_sharpness": score,
            "burst_group_id": gid, "is_burst_lead": lead}


def _bracket(name, second, offset):
    return {"path": PREFIX + name, "filename": name, "date_taken": f"1999:01:01 15:00:{second:02d}",
            "aggregate": 6.0, "aesthetic": 6.0, "tech_sharpness": 6.0, "sequence_kind": "bracket",
            "sequence_group_id": 77, "sequence_ev_offset": offset}


ROWS = [
    _burst("b1.jpg", 1, 9.0, 4242, 1), _burst("b2.jpg", 2, 5.0, 4242, 0),
    _burst("b3.jpg", 3, 2.0, 4242, 0),
    _bracket("k1.jpg", 1, -2), _bracket("k2.jpg", 2, 0), _bracket("k3.jpg", 3, 2),
]
BURST_PATHS = [PREFIX + n for n in ("b1.jpg", "b2.jpg", "b3.jpg")]
BRACKET_PATHS = [PREFIX + n for n in ("k1.jpg", "k2.jpg", "k3.jpg")]


@pytest.fixture()
def photos(seed_photos_prefix):
    return seed_photos_prefix(PREFIX, ROWS)


@pytest.fixture()
def env_token(agent_app, photos):
    nonce.reset()
    env = agent_app("legacy")
    return env, env.token(env.login(edition=True), "edition")


def _rejected():
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        return {r[0] for r in conn.execute(
            "SELECT path FROM photos WHERE path LIKE ? AND COALESCE(is_rejected,0)=1", (PREFIX + "%",))}


def _counts():
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        return (conn.execute("SELECT COUNT(*) FROM comparisons").fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM photos WHERE COALESCE(is_rejected,0)=1").fetchone()[0])


class TestGrant:
    def test_user_and_readonly_tokens_are_refused(self, agent_app, photos):
        env = agent_app("multi")
        headers = env.login("alice")
        for level in ("readonly", "user"):
            token = env.token(headers, level)
            for tool, args in (("list_culling_groups", {}), ("culling_profiles", {}),
                               ("auto_cull", {}), ("keeper_hints", {"paths": ["/x"]}),
                               ("confirm_culling_groups", {"groups": [
                                   {"type": "burst", "group_id": 1, "paths": ["/x"], "keep_paths": ["/x"]}]})):
                result = env.call(token, tool, args)
                assert result.get("error") == "forbidden_level", (level, tool, result)


class TestListGroups:
    def test_identity_pair_matches_the_router(self, env_token):
        env, token = env_token
        result = env.call(token, "list_culling_groups", {"group_by": "burst", **SCOPE})
        assert result["ok"], result
        direct = env.client.get("/api/culling-groups", params={"group_by": "burst", **SCOPE},
                                headers=env.login(edition=True)).json()
        assert [(g["type"], g["group_id"]) for g in result["data"]["rows"]] == \
            [(g["type"], g["group_id"]) for g in direct["groups"]]
        group = result["data"]["rows"][0]
        assert group["type"] == "burst" and group["photo_count"] == 3
        assert {p["path"] for p in group["photos"]} == set(BURST_PATHS)

    def test_default_group_by_all_lists_the_burst(self, env_token):
        env, token = env_token
        result = env.call(token, "list_culling_groups", SCOPE)
        assert result["ok"], result
        assert [g["type"] for g in result["data"]["rows"]] == ["burst"], result

    def test_bracket_set_carries_its_sequence_kind(self, env_token):
        env, token = env_token
        result = env.call(token, "list_culling_groups", {"group_by": "bracket", **SCOPE})
        group = result["data"]["rows"][0]
        assert (group["type"], group["sequence_kind"]) == ("bracket", "bracket")
        assert {p["path"] for p in group["photos"]} == set(BRACKET_PATHS)

    def test_a_page_over_the_byte_budget_sheds_members_not_groups(self):
        groups = [{"type": "scene", "group_id": g, "photos": [
            {"path": f"/p/{g}/{i}.jpg", "filename": "x" * 40, "date_taken": "1999:01:01 10:00:00"}
            for i in range(45)]} for g in range(20)]
        rows = tools_culling._fit_groups([tools_culling._compact_group(g) for g in groups], 20000)
        assert len(rows) == 20
        assert tools_culling.encoded_size({"rows": rows}) <= 20000
        assert all(row["photo_count"] == 45 for row in rows)
        assert all(row["photos_truncated"] is True for row in rows)
        assert any(len(row["photos"]) < tools_culling.GROUP_PHOTO_LIMIT for row in rows)

    def test_has_more_signals_further_pages(self, env_token):
        env, token = env_token
        result = env.call(token, "list_culling_groups", {"group_by": "burst", "per_page": 1, **SCOPE})
        assert result["data"]["has_more"] is False

    def test_has_more_is_true_on_a_page_with_more_behind_it(self, env_token, seed_photos_prefix):
        env, token = env_token
        window = {"date_from": "1998:01:01 00:00:00", "date_to": "1998:01:01 23:59:59"}
        rows = [{**_burst(f"p{gid}_{i}.jpg", i, 9.0 - i, gid, int(i == 0)),
                 "date_taken": f"1998:01:01 1{gid - 5000}:00:{i:02d}"} for gid in (5001, 5002) for i in range(3)]
        seed_photos_prefix(PREFIX + "pg/", [{**r, "path": PREFIX + "pg/" + r["filename"]} for r in rows])
        first = env.call(token, "list_culling_groups", {"group_by": "burst", "per_page": 1, **window})
        assert first["ok"] and len(first["data"]["rows"]) == 1 and first["data"]["has_more"] is True, first
        both = env.call(token, "list_culling_groups", {"group_by": "burst", "per_page": 2, **window})
        assert len(both["data"]["rows"]) == 2 and both["data"]["has_more"] is False

    def test_groups_seeded_after_a_first_call_are_visible_at_once(self, env_token, seed_photos_prefix):
        env, token = env_token
        window = {"date_from": "1997:01:01 00:00:00", "date_to": "1997:01:01 23:59:59"}
        assert env.call(token, "list_culling_groups", {"group_by": "burst", **window})["data"]["rows"] == []
        seed_photos_prefix(PREFIX + "late/", [
            {**_burst(f"l{i}.jpg", i, 9.0 - i, 6001, int(i == 0)), "path": PREFIX + f"late/l{i}.jpg",
             "date_taken": f"1997:01:01 10:00:{i:02d}"} for i in range(3)])
        rows = env.call(token, "list_culling_groups", {"group_by": "burst", **window})["data"]["rows"]
        assert [g["photo_count"] for g in rows] == [3]

    def test_rejecting_a_frame_through_the_gallery_route_refreshes_the_feed(self, env_token):
        env, token = env_token
        before = env.call(token, "list_culling_groups", {"group_by": "burst", **SCOPE})["data"]["rows"]
        assert [g["photo_count"] for g in before] == [3]
        resp = env.client.post("/api/photo/toggle_rejected", json={"photo_path": BURST_PATHS[2]},
                               headers=env.login(edition=True))
        assert resp.status_code == 200, resp.text
        after = env.call(token, "list_culling_groups", {"group_by": "burst", **SCOPE})["data"]["rows"]
        assert [g["photo_count"] for g in after] == [2]

    def test_bad_timestamp_is_invalid_input_before_any_call(self, env_token):
        env, token = env_token
        result = env.call(token, "list_culling_groups", {"date_from": "yesterday"})
        assert result["error"] == "invalid_input" and "YYYY-MM-DD" in result["message"]

    def test_iso_dates_are_accepted_and_scope_the_feed(self, env_token):
        env, token = env_token
        rows = env.call(token, "list_culling_groups", {
            "group_by": "burst", "date_from": "1999-01-01", "date_to": "1999-01-01"})["data"]["rows"]
        assert [g["photo_count"] for g in rows] == [3]
        none = env.call(token, "list_culling_groups", {
            "group_by": "burst", "date_from": "2001-01-01", "date_to": "2001-01-01"})
        assert none["ok"] and none["data"]["rows"] == []


class TestAutoCull:
    def args(self, **extra):
        return {"group_by": "all", **SCOPE, **extra}

    def test_auto_cull_accepts_iso_date(self, env_token):
        env, token = env_token
        result = env.call(token, "auto_cull", {"group_by": "burst", "date_from": "1999-01-01",
                                               "date_to": "1999-01-01"})
        assert result["ok"], result
        assert {g["group_id"] for g in result["data"]["rows"]} == {4242}

    def test_auto_cull_bad_date_is_invalid_input_naming_the_forms(self, env_token):
        env, token = env_token
        result = env.call(token, "auto_cull", {"date_from": "1999-13-45"})
        assert result["error"] == "invalid_input" and "YYYY-MM-DD" in result["message"]

    @pytest.mark.parametrize("group_by,kinds", [("burst", []), ("similar", ["similar"]),
                                                ("scene", ["scene"]), ("all", ["similar"])])
    def test_auto_cull_scope_dependent_kinds(self, env_token, group_by, kinds):
        env, token = env_token
        result = env.call(token, "auto_cull", {"group_by": group_by, **SCOPE})
        assert result["ok"], result
        assert result["data"]["scope_dependent_kinds"] == kinds
        assert ("whole range in one call" in result.get("note", "")) == bool(kinds)

    def _spy(self, monkeypatch, reply=None):
        from api.agent import show as relay
        calls = []

        async def fake(registry, resolved, settings, tab_id, paths, *, timeout, groups=None, marks=None, **extra):
            calls.append({"paths": paths, "groups": groups, "marks": marks, "tab_id": tab_id})
            return reply or {"applied": True, "tab_id": "t", "total": len(paths)}
        monkeypatch.setattr(relay, "show_paths_in_tab", fake)
        return calls

    def test_auto_cull_dry_run_pins_annotated_page(self, env_token, monkeypatch):
        env, token = env_token
        calls = self._spy(monkeypatch)
        result = env.call(token, "auto_cull", {"group_by": "burst", **SCOPE, "tab_id": "abcd"})
        assert result["ok"], result
        row = result["data"]["rows"][0]
        assert len(calls) == 1 and calls[0]["tab_id"] == "abcd"
        paths = row["keep_paths"] + row["reject_paths"]
        assert calls[0]["paths"] == paths
        assert calls[0]["groups"] == [row["number"]] * len(paths)
        assert calls[0]["marks"] == ["keep"] * len(row["keep_paths"]) + ["remove"] * len(row["reject_paths"])
        assert result["shown_in_tab"]["applied"] is True

    def test_auto_cull_show_failure_does_not_fail(self, env_token, monkeypatch):
        env, token = env_token
        self._spy(monkeypatch, reply={"applied": False, "reason": "no_tab"})
        result = env.call(token, "auto_cull", {"group_by": "burst", **SCOPE})
        assert result["ok"] and result["shown_in_tab"] == {"applied": False, "reason": "no_tab"}
        assert result["confirm"]

    def test_auto_cull_show_false_skips(self, env_token, monkeypatch):
        env, token = env_token
        calls = self._spy(monkeypatch)
        result = env.call(token, "auto_cull", {"group_by": "burst", **SCOPE, "show": False})
        assert result["ok"] and not calls and "shown_in_tab" not in result

    def test_auto_cull_apply_never_shows(self, env_token, monkeypatch):
        env, token = env_token
        first = env.call(token, "auto_cull", {"group_by": "burst", **SCOPE})
        calls = self._spy(monkeypatch)
        result = env.call(token, "auto_cull", {"group_by": "burst", **SCOPE, "dry_run": False,
                                               "confirm": first["confirm"]})
        assert result["ok"], result
        assert not calls and "shown_in_tab" not in result

    def test_auto_cull_description_says_one_call(self, env_token):
        env, token = env_token
        tools = env.rpc(token, "tools/list").json()["result"]["tools"]
        text = next(t["description"] for t in tools if t["name"] == "auto_cull")
        assert "ONE call" in text and "month" in text

    def test_preview_writes_nothing_and_issues_a_nonce(self, env_token):
        env, token = env_token
        before = _counts()
        result = env.call(token, "auto_cull", self.args())
        assert result["ok"] and result["data"]["dry_run"] is True and result["confirm"]
        assert _counts() == before and _rejected() == set()

    def test_apply_without_or_with_a_wrong_nonce_is_refused(self, env_token):
        env, token = env_token
        for confirm in (None, "bogus"):
            result = env.call(token, "auto_cull", self.args(dry_run=False, confirm=confirm))
            assert result["error"] == "confirmation_required"
        assert _rejected() == set()

    def test_apply_with_the_preview_nonce_rejects_and_keeps_the_bracket_whole(self, env_token):
        env, token = env_token
        preview = env.call(token, "auto_cull", self.args(strictness=0))
        planned = {p for g in preview["data"]["rows"] for p in g["reject_paths"]}
        assert planned and planned <= set(BURST_PATHS)
        assert not {p for g in preview["data"]["rows"] for p in g["keep_paths"] + g["reject_paths"]} \
            & set(BRACKET_PATHS)
        result = env.call(token, "auto_cull", self.args(strictness=0, dry_run=False,
                                                       confirm=preview["confirm"]))
        assert result["ok"], result
        assert _rejected() == planned
        assert not _rejected() & set(BRACKET_PATHS)

    def test_a_nonce_is_single_use(self, env_token):
        env, token = env_token
        preview = env.call(token, "auto_cull", self.args(strictness=0))
        args = self.args(strictness=0, dry_run=False, confirm=preview["confirm"])
        assert env.call(token, "auto_cull", args)["ok"]
        assert env.call(token, "auto_cull", args)["error"] == "confirmation_required"

    def test_a_plan_changed_since_the_preview_is_refused(self, env_token):
        env, token = env_token
        preview = env.call(token, "auto_cull", self.args(strictness=0))
        with sqlite3.connect(_TEST_DB_FILE.name) as conn:
            conn.execute("UPDATE photos SET aggregate = 9.5, aesthetic = 9.5, tech_sharpness = 9.5 "
                         "WHERE path = ?", (PREFIX + "b3.jpg",))
        result = env.call(token, "auto_cull", self.args(strictness=0, dry_run=False,
                                                       confirm=preview["confirm"]))
        assert result["error"] == "confirmation_required"
        assert _rejected() == set()

    def test_a_nonce_does_not_cross_options(self, env_token):
        env, token = env_token
        preview = env.call(token, "auto_cull", self.args(strictness=0))
        result = env.call(token, "auto_cull", self.args(strictness=100, dry_run=False,
                                                       confirm=preview["confirm"]))
        assert result["error"] == "confirmation_required"


BIG_PREFIX = PREFIX + "big/" + "d" * 70 + "/"
BIG_WINDOW = {"date_from": "1996-01-01", "date_to": "1996-01-01"}
BIG_GROUPS = 120


def _big_rows():
    return [{"path": f"{BIG_PREFIX}{'f' * 24}_{g:03d}_{i}.jpg", "filename": f"{g}_{i}.jpg",
             "date_taken": f"1996:01:01 {g // 60:02d}:{g % 60:02d}:{i:02d}",
             "aggregate": 9.0 - 3 * i, "aesthetic": 9.0 - 3 * i, "tech_sharpness": 9.0 - 3 * i,
             "burst_group_id": 7000 + g, "is_burst_lead": int(i == 0)}
            for g in range(BIG_GROUPS) for i in range(3)]


@pytest.fixture()
def big(env_token, seed_photos_prefix):
    seed_photos_prefix(BIG_PREFIX, _big_rows())
    return env_token


def _big_pages(env, token, **extra):
    pages, cursor, digest = [], 0, None
    while True:
        paging = {"cursor": cursor, "plan_digest": digest} if cursor else {}
        result = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 100,
                                               **BIG_WINDOW, **paging, **extra})
        assert result["ok"], result
        pages.append(result)
        digest = result["data"]["plan_digest"]
        cursor = result["data"]["next_cursor"]
        if cursor is None:
            return pages
        assert len(pages) < 20


class TestAutoCullPaging:
    def test_a_page_fits_the_envelope_with_long_paths(self, big):
        env, token = big
        first = _big_pages(env, token)[0]
        photos = sum(len(r["keep_paths"]) + len(r["reject_paths"]) for r in first["data"]["rows"])
        assert 100 < photos <= 200 and len(first["data"]["rows"]) <= 100
        assert max(len(p) for r in first["data"]["rows"] for p in r["keep_paths"]) >= 120
        assert "truncated" not in first and "next_offset" not in first
        assert len(first["data"]["rows"]) == first["data"]["next_cursor"]
        assert tools_culling.encoded_size(first) <= 60000

    def test_auto_cull_large_plan_confirmable(self, big):
        env, token = big
        pages = _big_pages(env, token)
        assert len(pages) >= 2 and pages[0]["confirm"] and all("confirm" not in p for p in pages[1:])
        planned = {p for page in pages for g in page["data"]["rows"] for p in g["reject_paths"]}
        assert len(planned) == BIG_GROUPS * 2
        result = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 100, "dry_run": False,
                                               "confirm": pages[0]["confirm"], **BIG_WINDOW})
        assert result["ok"], result
        assert {p for p in _rejected() if p.startswith(BIG_PREFIX)} == planned

    def test_the_apply_is_refused_when_the_plan_moved_after_the_nonce_check(self, big):
        env, token = big
        pages = _big_pages(env, token)
        with sqlite3.connect(_TEST_DB_FILE.name) as conn:
            conn.execute("UPDATE photos SET aggregate = 9.9, aesthetic = 9.9, tech_sharpness = 9.9 "
                         "WHERE path LIKE ? AND path LIKE '%\\_001\\_2.jpg' ESCAPE '\\'", (BIG_PREFIX + "%",))
        result = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 100, "dry_run": False,
                                               "confirm": pages[0]["confirm"], **BIG_WINDOW})
        assert result["error"] == "confirmation_required"
        assert not {p for p in _rejected() if p.startswith(BIG_PREFIX)}


@pytest.fixture()
def big_env(agent_app, seed_photos_prefix):
    def make(**mcp):
        nonce.reset()
        seed_photos_prefix(BIG_PREFIX, _big_rows())
        env = agent_app("legacy", **mcp)
        return env, env.token(env.login(edition=True), "edition")
    return make


def _big_rejected():
    return {p for p in _rejected() if p.startswith(BIG_PREFIX)}


def _assert_every_group_once(pages):
    numbers = [row["number"] for page in pages for row in page["data"]["rows"]]
    assert numbers == list(range(1, BIG_GROUPS + 1))
    assert not any("truncated" in page or "returned" in page for page in pages)


class TestAutoCullPageBudget:
    def test_stale_overrides_do_not_make_the_envelope_drop_groups(self, big_env):
        env, token = big_env()
        stale = [f"/agent-seeded/old-session/{'x' * 90}/{i:04d}.jpg" for i in range(300)]
        pages = _big_pages(env, token, remove_paths=stale)
        _assert_every_group_once(pages)
        data = pages[0]["data"]
        assert len(data["ignored_overrides"]) == 20 and data["ignored_overrides_count"] == 300
        result = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 100, "dry_run": False,
                                               "remove_paths": stale, "confirm": pages[0]["confirm"],
                                               **BIG_WINDOW})
        assert result["ok"], result
        assert _big_rejected() == {p for page in pages for r in page["data"]["rows"]
                                   for p in r["reject_paths"]}

    def test_a_small_operator_max_bytes_pages_by_whole_groups(self, big_env):
        env, token = big_env(max_bytes=30000)
        pages = _big_pages(env, token)
        _assert_every_group_once(pages)
        assert len(pages) > 2 and all(tools_culling.encoded_size(p) <= 30000 for p in pages)

    def test_the_apply_returns_counts_only(self, big_env):
        env, token = big_env(max_bytes=30000)
        first = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 100, "show": False,
                                              **BIG_WINDOW})
        result = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 100, "dry_run": False,
                                               "confirm": first["confirm"], **BIG_WINDOW})
        assert result["ok"], result
        assert set(result["data"]) <= {"groups_processed", "kept", "rejected", "highlights_added", "dry_run"}
        assert result["data"]["rejected"] == BIG_GROUPS * 2 and len(_big_rejected()) == BIG_GROUPS * 2

    def test_a_later_page_needs_the_plan_digest(self, big_env):
        env, token = big_env()
        first = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 100, "show": False,
                                              **BIG_WINDOW})
        result = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 100, "show": False,
                                               "cursor": first["data"]["next_cursor"], **BIG_WINDOW})
        assert result["error"] == "invalid_input" and "plan_digest" in result["message"]

    def test_a_plan_that_moves_between_pages_refuses_the_next_page(self, big_env):
        env, token = big_env()
        args = {"group_by": "burst", "strictness": 100, "show": False, **BIG_WINDOW}
        first = env.call(token, "auto_cull", args)
        with sqlite3.connect(_TEST_DB_FILE.name) as conn:
            conn.execute("UPDATE photos SET burst_reviewed = 1 WHERE burst_group_id = 7000 AND path LIKE ?",
                         (BIG_PREFIX + "%",))
        second = env.call(token, "auto_cull", {**args, "cursor": first["data"]["next_cursor"],
                                               "plan_digest": first["data"]["plan_digest"]})
        assert second["error"] == "confirmation_required" and "cursor 0" in second["message"]

    def test_only_the_first_page_issues_a_confirm_so_many_pages_keep_it_valid(self, big_env):
        env, token = big_env()
        first = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 100, "show": False,
                                              **BIG_WINDOW})
        for _ in range(nonce.MAX_PENDING_PER_OWNER + 4):
            later = env.call(token, "auto_cull", {
                "group_by": "burst", "strictness": 100, "show": False, **BIG_WINDOW,
                "cursor": first["data"]["next_cursor"], "plan_digest": first["data"]["plan_digest"]})
            assert later["ok"] and "confirm" not in later
        result = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 100, "dry_run": False,
                                               "confirm": first["confirm"], **BIG_WINDOW})
        assert result["ok"], result

    def test_the_plan_moving_after_the_nonce_check_is_refused_by_expected_digest(self, big_env, monkeypatch):
        from api.agent.internal_client import InternalClient
        env, token = big_env()
        first = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 100, "show": False,
                                              **BIG_WINDOW})
        real = InternalClient.call

        async def call(self, grant, name, *a, **kw):
            body = kw.get("json")
            if name == "culling.auto" and isinstance(body, dict) and body.get("dry_run") is False:
                with sqlite3.connect(_TEST_DB_FILE.name) as conn:
                    conn.execute("UPDATE photos SET aggregate = 9.9, aesthetic = 9.9, tech_sharpness = 9.9 "
                                 "WHERE path LIKE ? AND path LIKE '%\\_001\\_2.jpg' ESCAPE '\\'",
                                 (BIG_PREFIX + "%",))
            return await real(self, grant, name, *a, **kw)
        monkeypatch.setattr(InternalClient, "call", call)
        result = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 100, "dry_run": False,
                                               "confirm": first["confirm"], **BIG_WINDOW})
        assert result["error"] == "confirmation_required"
        assert not _big_rejected()

    def test_a_restated_removal_of_a_trimmed_bracket_rung_is_not_refused(self):
        from api.routers import burst_culling as bc
        photos = [{"path": "/b/k0.jpg", "sequence_ev_offset": 0},
                  {"path": "/b/k-2.jpg", "sequence_ev_offset": -2},
                  {"path": "/b/k+2.jpg", "sequence_ev_offset": 2}]
        plan = bc._plan_auto_cull_groups(
            [{"type": "bracket", "group_id": 9, "sequence_kind": "bracket", "photos": photos}], set(), 50, 1)
        assert "/b/k-2.jpg" in plan[0]["reject_paths"]
        effective, ignored = bc._apply_plan_overrides(plan, [], ["/b/k-2.jpg"])
        assert ignored == [] and effective == {"keep": [], "remove": []}
        with pytest.raises(bc.AutoCullOverrideError):
            bc._apply_plan_overrides(plan, [], ["/b/k0.jpg"])

    def test_trim_brackets_makes_bracket_scope_dependent(self, env_token):
        env, token = env_token
        result = env.call(token, "auto_cull", {"group_by": "burst", "trim_brackets": True, **SCOPE})
        assert result["ok"], result
        assert result["data"]["scope_dependent_kinds"] == ["bracket"]


class TestAutoCullOverrides:
    def args(self, **extra):
        return {"group_by": "burst", "strictness": 0, **SCOPE, **extra}

    def test_description_documents_the_protocol(self, env_token):
        env, token = env_token
        tools = env.rpc(token, "tools/list").json()["result"]["tools"]
        text = next(t["description"] for t in tools if t["name"] == "auto_cull")
        for needle in ("keep_paths", "remove_paths", "ui_get_context", "SAME", "next_cursor", "300"):
            assert needle in text, needle

    def test_overrides_are_applied_under_the_same_confirm(self, env_token):
        env, token = env_token
        overrides = {"keep_paths": [BURST_PATHS[2]], "remove_paths": [BURST_PATHS[1]]}
        preview = env.call(token, "auto_cull", self.args(**overrides))
        assert preview["ok"], preview
        row = preview["data"]["rows"][0]
        assert row["reject_paths"] == [BURST_PATHS[1]] and BURST_PATHS[2] in row["keep_paths"]
        result = env.call(token, "auto_cull", self.args(dry_run=False, confirm=preview["confirm"], **overrides))
        assert result["ok"], result
        assert _rejected() == {BURST_PATHS[1]}

    def test_a_confirm_does_not_cover_different_overrides(self, env_token):
        env, token = env_token
        preview = env.call(token, "auto_cull", self.args(remove_paths=[BURST_PATHS[1]]))
        result = env.call(token, "auto_cull", self.args(dry_run=False, confirm=preview["confirm"]))
        assert result["error"] == "confirmation_required"
        assert _rejected() == set()

    def test_stale_paths_are_reported_not_applied(self, env_token):
        env, token = env_token
        result = env.call(token, "auto_cull", self.args(remove_paths=["/not/in/plan.jpg"]))
        assert result["ok"] and result["data"]["ignored_overrides"] == ["/not/in/plan.jpg"]

    def test_refusals_name_the_paths_and_groups(self, env_token):
        env, token = env_token
        both = env.call(token, "auto_cull", self.args(keep_paths=[BURST_PATHS[0]], remove_paths=[BURST_PATHS[0]]))
        assert both["error"] == "invalid_input" and BURST_PATHS[0] in both["message"]
        zero = env.call(token, "auto_cull", self.args(remove_paths=BURST_PATHS[:2]))
        assert zero["error"] == "invalid_input" and "4242" in zero["message"]

    def test_too_many_override_paths_are_invalid(self, env_token):
        env, token = env_token
        result = env.call(token, "auto_cull", self.args(remove_paths=[f"/p{i}" for i in range(1001)]))
        assert result["error"] == "invalid_input"


class TestConfirm:
    def group(self, type_, paths, keep):
        return {"type": type_, "group_id": 4242 if type_ == "burst" else 77, "paths": paths,
                "keep_paths": keep}

    def test_confirm_rejects_the_unkept_frames(self, env_token):
        env, token = env_token
        result = env.call(token, "confirm_culling_groups", {
            "groups": [self.group("burst", BURST_PATHS, BURST_PATHS[:1])]})
        assert result["ok"], result
        row = result["data"]["rows"][0]
        assert (row["type"], row["group_id"], row["ok"]) == ("burst", 4242, True)
        assert _rejected() == set(BURST_PATHS[1:])

    def test_empty_keep_needs_the_nonce_flow(self, env_token):
        env, token = env_token
        groups = [self.group("burst", BURST_PATHS, [])]
        first = env.call(token, "confirm_culling_groups", {"groups": groups})
        assert first["error"] == "confirmation_required" and first["confirm"]
        assert _rejected() == set()
        other = [self.group("burst", BURST_PATHS[:2], [])]
        assert env.call(token, "confirm_culling_groups", {
            "groups": other, "confirm": first["confirm"]})["error"] == "confirmation_required"
        again = env.call(token, "confirm_culling_groups", {"groups": groups})
        done = env.call(token, "confirm_culling_groups", {"groups": groups, "confirm": again["confirm"]})
        assert done["ok"] and _rejected() == set(BURST_PATHS)

    def test_partial_selection_of_a_bracket_is_refused(self, env_token):
        env, token = env_token
        result = env.call(token, "confirm_culling_groups", {
            "groups": [self.group("bracket", BRACKET_PATHS, BRACKET_PATHS[:1])]})
        assert result["error"] == "invalid_input"
        assert _rejected() == set()

    def test_keeping_a_whole_bracket_is_accepted(self, env_token):
        env, token = env_token
        result = env.call(token, "confirm_culling_groups", {
            "groups": [self.group("bracket", BRACKET_PATHS, BRACKET_PATHS)]})
        assert result["ok"] and _rejected() == set()

    def test_keep_outside_paths_is_invalid(self, env_token):
        env, token = env_token
        result = env.call(token, "confirm_culling_groups", {
            "groups": [self.group("burst", BURST_PATHS[:2], BURST_PATHS)]})
        assert result["error"] == "invalid_input"


class TestProfiles:
    def test_profiles_suggest_and_hints(self, env_token):
        env, token = env_token
        assert env.call(token, "culling_profiles")["data"]["profiles"]
        suggest = env.call(token, "suggest_culling_profile", SCOPE)
        assert suggest["ok"] and "confidence" in suggest["data"]
        assert env.call(token, "suggest_culling_profile", {"date_to": "x"})["error"] == "invalid_input"
        hints = env.call(token, "keeper_hints", {"paths": BURST_PATHS})
        assert hints["ok"] and isinstance(hints["data"]["rows"], list)


def test_pinned_page_past_the_cap_pins_keepers_first():
    rows = [{"number": n, "keep_paths": [f"/k{n}"], "reject_paths": [f"/r{n}a", f"/r{n}b"],
             "group_reason": {"key": "photo_count", "params": {"n": 3}}, "kind": "burst",
             "reasons": {f"/r{n}a": {"key": "soft", "value": None}, f"/r{n}b": {"key": "lower_overall", "value": 1.5}}}
            for n in range(1, 101)]
    page = tools_culling._pinned_page(rows)
    assert len(page.paths) == tools_culling.SHOW_PIN_MAX and page.unpinned == 100
    assert page.marks[:100] == ["keep"] * 100 and page.marks[100:] == ["remove"] * 100
    assert page.paths[0] == "/k1" and page.groups[0] == 1 and page.paths[100] == "/r1a" and page.groups[100] == 1
    assert len(page.labels) == len(page.reasons) == len(page.kinds) == len(page.paths)
    assert page.reasons[0] == {"key": "best"} and page.reasons[100] == {"key": "soft", "value": None}
    assert page.reasons[101] == {"key": "lower_overall", "value": 1.5}
    assert page.labels[100] == {"key": "photo_count", "params": {"n": 3}} and page.kinds[100] == "burst"


class TestAutoCullRowsCarryReasons:
    def test_rows_have_a_group_reason_key_reject_only_reasons_and_a_kind(self, env_token):
        env, token = env_token
        result = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 0, "show": False, **SCOPE})
        assert result["ok"], result
        row = result["data"]["rows"][0]
        assert row["group_reason"]["key"] in ("burst", "burst_seconds") and isinstance(row["group_reason"]["params"], dict)
        assert set(row["reasons"]) == set(row["reject_paths"]) and row["reject_paths"]
        assert all(set(r) == {"key", "value"} and r["key"] != "best" for r in row["reasons"].values())
        assert row["kind"] == "burst"

    def test_the_pin_carries_aligned_labels_reasons_and_kinds(self, env_token, monkeypatch):
        from api.agent import show as relay
        env, token = env_token
        sent = []

        async def fake(registry, resolved, settings, tab_id, paths, *, timeout, **extra):
            sent.append({"paths": paths, **extra})
            return {"applied": True, "tab_id": "t", "total": len(paths)}
        monkeypatch.setattr(relay, "show_paths_in_tab", fake)
        result = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 0, **SCOPE})
        assert result["ok"], result
        call = sent[0]
        assert len(call["labels"]) == len(call["reasons"]) == len(call["kinds"]) == len(call["paths"])
        assert call["kinds"] == ["burst"] * len(call["paths"])
        assert call["reasons"][0] == {"key": "best"}


def test_group_reason_keys_for_every_plan_builder_string():
    from api.routers.burst_culling import _group_reason
    cases = [
        ({"type": "burst", "reason": "burst"}, "burst", {}),
        ({"type": "burst", "reason": "1.5s burst"}, "burst_seconds", {"seconds": 1.5}),
        ({"type": "burst", "reason": "2.5m burst"}, "burst_minutes", {"minutes": 2.5}),
        ({"type": "similar", "reason": "85% similar"}, "similar_percent", {"percent": 85}),
        ({"type": "scene", "reason": "12 photos"}, "photo_count", {"n": 12}),
        ({"type": "scene", "reason": "golden hour"}, "moment", {"moment": "golden hour"}),
        ({"type": "bracket", "reason": "4 frames, 1.3 EV span"}, "bracket_span", {"frames": 4, "ev_span": 1.3}),
        ({"type": "panorama", "reason": "9 frames"}, "frame_count", {"frames": 9}),
    ]
    for group, key, params in cases:
        assert _group_reason(group) == {"key": key, "params": params}, group
    assert _group_reason({"type": "burst"}) is None
    assert len(_group_reason({"type": "scene", "reason": "x" * 200})["params"]["moment"]) == 80


class TestAutoCullOversizedGroup:
    def test_a_single_group_over_the_budget_is_clipped_not_dropped(self, agent_app, seed_photos_prefix):
        nonce.reset()
        prefix = PREFIX + "huge/"
        rows = [{"path": f"{prefix}{'h' * 120}_{i:04d}.jpg", "filename": f"h{i}.jpg",
                 "date_taken": f"1997:02:02 00:{i // 60:02d}:{i % 60:02d}",
                 "aggregate": 5.0, "aesthetic": 5.0, "tech_sharpness": 5.0,
                 "burst_group_id": 9000, "is_burst_lead": int(i == 0)} for i in range(800)]
        rows += [{"path": f"{prefix}small_{i}.jpg", "filename": f"s{i}.jpg",
                  "date_taken": f"1997:02:02 05:00:{i:02d}", "aggregate": 9.0 - 3 * i,
                  "aesthetic": 9.0 - 3 * i, "tech_sharpness": 9.0 - 3 * i,
                  "burst_group_id": 9001, "is_burst_lead": int(i == 0)} for i in range(3)]
        seed_photos_prefix(prefix, rows)
        env = agent_app("legacy")
        token = env.token(env.login(edition=True), "edition")
        result = env.call(token, "auto_cull", {"group_by": "burst", "strictness": 100, "show": False,
                                               "date_from": "1997-02-02", "date_to": "1997-02-02"})
        assert result["ok"], result
        got = result["data"]["rows"]
        assert len(got) == 1 and got[0]["paths_clipped"] is True
        assert got[0]["keep_count"] + got[0]["reject_count"] == 800
        assert len(got[0]["keep_paths"]) + len(got[0]["reject_paths"]) < 800
        assert result["data"]["next_cursor"] == got[0]["number"]
        assert "truncated" not in result


def _jwt_of(headers):
    return headers["Authorization"].split(" ", 1)[1]


def _rate(path, **columns):
    sets = ", ".join(f"{k} = ?" for k in columns)
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.execute(f"UPDATE photos SET {sets} WHERE path = ?", [*columns.values(), path])


class TestAutoCullTabMarks:
    """C1: ``auto_cull`` reads the user's Keep/Remove flips from the tab when it is given neither list."""

    @pytest.fixture()
    def rig(self, agent_app, photos, fake_tab, monkeypatch):
        from tests.conftest import intercept_internal_call
        nonce.reset()
        tools_culling.reset_preview_memory()
        state = {"review": {"keep": [], "remove": []}, "upstream": []}
        env = agent_app("legacy")
        headers = env.login(edition=True)

        def reply(call):
            if call["tool"] == "ui_get_context":
                return {"ok": True, "data": {"review": state["review"]}}
            return {"ok": True, "data": {"echo": call["tool"]}}
        tab = fake_tab(env, _jwt_of(headers), reply=reply)
        intercept_internal_call(monkeypatch, lambda tool, kw: state["upstream"].append((tool, kw)) and None)
        token = env.token(headers, "edition")
        return type("Rig", (), {"env": env, "token": token, "tab": tab, "state": state, "headers": headers})

    @staticmethod
    def args(**extra):
        return {"group_by": "burst", "strictness": 0, "show": False, **SCOPE, **extra}

    def auto_calls(self, rig):
        return [kw["json"] for tool, kw in rig.state["upstream"] if tool == "culling.auto"]

    def context_calls(self, rig):
        return [c for c in rig.tab.calls if c["tool"] == "ui_get_context"]

    def test_neither_list_reads_the_tab_marks(self, rig):
        rig.state["review"] = {"keep": [BURST_PATHS[0], BURST_PATHS[2]], "remove": [BURST_PATHS[1]]}
        result = rig.env.call(rig.token, "auto_cull", self.args())
        assert result["ok"], result
        sent = self.auto_calls(rig)[0]
        assert sent["keep_paths"] == [BURST_PATHS[0], BURST_PATHS[2]] and sent["remove_paths"] == [BURST_PATHS[1]]
        assert result["overrides_from_tab"] == {"keep": 1, "remove": 1}
        assert len(self.context_calls(rig)) == 1 and "activity_since" not in self.context_calls(rig)[0]["args"]

    def test_an_explicit_list_wins_with_no_merge_of_the_tab_s_marks(self, rig):
        rig.state["review"] = {"keep": [BURST_PATHS[0]], "remove": [BURST_PATHS[1]]}
        result = rig.env.call(rig.token, "auto_cull", self.args(keep_paths=[BURST_PATHS[2]]))
        assert result["ok"], result
        sent = self.auto_calls(rig)[0]
        assert sent["keep_paths"] == [BURST_PATHS[2]] and sent["remove_paths"] == []
        assert "overrides_from_tab" not in result

    def test_no_tab_keeps_today_s_behaviour(self, agent_app, photos, monkeypatch):
        from tests.conftest import intercept_internal_call
        nonce.reset()
        seen = []
        intercept_internal_call(monkeypatch, lambda tool, kw: seen.append((tool, kw)) and None)
        env = agent_app("legacy")
        result = env.call(env.token(env.login(edition=True), "edition"), "auto_cull", self.args())
        assert result["ok"], result
        sent = next(kw["json"] for tool, kw in seen if tool == "culling.auto")
        assert sent["keep_paths"] == [] and sent["remove_paths"] == [] and "overrides_from_tab" not in result

    def test_bridge_off_keeps_today_s_behaviour(self, agent_app, photos, monkeypatch):
        from tests.conftest import intercept_internal_call
        nonce.reset()
        seen = []
        intercept_internal_call(monkeypatch, lambda tool, kw: seen.append((tool, kw)) and None)
        env = agent_app("legacy", bridge=False)
        result = env.call(env.token(env.login(edition=True), "edition"), "auto_cull", self.args())
        assert result["ok"], result
        assert "overrides_from_tab" not in result
        assert next(kw["json"] for tool, kw in seen if tool == "culling.auto")["keep_paths"] == []

    def test_a_list_at_the_tab_cap_is_not_trusted(self, rig):
        rig.state["review"] = {"keep": [f"/k/{i}.jpg" for i in range(1000)], "remove": [BURST_PATHS[1]]}
        result = rig.env.call(rig.token, "auto_cull", self.args())
        assert result["ok"], result
        sent = self.auto_calls(rig)[0]
        assert sent["keep_paths"] == [] and sent["remove_paths"] == []
        assert result["overrides_from_tab"] == {"skipped": "truncated"}

    def test_ignored_overrides_surface(self, rig):
        rig.state["review"] = {"keep": [], "remove": ["/not/in/plan.jpg"]}
        result = rig.env.call(rig.token, "auto_cull", self.args())
        assert result["ok"] and result["data"]["ignored_overrides"] == ["/not/in/plan.jpg"]
        assert result["overrides_from_tab"]["remove"] == 0

    def test_marks_that_restate_the_plan_are_not_counted(self, rig):
        rig.state["review"] = {"keep": [BURST_PATHS[0], BURST_PATHS[1]], "remove": [BURST_PATHS[2]]}
        result = rig.env.call(rig.token, "auto_cull", self.args())
        assert result["ok"], result
        assert result["overrides_from_tab"] == {"keep": 0, "remove": 0}

    def test_a_dropped_mark_is_not_counted_as_effective(self, rig):
        rig.state["review"] = {"keep": [], "remove": list(BURST_PATHS)}
        result = rig.env.call(rig.token, "auto_cull", self.args())
        assert result["ok"], result
        assert result["overrides_from_tab"]["remove"] == 0 and result["overrides_from_tab"]["dropped"]

    def test_effective_overrides_never_reaches_the_tool_result(self, rig):
        rig.state["review"] = {"keep": [BURST_PATHS[2]], "remove": [BURST_PATHS[1]]}
        with_marks = rig.env.call(rig.token, "auto_cull", self.args())
        explicit = rig.env.call(rig.token, "auto_cull", self.args(keep_paths=[BURST_PATHS[2]]))
        rig.state["review"] = {"keep": [], "remove": []}
        without = rig.env.call(rig.token, "auto_cull", self.args())
        for result in (with_marks, explicit, without):
            assert result["ok"], result
            assert "effective_overrides" not in result["data"]

    def test_a_remove_all_group_mark_is_dropped_and_reported_not_refused(self, rig):
        rig.state["review"] = {"keep": [], "remove": list(BURST_PATHS)}
        result = rig.env.call(rig.token, "auto_cull", self.args())
        assert result["ok"], result
        dropped = result["overrides_from_tab"]["dropped"]
        assert {d["path"] for d in dropped} == set(BURST_PATHS[:2])
        assert {d["reason"] for d in dropped} == {"would_leave_no_keeper"}
        assert self.auto_calls(rig)[0]["lenient_overrides"] is True

    def test_later_pages_reuse_the_marks_and_never_re_read_the_tab(self, rig):
        rig.state["review"] = {"keep": [BURST_PATHS[2]], "remove": []}
        first = rig.env.call(rig.token, "auto_cull", self.args())
        digest = first["data"]["plan_digest"]
        rig.state["review"] = {"keep": [], "remove": [BURST_PATHS[1]]}
        second = rig.env.call(rig.token, "auto_cull", self.args(cursor=1, plan_digest=digest))
        assert second["ok"], second
        assert self.auto_calls(rig)[1]["keep_paths"] == [BURST_PATHS[2]]
        assert self.auto_calls(rig)[1]["remove_paths"] == []
        assert len(self.context_calls(rig)) == 1
        assert second["overrides_from_tab"] == {"keep": 1, "remove": 0}

    def test_the_description_tells_the_agent_to_omit_the_lists(self, rig):
        tools = rig.env.rpc(rig.token, "tools/list").json()["result"]["tools"]
        text = next(t["description"] for t in tools if t["name"] == "auto_cull")
        assert "omit" in text.lower() and "pass them as keep_paths / remove_paths" not in text


class TestAutoCullStateGuardThroughTheTool:
    """C2: the tool binds the apply to the ORIGINAL preview and the route skips what the user touched."""

    @pytest.fixture()
    def rig(self, agent_app, photos, fake_tab, monkeypatch):
        from tests.conftest import intercept_internal_call
        nonce.reset()
        tools_culling.reset_preview_memory()
        state = {"review": {"keep": [], "remove": []}, "upstream": []}
        env = agent_app("legacy")
        headers = env.login(edition=True)

        def reply(call):
            if call["tool"] == "ui_get_context":
                return {"ok": True, "data": {"review": state["review"]}}
            return {"ok": True, "data": {"echo": call["tool"]}}
        tab = fake_tab(env, _jwt_of(headers), reply=reply)
        intercept_internal_call(monkeypatch, lambda tool, kw: state["upstream"].append((tool, kw)) and None)
        token = env.token(headers, "edition")
        yield type("Rig", (), {"env": env, "token": token, "tab": tab, "state": state})
        for path in BURST_PATHS:
            _rate(path, star_rating=0, is_favorite=0, is_rejected=0)

    @staticmethod
    def args(**extra):
        return {"group_by": "burst", "strictness": 0, "show": False, **SCOPE, **extra}

    def apply(self, rig, preview, **extra):
        return rig.env.call(rig.token, "auto_cull", self.args(dry_run=False, confirm=preview["confirm"], **extra))

    def test_a_rating_after_the_preview_is_skipped_and_listed(self, rig):
        preview = rig.env.call(rig.token, "auto_cull", self.args())
        assert {p for r in preview["data"]["rows"] for p in r["reject_paths"]} == {BURST_PATHS[2]}
        _rate(BURST_PATHS[2], star_rating=5)
        result = self.apply(rig, preview)
        assert result["ok"], result
        assert _rejected() == set()
        assert result["data"]["skipped_user_changed"] == [BURST_PATHS[2]]
        assert result["data"]["skipped_user_changed_count"] == 1

    def test_a_manual_reject_after_the_preview_is_listed(self, rig):
        preview = rig.env.call(rig.token, "auto_cull", self.args())
        _rate(BURST_PATHS[2], is_rejected=1)
        result = self.apply(rig, preview)
        assert result["ok"], result
        assert _rejected() == {BURST_PATHS[2]}
        assert result["data"]["skipped_user_changed"] == [BURST_PATHS[2]]

    def test_the_apply_does_not_re_run_a_dry_run_that_would_overwrite_the_snapshot(self, rig):
        preview = rig.env.call(rig.token, "auto_cull", self.args())
        _rate(BURST_PATHS[2], star_rating=5)
        self.apply(rig, preview)
        sent = self.auto_calls(rig)
        assert [c["dry_run"] for c in sent] == [True, False]
        assert sent[1]["expected_digest"] == preview["data"]["plan_digest"]

    def auto_calls(self, rig):
        return [kw["json"] for tool, kw in rig.state["upstream"] if tool == "culling.auto"]

    def test_a_flip_since_the_preview_becomes_skip_paths_under_the_preview_marks(self, rig):
        rig.state["review"] = {"keep": [], "remove": [BURST_PATHS[1]]}
        preview = rig.env.call(rig.token, "auto_cull", self.args())
        assert preview["ok"], preview
        rig.state["review"] = {"keep": [], "remove": []}
        result = self.apply(rig, preview)
        assert result["ok"], result
        sent = self.auto_calls(rig)[-1]
        assert sent["remove_paths"] == [BURST_PATHS[1]] and sent["skip_paths"] == [BURST_PATHS[1]]
        assert sent["expected_digest"] == preview["data"]["plan_digest"]
        assert result["data"]["skipped_user_changed"] == [BURST_PATHS[1]]
        assert _rejected() == {BURST_PATHS[2]}

    def test_without_memory_of_the_confirm_the_apply_keeps_todays_path(self, rig):
        preview = rig.env.call(rig.token, "auto_cull", self.args())
        tools_culling.reset_preview_memory()
        result = self.apply(rig, preview)
        assert result["ok"], result
        sent = self.auto_calls(rig)
        assert [c["dry_run"] for c in sent] == [True, True, False]
        assert "skip_paths" not in sent[-1]
        assert _rejected() == {BURST_PATHS[2]}

    def test_a_confirm_is_single_use(self, rig):
        preview = rig.env.call(rig.token, "auto_cull", self.args())
        assert self.apply(rig, preview)["ok"]
        assert self.apply(rig, preview)["error"] == "confirmation_required"


def test_a_pinned_card_without_a_group_reason_labels_the_photo_count():
    page = tools_culling._pinned_page([{"number": 1, "keep_paths": ["/k"], "reject_paths": ["/r1", "/r2"]}])
    assert page.labels[0] == {"key": "photo_count", "params": {"n": 3}}


class TestAutoCullApplyWithUnreadableMarks:
    """I2: a preview built on the tab's marks is not applied when the tab cannot be re-read."""

    @pytest.fixture()
    def rig(self, agent_app, photos, fake_tab, monkeypatch):
        from tests.conftest import intercept_internal_call
        nonce.reset()
        tools_culling.reset_preview_memory()
        state = {"review": {"keep": [], "remove": []}, "upstream": [], "fail": False}
        env = agent_app("legacy")
        headers = env.login(edition=True)

        def reply(call):
            if call["tool"] == "ui_get_context":
                if state["fail"]:
                    return {"ok": False, "error": "tab_timeout"}
                return {"ok": True, "data": {"review": state["review"]}}
            return {"ok": True, "data": {"echo": call["tool"]}}
        tab = fake_tab(env, _jwt_of(headers), reply=reply)
        intercept_internal_call(monkeypatch, lambda tool, kw: state["upstream"].append((tool, kw)) and None)
        token = env.token(headers, "edition")
        yield type("Rig", (), {"env": env, "token": token, "tab": tab, "state": state})
        for path in BURST_PATHS:
            _rate(path, star_rating=0, is_favorite=0, is_rejected=0)

    @staticmethod
    def args(**extra):
        return {"group_by": "burst", "strictness": 0, "show": False, **SCOPE, **extra}

    def apply(self, rig, preview):
        return rig.env.call(rig.token, "auto_cull", self.args(dry_run=False, confirm=preview["confirm"]))

    def applies(self, rig):
        return [kw["json"] for tool, kw in rig.state["upstream"]
                if tool == "culling.auto" and not kw["json"]["dry_run"]]

    def refused(self, rig, result):
        assert result["error"] == "confirmation_required", result
        assert not self.applies(rig) and _rejected() == set()

    def test_a_failed_re_read_refuses_the_apply(self, rig):
        rig.state["review"] = {"keep": [], "remove": [BURST_PATHS[1]]}
        preview = rig.env.call(rig.token, "auto_cull", self.args())
        rig.state["fail"] = True
        self.refused(rig, self.apply(rig, preview))

    def test_a_truncated_re_read_refuses_the_apply(self, rig):
        rig.state["review"] = {"keep": [], "remove": [BURST_PATHS[1]]}
        preview = rig.env.call(rig.token, "auto_cull", self.args())
        rig.state["review"] = {"keep": [], "remove": [], "truncated": True}
        self.refused(rig, self.apply(rig, preview))

    def test_more_flips_than_the_skip_list_holds_refuses_the_apply(self, rig):
        rig.state["review"] = {"keep": [], "remove": [BURST_PATHS[1]]}
        preview = rig.env.call(rig.token, "auto_cull", self.args())
        rig.state["review"] = {"keep": [f"/k{i}" for i in range(999)], "remove": [f"/r{i}" for i in range(999)]}
        self.refused(rig, self.apply(rig, preview))

    def test_a_preview_without_tab_marks_applies_despite_a_failed_re_read(self, rig):
        preview = rig.env.call(rig.token, "auto_cull", self.args())
        rig.state["fail"] = True
        result = self.apply(rig, preview)
        assert result["ok"], result
        assert len(self.applies(rig)) == 1 and _rejected() == {BURST_PATHS[2]}


class TestAutoCullAppliedFromTheTab:
    """The user's own Apply in the tab: the photos they applied are never re-decided, whatever the call shape."""

    @pytest.fixture()
    def rig(self, agent_app, photos, fake_tab, monkeypatch):
        from tests.conftest import intercept_internal_call
        nonce.reset()
        tools_culling.reset_preview_memory()
        state = {"review": {"keep": [], "remove": []}, "upstream": []}
        env = agent_app("legacy")
        headers = env.login(edition=True)

        def reply(call):
            if call["tool"] == "ui_get_context":
                return {"ok": True, "data": {"review": state["review"]}}
            return {"ok": True, "data": {"echo": call["tool"]}}
        tab = fake_tab(env, _jwt_of(headers), reply=reply)
        intercept_internal_call(monkeypatch, lambda tool, kw: state["upstream"].append((tool, kw)) and None)
        token = env.token(headers, "edition")
        yield type("Rig", (), {"env": env, "token": token, "tab": tab, "state": state})
        with sqlite3.connect(_TEST_DB_FILE.name) as conn:
            conn.execute("UPDATE photos SET burst_reviewed = 0, is_rejected = 0 WHERE path LIKE ?", (PREFIX + "%",))

    @staticmethod
    def args(**extra):
        return {"group_by": "burst", "strictness": 0, "show": False, **SCOPE, **extra}

    @staticmethod
    def applied(keep=(), remove=(), truncated=False):
        return {"keep": list(keep), "remove": list(remove), "truncated": truncated}

    def sent(self, rig):
        return [kw["json"] for tool, kw in rig.state["upstream"] if tool == "culling.auto"]

    def apply(self, rig, preview, **extra):
        return rig.env.call(rig.token, "auto_cull", self.args(dry_run=False, confirm=preview["confirm"], **extra))

    def test_marks_from_review_parses_the_applied_block(self):
        marks = tools_culling.marks_from_review({
            "keep": ["/a"], "remove": [],
            "applied": {"keep": ["/k"], "remove": ["/r"], "truncated": False}})
        assert marks.applied == ("/k", "/r") and marks.applied_truncated is False and marks.has_applied
        assert tools_culling.marks_from_review({"keep": [], "remove": []}).has_applied is False
        cut = tools_culling.marks_from_review({"applied": {"keep": ["/k"], "remove": [], "truncated": True}})
        assert cut.applied_truncated is True

    def test_applied_with_no_pending_marks_is_not_usable_but_is_reported(self, rig):
        rig.state["review"] = {"keep": [], "remove": [], "applied": self.applied(keep=[BURST_PATHS[0]])}
        preview = rig.env.call(rig.token, "auto_cull", self.args())
        assert preview["ok"], preview
        assert preview["overrides_from_tab"] == {"applied": 1}
        result = self.apply(rig, preview)
        assert result["ok"], result
        assert self.sent(rig)[-1]["skip_paths"] == [BURST_PATHS[0]]
        assert self.sent(rig)[-1]["applied_paths"] == [BURST_PATHS[0]]

    def test_the_marked_branch_skips_the_applied_paths_and_reports_the_count(self, rig):
        rig.state["review"] = {"keep": [BURST_PATHS[0]], "remove": [BURST_PATHS[1]],
                               "applied": self.applied(remove=[BURST_PATHS[2]])}
        preview = rig.env.call(rig.token, "auto_cull", self.args())
        assert preview["overrides_from_tab"]["applied"] == 1 and "keep" in preview["overrides_from_tab"]
        result = self.apply(rig, preview)
        assert result["ok"], result
        sent = self.sent(rig)[-1]
        assert sent["skip_paths"] == [BURST_PATHS[2]] and sent["applied_paths"] == [BURST_PATHS[2]]

    def test_the_explicit_branch_reads_only_the_applied_block(self, rig):
        rig.state["review"] = {"keep": [BURST_PATHS[0]], "remove": [BURST_PATHS[1]],
                               "applied": self.applied(keep=[BURST_PATHS[2]])}
        preview = rig.env.call(rig.token, "auto_cull", self.args(keep_paths=[BURST_PATHS[0]]))
        assert preview["ok"], preview
        assert preview["overrides_from_tab"] == {"applied": 1}
        result = self.apply(rig, preview, keep_paths=[BURST_PATHS[0]])
        assert result["ok"], result
        sent = self.sent(rig)[-1]
        assert sent["keep_paths"] == [BURST_PATHS[0]] and sent["remove_paths"] == []
        assert sent["skip_paths"] == [BURST_PATHS[2]]

    def test_flips_and_applied_paths_are_one_deduplicated_skip_list(self, rig):
        rig.state["review"] = {"keep": [], "remove": [BURST_PATHS[1]],
                               "applied": self.applied(keep=[BURST_PATHS[2]])}
        preview = rig.env.call(rig.token, "auto_cull", self.args())
        rig.state["review"] = {"keep": [], "remove": [],
                               "applied": self.applied(keep=[BURST_PATHS[2], BURST_PATHS[1]])}
        result = self.apply(rig, preview)
        assert result["ok"], result
        assert sorted(self.sent(rig)[-1]["skip_paths"]) == sorted([BURST_PATHS[1], BURST_PATHS[2]])

    def test_the_apply_reports_what_the_tab_applied_after_the_preview(self, rig):
        preview = rig.env.call(rig.token, "auto_cull", self.args())
        assert "overrides_from_tab" not in preview
        rig.state["review"] = {"keep": [], "remove": [], "applied": self.applied(keep=[BURST_PATHS[0]])}
        result = self.apply(rig, preview)
        assert result["ok"], result
        assert result["overrides_from_tab"] == {"applied": 1}
        assert self.sent(rig)[-1]["skip_paths"] == [BURST_PATHS[0]]

    def test_a_re_preview_lists_an_applied_photo_as_skipped_not_as_a_reject(self, rig):
        plain = rig.env.call(rig.token, "auto_cull", self.args())
        listed = [p for row in plain["data"]["rows"] for p in row["keep_paths"] + row["reject_paths"]]
        victim = BURST_PATHS[2]
        assert victim in listed
        rig.state["review"] = {"keep": [], "remove": [], "applied": self.applied(remove=[victim])}
        preview = rig.env.call(rig.token, "auto_cull", self.args())
        shown = [p for row in preview["data"]["rows"] for p in row["keep_paths"] + row["reject_paths"]]
        assert victim not in shown
        assert preview["data"]["skipped_applied"] == {"count": 1, "paths": [victim]}
        assert preview["data"]["plan_digest"] == plain["data"]["plan_digest"]
        result = self.apply(rig, preview)
        assert result["ok"], result
        assert self.sent(rig)[-1]["skip_paths"] == [victim]

    def test_a_truncated_applied_block_refuses_the_apply(self, rig):
        rig.state["review"] = {"keep": [], "remove": [], "applied": self.applied(keep=[BURST_PATHS[0]])}
        preview = rig.env.call(rig.token, "auto_cull", self.args())
        rig.state["review"] = {"keep": [], "remove": [],
                               "applied": self.applied(keep=[BURST_PATHS[0]], truncated=True)}
        result = self.apply(rig, preview)
        assert result["error"] == "confirmation_required", result
        assert not [c for c in self.sent(rig) if not c["dry_run"]] and _rejected() == set()

    def test_more_applied_paths_than_the_skip_list_holds_refuses_the_apply(self, rig):
        rig.state["review"] = {"keep": [], "remove": [],
                               "applied": self.applied(keep=[f"/a{i}" for i in range(600)],
                                                       remove=[f"/b{i}" for i in range(600)])}
        preview = rig.env.call(rig.token, "auto_cull", self.args())
        result = self.apply(rig, preview)
        assert result["error"] == "confirmation_required", result
        assert not [c for c in self.sent(rig) if not c["dry_run"]]

    def test_an_apply_without_memory_of_the_confirm_still_skips_the_applied_paths(self, rig):
        rig.state["review"] = {"keep": [], "remove": [], "applied": self.applied(keep=[BURST_PATHS[0]])}
        preview = rig.env.call(rig.token, "auto_cull", self.args())
        tools_culling.reset_preview_memory()
        result = self.apply(rig, preview)
        assert result["ok"], result
        assert self.sent(rig)[-1]["skip_paths"] == [BURST_PATHS[0]]

    def test_a_plan_moved_by_the_users_apply_tells_the_assistant_to_preview_again(self, rig):
        rig.state["review"] = {"keep": [], "remove": [], "applied": self.applied()}
        preview = rig.env.call(rig.token, "auto_cull", self.args())
        assert preview["ok"], preview
        with sqlite3.connect(_TEST_DB_FILE.name) as conn:
            conn.execute("UPDATE photos SET burst_reviewed = 1 WHERE path LIKE ?", (PREFIX + "%",))
        rig.state["review"] = {"keep": [], "remove": [],
                               "applied": self.applied(keep=[BURST_PATHS[0]], remove=BURST_PATHS[1:])}
        result = self.apply(rig, preview)
        assert result["error"] == "confirmation_required", result
        assert "applied groups in the tab" in result["message"] and "dry_run=true" in result["message"]
        assert _rejected() == set()
