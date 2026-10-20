"""``tools/list`` shows exactly what the key may call; the profile only narrows the list, never the wall.

[REAL] ``agent_app`` (real auth chain), the real tool registry and the real write routes against a
seeded row; nothing on the auth path is mocked.
"""

import copy
import json

import pytest

from api import config as api_config
from api.agent.tools_common import CORE_TOOLS, TOOL_LEVELS
from api.agent.tools_write import WRITE_TOOL_LEVELS
from tests import test_agent_write as write_tests
from tests.conftest import AGENT_DIR

P, ROWS, ARGS, wipe_prefs = write_tests.P, write_tests.ROWS, write_tests.TestGrantMatrix.ARGS, write_tests.wipe_prefs

# What the WRAPPER refuses (level floor, operator switch). A route's own config refusal (the OS-trash switch on
# delete_photos, say) is an upstream answer for a tool that is listed, so it is not in this set.
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
                      and not n.startswith("ui_")} or level == "readonly"


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


def test_the_listing_is_a_json_list_of_unique_names(agent_app):
    env = agent_app("legacy")
    resp = env.rpc(env.token(env.login(edition=True), "edition"), "tools/list").json()["result"]["tools"]
    names = [t["name"] for t in resp]
    assert len(names) == len(set(names)) and json.dumps(names) and copy.copy(names)
