"""``tools/list`` shows exactly what the key may call; the profile only narrows the list, never the wall.

[REAL] ``agent_app`` (real auth chain), the real tool registry and the real write routes against a
seeded row; nothing on the auth path is mocked.
"""

import pytest

from api import config as api_config
from api.agent import tokens
from api.agent.tools_common import CORE_TOOLS, TOOL_LEVELS
from api.agent.tools_write import WRITE_TOOL_LEVELS
from tests import test_agent_write as write_tests
from tests.conftest import AGENT_DIR

P, ROWS, ARGS, wipe_prefs = write_tests.P, write_tests.ROWS, write_tests.TestGrantMatrix.ARGS, write_tests.wipe_prefs

# What the WRAPPER refuses (level floor, operator switch). A route's own config refusal (the OS-trash switch on
# delete_photos, say) is an upstream answer for a tool that is listed, so it is not in this set.
SCAN_TOOLS = {"start_scan", "scan_status"}   # behind viewer.features.show_scan_button, off in the test config
WRAPPER_MESSAGES = ("token's level", "allow_destructive", "show_scan_button")


@pytest.fixture()
def photos(seed_photos_prefix):
    wipe_prefs()
    yield seed_photos_prefix(AGENT_DIR, ROWS)
    wipe_prefs()


def refused(env, token, tool):
    result = env.call(token, tool, ARGS[tool])
    return result.get("error") in ("forbidden_level", "feature_disabled") and any(
        m in result["message"] for m in WRAPPER_MESSAGES)


@pytest.mark.parametrize("who,level", [("root", "readonly"), ("alice", "user"), ("root", "edition")])
def test_the_listed_write_tools_are_exactly_the_ones_a_call_is_not_refused_for(agent_app, photos, who, level):
    env = agent_app("multi", allow_destructive=True)
    token = env.token(env.login(who), level)
    listed = env.tool_names(token)
    for tool in WRITE_TOOL_LEVELS:
        assert (tool in listed) is (not refused(env, token, tool)), (level, tool)
    assert listed >= {n for n, floor in TOOL_LEVELS.items() if floor == "readonly" and n not in WRITE_TOOL_LEVELS
                      and not n.startswith("ui_")}


@pytest.mark.parametrize("mode,who,level", [
    ("multi", "root", "readonly"), ("multi", "alice", "user"), ("multi", "root", "edition"),
    ("legacy", None, "readonly"), ("legacy", None, "edition"), ("open", None, "readonly")])
def test_every_registered_tool_is_listed_exactly_when_its_requirement_is_met(agent_app, photos, mode, who, level):
    """All tools, not just the writes: culling, ui_* and reads, in every install mode.

    A single-password install has no ``user`` rung, so its ``user`` tools need ``edition`` there.
    """
    env = agent_app(mode, allow_destructive=True)
    login = env.login(who) if who else (env.login(edition=True) if level == "edition" else env.login())
    token = env.token(login, level)
    rank = tokens.level_rank(level)
    expected = {n for n, floor in TOOL_LEVELS.items()
                if rank >= tokens.level_rank(tokens.effective_requirement(floor))}
    listed = env.tool_names(token)
    assert listed == expected - SCAN_TOOLS, (sorted(listed ^ expected))
    assert {n for n in listed if n.startswith("ui_")} and any(n.startswith("get_culling") or "cull" in n for n in listed)


def test_a_downgrade_shrinks_the_very_next_list(agent_app, photos):
    env = agent_app("multi")
    token = env.token(env.login("root"), "edition")
    before = env.tool_names(token)
    assert "override_sequence" in before
    api_config._FULL_CONFIG["users"]["root"]["role"] = "user"
    after = env.tool_names(token)
    assert "override_sequence" not in after and "set_rating" in after and after < before


def test_destructive_tools_are_hidden_by_default_and_listed_when_allowed(agent_app):
    env = agent_app("legacy")
    token = env.token(env.login(edition=True), "edition")
    assert "delete_photos" not in env.tool_names(token)
    assert "cull_apply" in env.tool_names(token), "cull_apply stays listed: only its destructive actions refuse"
    env = agent_app("legacy", allow_destructive=True)
    assert "delete_photos" in env.tool_names(env.token(env.login(edition=True), "edition"))


def test_the_shipped_default_keeps_destructive_actions_off():
    assert api_config.MCP_SETTINGS_DEFAULTS["allow_destructive"] is False
    assert api_config.MCP_SETTINGS_DEFAULTS["enabled"] is True
    assert api_config.MCP_SETTINGS_DEFAULTS["tool_profile"] == "full"


def test_core_profile_lists_exactly_the_core_tools_and_no_destructive_one(agent_app):
    env = agent_app("legacy", tool_profile="core", allow_destructive=True)
    token = env.token(env.login(edition=True), "edition")
    resp = env.rpc(token, "tools/list").json()["result"]["tools"]
    names = {t["name"] for t in resp}
    assert names == CORE_TOOLS and len(names) <= 12
    assert not [t["name"] for t in resp if (t.get("annotations") or {}).get("destructiveHint")]


def test_a_tool_hidden_by_the_core_profile_is_still_callable(agent_app):
    env = agent_app("legacy", tool_profile="core")
    token = env.token(env.login(), "readonly")
    assert "list_persons" not in env.tool_names(token)
    assert env.call(token, "list_persons", {})["ok"] is True


def test_an_unknown_profile_falls_back_to_full(agent_app):
    env = agent_app("legacy", tool_profile="bogus")
    token = env.token(env.login(edition=True), "edition")
    assert len(env.tool_names(token)) > 12
    assert env.call(token, "status", {})["data"]["tool_profile"] == "full"


def test_status_says_what_is_hidden_and_why(agent_app):
    env = agent_app("legacy")
    readonly = env.call(env.token(env.login(), "readonly"), "status", {})["data"]["hidden_tools"]
    assert readonly["count"] > 0 and readonly["needs"] == "edition" and "edition token" in readonly["hint"]
    edition = env.call(env.token(env.login(edition=True), "edition"), "status", {})["data"]["hidden_tools"]
    assert edition["count"] == 0
    disabled = {d["tool"]: d["reason"] for d in edition["disabled"]}
    assert "allow_destructive" in disabled["delete_photos"] and "show_scan_button" in disabled["start_scan"]


def test_a_hidden_tool_is_refused_not_missing(agent_app):
    env = agent_app("legacy")
    token = env.token(env.login(edition=True), "edition")
    result = env.call(token, "delete_photos", {"paths": [P[0]]})
    assert result["error"] == "feature_disabled" and "allow_destructive" in result["message"]


def test_the_listing_is_a_non_empty_list_of_unique_names(agent_app):
    env = agent_app("legacy")
    resp = env.rpc(env.token(env.login(edition=True), "edition"), "tools/list").json()["result"]["tools"]
    names = [t["name"] for t in resp]
    assert names and len(names) == len(set(names))


@pytest.mark.parametrize("args", [{}, {"nope": 1}, {"paths": "not-a-list", "rating": 99}])
def test_a_tool_above_the_level_answers_forbidden_level_before_any_argument_check(agent_app, args):
    env = agent_app("legacy")
    token = env.token(env.login(), "readonly")
    assert "set_rating" not in env.tool_names(token)
    result = env.call(token, "set_rating", args)
    assert result["error"] == "forbidden_level" and "issues" not in result, result
    assert env.call(env.token(env.login(edition=True), "edition"), "set_rating", args)["error"] == "invalid_input"
