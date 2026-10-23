"""MCP resources: five read-only ``facet://`` lists (a sixth, scoring-weights, for edition), served per caller through the same routes as the tools.

[REAL] ``agent_app`` (real auth chain), real routes, rows seeded into the shared session DB.
"""

import json

import pytest

from api.agent import resources
from api.agent.tools_common import MCP_FILTER_KEYS
from tests.conftest import AGENT_DIR, agent_db as db

PREFIX = AGENT_DIR + "res/"
URIS = {"facet://categories", "facet://tags", "facet://persons", "facet://filters", "facet://scoring-contexts"}


def read(env, token, uri):
    resp = env.rpc(token, "resources/read", {"uri": uri})
    assert resp.status_code == 200, resp.text
    return resp.json()


def body(env, token, uri):
    contents = read(env, token, uri)["result"]["contents"]
    assert len(contents) == 1 and contents[0]["mimeType"] == "application/json"
    return json.loads(contents[0]["text"])


@pytest.fixture()
def world(agent_app):
    env = agent_app("legacy")
    return env, env.token(env.login(), "readonly")


def test_an_edition_key_is_offered_a_sixth_resource_the_scoring_weights(agent_app):
    env = agent_app("legacy")
    token = env.token(env.login(edition=True), "edition")
    listed = {r["uri"] for r in env.rpc(token, "resources/list").json()["result"]["resources"]}
    assert listed == URIS | {"facet://scoring-weights"}


def test_exactly_five_static_resources_and_no_templates(world):
    env, token = world
    listed = env.rpc(token, "resources/list").json()["result"]["resources"]
    assert {r["uri"] for r in listed} == URIS and len(listed) == 5
    assert env.rpc(token, "resources/templates/list").json()["result"]["resourceTemplates"] == []


def test_every_resource_reads_with_uri_truncated_and_data(world):
    env, token = world
    for uri in URIS:
        payload = body(env, token, uri)
        assert payload["uri"] == uri and payload["truncated"] is False and payload["data"], uri


def test_the_resource_is_marked_untrusted(world):
    env, token = world
    meta = read(env, token, "facet://categories")["result"]["contents"][0]["_meta"]
    assert meta == resources.UNTRUSTED_META


def test_unknown_uri_is_an_invalid_params_error(world):
    env, token = world
    error = read(env, token, "facet://nope")["error"]
    assert error["code"] == -32602 and "facet://nope" in error["message"]


def test_a_missing_or_bad_token_is_401(world):
    env, _ = world
    assert env.rpc(None, "resources/read", {"uri": "facet://tags"}).status_code == 401
    assert env.rpc("not-a-token", "resources/list").status_code == 401


def test_filters_resource_lists_exactly_the_search_filter_keys(world):
    env, token = world
    data = body(env, token, "facet://filters")["data"]
    assert set(data["filters"]) == set(MCP_FILTER_KEYS)
    assert data["filters"]["min_score"] == {"type": "string"}, "the gallery wire carries every filter as a string"
    assert data["metric_ranges"]


def test_tags_are_cut_at_the_row_cap_and_flagged_truncated(agent_app, seed_photos_prefix):
    tags = [f"zzres{i:04d}" for i in range(320)]
    seed_photos_prefix(PREFIX, [{"path": PREFIX + "t.jpg", "filename": "t.jpg", "tags": ",".join(tags)}])
    db("DELETE FROM photo_tags WHERE photo_path = ?", PREFIX + "t.jpg")
    for tag in tags:
        db("INSERT INTO photo_tags(photo_path, tag) VALUES (?, ?)", PREFIX + "t.jpg", tag)
    try:
        env = agent_app("legacy")
        token = env.token(env.login(), "readonly")
        payload = body(env, token, "facet://tags")
        assert len(payload["data"]["tags"]) <= resources.MAX_ROWS
        assert len(json.dumps(payload).encode()) <= resources.MAX_BYTES + 512
    finally:
        db("DELETE FROM photo_tags WHERE photo_path = ?", PREFIX + "t.jpg")


def test_domain_reads_the_declared_type_of_a_filter(monkeypatch):
    from types import SimpleNamespace
    from typing import Literal, Optional
    fields = {"a": SimpleNamespace(annotation=Literal["x", "y"]), "b": SimpleNamespace(annotation=Optional[int]),
              "c": SimpleNamespace(annotation=bool)}
    monkeypatch.setattr(resources.GalleryParams, "model_fields", fields)
    assert resources._domain("a") == {"enum": ["x", "y"]} and resources._domain("b") == {"type": "integer"}
    assert resources._domain("c") == {"type": "boolean"} and resources._domain("zz") == {"type": "string"}


def test_limit_truncates_rows_then_bytes():
    cut, flag = resources._limit({"rows": list(range(500))})
    assert len(cut["rows"]) == resources.MAX_ROWS and flag is True
    fat, flagged = resources._limit({"rows": ["x" * 400] * 150})
    assert flagged and len(json.dumps(fat).encode()) <= resources.MAX_BYTES
    same, untouched = resources._limit({"rows": [1, 2]})
    assert same == {"rows": [1, 2]} and untouched is False


def test_persons_respect_multi_user_visibility(agent_app, seed_photos_prefix):
    seed_photos_prefix(PREFIX, [{"path": PREFIX + "p.jpg", "filename": "p.jpg"}])
    db("INSERT INTO persons(id, name, face_count) VALUES (880001, 'Zz Alice Person', 1)")
    db("INSERT INTO faces(embedding, photo_path, face_index, person_id) VALUES (x'00', ?, 0, 880001)",
       PREFIX + "p.jpg")
    try:
        env = agent_app("multi")
        alice = body(env, env.token(env.login("alice"), "readonly"), "facet://persons")["data"]["persons"]
        bob = body(env, env.token(env.login("bob"), "readonly"), "facet://persons")["data"]["persons"]
        assert "Zz Alice Person" in {p["name"] for p in alice}
        assert "Zz Alice Person" not in {p["name"] for p in bob}
    finally:
        db("DELETE FROM faces WHERE photo_path = ?", PREFIX + "p.jpg")
        db("DELETE FROM persons WHERE id = 880001")


def test_readers_never_open_the_database_themselves():
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(resources))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree)
                                                                      if isinstance(n, ast.Attribute)}
    assert not names & {"get_db", "sqlite3", "execute"}


def test_categories_and_tags_are_flat_lists_without_the_route_cache_flag(world):
    env, token = world
    for uri, key in (("facet://categories", "categories"), ("facet://tags", "tags")):
        data = body(env, token, uri)["data"]
        assert set(data) == {key} and isinstance(data[key], list), (uri, data)


def test_resources_list_follows_the_tool_profile_like_tools_list(agent_app):
    env = agent_app("legacy", tool_profile="core")
    token = env.token(env.login(), "readonly")
    assert "list_persons" not in env.tool_names(token)
    listed = {r["uri"] for r in env.rpc(token, "resources/list").json()["result"]["resources"]}
    assert listed == URIS - {"facet://persons"}


def test_a_read_depends_on_the_level_only_never_on_the_tool_profile(agent_app):
    full = agent_app("legacy")
    core = agent_app("legacy", tool_profile="core")
    full_token, core_token = full.token(full.login(), "readonly"), core.token(core.login(), "readonly")
    assert "list_persons" not in core.tool_names(core_token)
    for uri in sorted(URIS):
        assert body(core, core_token, uri) == body(full, full_token, uri), uri


def test_the_edition_resource_is_refused_to_a_readonly_key_but_read_by_an_edition_key(agent_app):
    env = agent_app("legacy")
    readonly = env.token(env.login(), "readonly")
    error = read(env, readonly, "facet://scoring-weights")["error"]
    assert error["code"] == -32602 and "facet://scoring-weights" in error["message"]
    edition = env.token(env.login(edition=True), "edition")
    payload = body(env, edition, "facet://scoring-weights")
    assert payload["uri"] == "facet://scoring-weights" and payload["data"]
