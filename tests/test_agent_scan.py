"""``start_scan`` / ``scan_status`` over /mcp: the route's own gates, a directory pre-check and no free spawn.

[REAL] ``agent_app`` (real auth chain) and the real scan router. Only the OS boundary is replaced: the
router's ``Popen``, its output reader, its configured-directory list and its job-conflict probe. The
Popen recorder is what proves a refused call spawned nothing.
"""

from collections import deque

import pytest

from api import config as api_config
import importlib
import subprocess
from types import SimpleNamespace
from tests.conftest import AGENT_DIR

scan = importlib.import_module("api.routers.scan")
CONFIGURED = [AGENT_DIR + "scan-a/", AGENT_DIR + "scan-b/"]


def spawner(spawned):
    """A stand-in for the router's ``subprocess`` name only (patching the real module would leak)."""
    return SimpleNamespace(Popen=lambda cmd, **kw: (spawned.append(cmd), FakeProc())[1],
                           SubprocessError=subprocess.SubprocessError, PIPE=-1, STDOUT=-2)


class FakeProc:
    pid = 4242
    stdout = iter(())


@pytest.fixture()
def world(agent_app, monkeypatch):
    spawned = []
    monkeypatch.setattr(scan, "subprocess", spawner(spawned))
    monkeypatch.setattr(scan, "_read_scan_output", lambda proc: None)
    monkeypatch.setattr(scan, "get_all_scan_directories", lambda: list(CONFIGURED))
    monkeypatch.setattr(scan, "_library_job_conflict_detail", lambda: None)
    for key, value in (("running", False), ("kind", None), ("process", None), ("started_at", None),
                       ("directories", []), ("exit_code", None), ("progress", None),
                       ("output_lines", deque(maxlen=500))):
        monkeypatch.setitem(scan._scan_state, key, value)
    monkeypatch.setitem(api_config.VIEWER_CONFIG.setdefault("features", {}), "show_scan_button", True)
    env = agent_app("legacy")
    yield env, env.token(env.login(edition=True), "edition"), spawned


def test_flag_off_refuses_and_hides_nothing_is_spawned(world, monkeypatch):
    env, token, spawned = world
    monkeypatch.setitem(api_config.VIEWER_CONFIG["features"], "show_scan_button", False)
    for tool, args in (("start_scan", {"directories": CONFIGURED[:1]}), ("scan_status", {})):
        refused = env.call(token, tool, args)
        assert refused["error"] == "feature_disabled" and "show_scan_button" in refused["message"]
    assert spawned == []


def test_flag_off_unlists_the_tools(world, monkeypatch):
    env, token, _ = world
    assert {"start_scan", "scan_status"} <= env.tool_names(token)
    monkeypatch.setitem(api_config.VIEWER_CONFIG["features"], "show_scan_button", False)
    assert not {"start_scan", "scan_status"} & env.tool_names(token)


def test_an_unconfigured_directory_is_refused_before_anything_spawns(world):
    env, token, spawned = world
    refused = env.call(token, "start_scan", {"directories": [CONFIGURED[0], "/etc/"]})
    assert refused["error"] == "invalid_input" and "/etc/" in refused["message"]
    assert refused["configured_directories"] == CONFIGURED and spawned == []


def test_a_configured_directory_spawns_exactly_the_validated_command(world):
    env, token, spawned = world
    done = env.call(token, "start_scan", {"directories": [CONFIGURED[1]]})
    assert done["ok"] and done["data"]["pid"] == 4242 and done["data"]["undoable"] is False
    assert len(spawned) == 1 and spawned[0][-1:] == [CONFIGURED[1]] and spawned[0][1] == scan.FACET_SCRIPT


def test_a_running_scan_is_a_conflict_and_spawns_nothing(world, monkeypatch):
    env, token, spawned = world
    monkeypatch.setitem(scan._scan_state, "running", True)
    refused = env.call(token, "start_scan", {"directories": CONFIGURED[:1]})
    assert refused["error"] == "conflict" and spawned == []


def test_status_caps_the_returned_lines(world, monkeypatch):
    env, token, _ = world
    monkeypatch.setitem(scan._scan_state, "output_lines", deque((f"line {i}" for i in range(120)), maxlen=500))
    data = env.call(token, "scan_status", {"lines": 50})["data"]
    assert len(data["output"]) == 50 and data["output"][-1] == "line 119"
    assert data["configured_directories"] == CONFIGURED and data["running"] is False
    assert env.call(token, "scan_status", {"lines": 0})["data"]["output"] == []
    assert env.call(token, "scan_status", {"lines": 51})["ok"] is False


def test_more_than_twenty_directories_are_refused(world):
    env, token, spawned = world
    assert env.call(token, "start_scan", {"directories": [f"/d{i}/" for i in range(21)]})["ok"] is False
    assert spawned == []


def test_a_readonly_key_cannot_see_or_call_the_scan_tools(world):
    env, _, spawned = world
    readonly = env.token(env.login(), "readonly")
    assert not {"start_scan", "scan_status"} & env.tool_names(readonly)
    assert env.call(readonly, "start_scan", {"directories": CONFIGURED[:1]})["error"] == "forbidden_level"
    assert spawned == []


def test_an_open_install_cannot_start_a_scan(agent_app, monkeypatch):
    spawned = []
    monkeypatch.setattr(scan, "subprocess", spawner(spawned))
    monkeypatch.setattr(scan, "get_all_scan_directories", lambda: list(CONFIGURED))
    monkeypatch.setitem(api_config.VIEWER_CONFIG.setdefault("features", {}), "show_scan_button", True)
    env = agent_app("open")
    token = env.token(env.login(), "readonly")
    assert env.call(token, "start_scan", {"directories": CONFIGURED[:1]})["error"] == "forbidden_level"
    assert spawned == []


def test_multi_user_needs_a_superadmin_not_just_an_admin(agent_app, monkeypatch):
    spawned = []
    monkeypatch.setattr(scan, "subprocess", spawner(spawned))
    monkeypatch.setattr(scan, "_read_scan_output", lambda proc: None)
    monkeypatch.setattr(scan, "get_all_scan_directories", lambda: list(CONFIGURED))
    monkeypatch.setattr(scan, "_library_job_conflict_detail", lambda: None)
    monkeypatch.setitem(scan._scan_state, "running", False)
    monkeypatch.setitem(api_config.VIEWER_CONFIG.setdefault("features", {}), "show_scan_button", True)
    env = agent_app("multi")
    admin = env.token(env.login("root"), "edition")
    assert env.call(admin, "start_scan", {"directories": CONFIGURED[:1]})["error"] == "forbidden_level"
    assert "start_scan" not in env.tool_names(admin) and spawned == []
    api_config._FULL_CONFIG["users"]["root"]["role"] = "superadmin"
    superadmin = env.token(env.login("root"), "edition")
    assert "start_scan" in env.tool_names(superadmin)
    assert env.call(superadmin, "start_scan", {"directories": CONFIGURED[:1]})["ok"]
    assert len(spawned) == 1


def test_the_tool_gate_and_the_route_gate_are_one_rule():
    from api.auth import scan_access_refusal
    from api.agent import requirements
    import inspect
    assert "scan_access_refusal" in inspect.getsource(requirements.scan_available)
    assert "scan_access_refusal" in inspect.getsource(__import__("api.auth", fromlist=["x"]).require_scan_access)
    assert scan_access_refusal(False, False, True, True)[0] == 403 and scan_access_refusal(False, False, True, False) is None
    assert scan_access_refusal(True, False, True, False)[0] == 403 and scan_access_refusal(True, True, False, True) is None
