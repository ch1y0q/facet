"""The agent never answers a comparison pair: no allowlisted route can record one.

[REAL] the real allowlist tables, the real ``api/agent`` source (parsed, not imported) and the real
app's route table. The status tool is called through ``agent_app``.
"""

import ast
import asyncio
import pathlib
import re
from collections.abc import Mapping

import pytest

import api.agent as agent_pkg
from api.agent import internal_client, tools_culling
from api.agent.internal_client import InternalClient, NotAllowedError, RouteSpec

AGENT_DIR_PATH = pathlib.Path(agent_pkg.__file__).parent
FORBIDDEN = re.compile(r"/api/comparison/(submit|reset|edit|delete|batch|record)", re.I)
ALLOWED_COMPARISON = {"/api/comparison/stats", "/api/comparison/coverage", "/api/comparison/override_category",
                      "/api/comparison/clear_category_override"}


def all_route_specs():
    found = {}
    for module in (internal_client, tools_culling):
        for name, value in vars(module).items():
            if isinstance(value, Mapping):
                for key, spec in value.items():
                    if isinstance(spec, RouteSpec):
                        found[f"{module.__name__}.{name}[{key}]"] = spec
    return found


def test_the_walk_actually_finds_the_tables():
    specs = all_route_specs()
    assert len(specs) > 50 and any("culling.groups" in k for k in specs)


def test_no_route_spec_reaches_a_comparison_write():
    for where, spec in all_route_specs().items():
        assert not FORBIDDEN.search(spec.template), where


def test_comparison_templates_are_exactly_the_reviewed_set():
    templates = {s.template for s in all_route_specs().values() if "/api/comparison/" in s.template}
    assert templates == ALLOWED_COMPARISON


def test_no_string_constant_in_the_agent_package_names_a_comparison_write():
    hits = []
    scanned = 0
    for source in sorted(AGENT_DIR_PATH.glob("*.py")):
        scanned += 1
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and FORBIDDEN.search(node.value):
                hits.append((source.name, node.lineno))
    assert scanned >= 15 and hits == []


def test_the_denylist_is_not_vacuous_the_app_really_has_those_routes(agent_app):
    paths = set(agent_app("legacy").client.app.openapi()["paths"])
    assert {p for p in paths if FORBIDDEN.search(p)} >= {"/api/comparison/submit", "/api/comparison/reset"}


def test_an_unlisted_comparison_tool_raises_before_anything_is_sent(agent_app):
    env = agent_app("legacy")
    client = InternalClient(env.client.app)
    with pytest.raises(NotAllowedError):
        asyncio.run(client.call(None, "comparison_submit", json={"photo_a": "x", "photo_b": "y", "winner": "a"}))


def test_comparison_status_needs_an_edition_token(agent_app):
    env = agent_app("legacy")
    readonly = env.token(env.login(), "readonly")
    assert "comparison_status" not in env.tool_names(readonly)
    assert env.call(readonly, "comparison_status", {})["error"] == "forbidden_level"
    edition = env.token(env.login(edition=True), "edition")
    assert "comparison_status" in env.tool_names(edition)
    data = env.call(edition, "comparison_status", {})["data"]
    assert set(data) >= {"stats", "coverage"}


def test_no_registered_tool_is_a_comparison_writer(agent_app):
    env = agent_app("open")
    token = env.token(env.login(), "readonly")
    from api.agent.tools_common import TOOL_LEVELS
    names = set(TOOL_LEVELS)
    assert not [n for n in names if re.search(r"(submit|record|answer).*(comparison|pair)|comparison.*(submit|record|answer)", n)]
    assert "comparison_status" in names and token
