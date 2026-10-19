"""Darkroom agent tools (``list_culling_groups`` ... ``confirm_culling_groups``) over /mcp.

Seeds a burst, a similar-free library slice and a bracket set under ``AGENT_DIR`` with
a unique capture-date window so ``date_from``/``date_to`` scope every call to them.
"""

import sqlite3

import pytest

from api.agent import nonce, server, tools_culling
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
def wired(monkeypatch):
    """Register the culling tools on the server the way ``mount_agent`` will."""
    original = server.register_read_tools

    def register(srv, client, status_extra):
        original(srv, client, status_extra)
        if srv._tool_manager.get_tool("list_culling_groups") is None:
            tools_culling.register_culling_tools(srv, client._app)

    monkeypatch.setattr(server, "register_read_tools", register)
    nonce.reset()


@pytest.fixture()
def env_token(wired, agent_app, photos):
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
    def test_user_and_readonly_tokens_are_refused(self, wired, agent_app, photos):
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

    def test_bad_timestamp_is_invalid_input_before_any_call(self, env_token):
        env, token = env_token
        result = env.call(token, "list_culling_groups", {"date_from": "1999-01-01"})
        assert result["error"] == "invalid_input"


class TestAutoCull:
    def args(self, **extra):
        return {"group_by": "all", **SCOPE, **extra}

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
