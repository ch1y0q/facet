"""``ui_tools.py`` is canonical; the client's JSON is generated and must not drift."""

import json
import re

import pytest
from pathlib import Path

from api.agent.ui_tools import UI_TOOLS, render_client_json, tools_version

CLIENT_JSON = Path(__file__).resolve().parent.parent / "client/src/app/core/agent/ui-tools.schema.json"


def test_committed_json_matches_the_contract():
    assert CLIENT_JSON.read_text() == render_client_json(), (
        "ui-tools.schema.json is stale: run `venv/bin/python scripts/dump_ui_tools.py`")


DOCS = Path(__file__).resolve().parent.parent / "docs"


@pytest.mark.parametrize("lang", ["", "fr", "de", "it", "es", "pt", "zh"])
def test_every_ui_tool_has_a_row_in_the_agents_doc_table(lang):
    text = (DOCS / lang / "AGENTS.md").read_text()
    rows = {m.group(1) for m in re.finditer(r"^\| `(ui_[a-z_]+)` \|", text, re.MULTILINE)}
    assert rows == {tool.name for tool in UI_TOOLS}


def test_json_shape_for_the_client_checker():
    data = json.loads(render_client_json())
    assert data["version"] == tools_version() and re.fullmatch(r"[0-9a-f]{16}", data["version"])
    assert [t["name"] for t in data["tools"]] == [t.name for t in UI_TOOLS]
    for tool in data["tools"]:
        schema = tool["inputSchema"]
        assert schema["type"] == "object" and schema["additionalProperties"] is False
        assert "tab_id" not in schema["properties"]
        assert "$ref" not in json.dumps(schema) and "anyOf" not in json.dumps(schema)
        assert {"readOnlyHint", "destructiveHint", "untrustedContentHint"} <= set(tool["annotations"])


def test_json_carries_the_jobs_table_for_the_client():
    from api.agent.actions import ACTIONS, FACTS
    rows = json.loads(render_client_json())["actions"]
    assert [r["id"] for r in rows] == [a.id for a in ACTIONS]
    for row in rows:
        assert set(row) == {"id", "summary", "when", "tools"}
        assert set(row["when"]) <= FACTS
        assert all(set(t) == {"name", "required_level"} for t in row["tools"])


def test_version_changes_with_a_description():
    before = tools_version()
    original = UI_TOOLS[0]
    import api.agent.ui_tools as module
    from dataclasses import replace
    module.UI_TOOLS = (replace(original, description=original.description + "!"),) + UI_TOOLS[1:]
    try:
        assert tools_version() != before
    finally:
        module.UI_TOOLS = (original,) + module.UI_TOOLS[1:]
    assert tools_version() == before


def test_ui_get_context_describes_the_culling_block_and_its_activity_kinds():
    description = next(t for t in UI_TOOLS if t.name == "ui_get_context").description
    for term in ("culling", "plan_digest", "groups_total", "confirmed", "pending", "changed", "untouched",
                 "cull_confirm", "cull_skip"):
        assert term in description, term
    for gone in ("review.applied", "groups_applied", "`review`"):
        assert gone not in description, gone


def test_ui_show_culling_plan_takes_the_digest_the_shared_request_and_a_focus():
    from api.agent.ui_tools import UiShowCullingPlan, input_schema
    from api.models.culling import CullPlanRequest
    assert UiShowCullingPlan.model_fields["request"].annotation is CullPlanRequest
    args = UiShowCullingPlan(plan_digest="abc", request={"group_by": "burst", "strictness": 40}, focus=3)
    forwarded = args.forward()
    assert forwarded["plan_digest"] == "abc" and forwarded["focus"] == 3
    assert forwarded["request"]["group_by"] == "burst" and forwarded["request"]["strictness"] == 40
    assert "focus" not in UiShowCullingPlan(plan_digest="abc", request={}).forward()
    for bad in ({"plan_digest": "abc", "request": {}, "focus": 0}, {"request": {}},
                {"plan_digest": "abc"}, {"plan_digest": "abc", "request": {"group_by": "weird"}},
                {"plan_digest": "abc", "request": {}, "extra": 1}):
        with pytest.raises(ValueError):
            UiShowCullingPlan(**bad)
    schema = input_schema(next(t for t in UI_TOOLS if t.name == "ui_show_culling_plan"))
    text = json.dumps(schema)
    assert "$ref" not in text and "anyOf" not in text and schema["required"] == ["plan_digest", "request"]
    assert schema["properties"]["request"]["properties"]["keep_paths"]["maxItems"] == 1000


def test_ui_show_culling_plan_is_an_edition_write_free_tool():
    tool = next(t for t in UI_TOOLS if t.name == "ui_show_culling_plan")
    assert tool.read_only is False
    assert "/culling" in tool.description and "unsaved_decisions" in tool.description \
        and "plan_changed" in tool.description


def test_the_tab_may_report_the_plan_refusals():
    from api.agent.ui_tools import TAB_ERROR_CODES
    assert {"unsaved_decisions", "plan_changed", "plan_load_failed"} <= TAB_ERROR_CODES


def test_ui_show_photos_path_bound_is_in_the_contract_and_enforced():
    from api.agent.ui_tools import UiShowPhotos
    items = UiShowPhotos.model_json_schema()["properties"]["paths"]["items"]
    assert items["minLength"] == 1 and items["maxLength"] == 4096
    with pytest.raises(ValueError):
        UiShowPhotos(paths=["x" * 4097])
    with pytest.raises(ValueError):
        UiShowPhotos(paths=[""])


def test_ui_show_photos_takes_only_paths_and_rejects_the_removed_review_fields():
    from api.agent.ui_tools import UiShowPhotos
    assert UiShowPhotos(paths=["a", "b"]).forward() == {"paths": ["a", "b"]}
    assert set(UiShowPhotos.model_fields) == {"paths", "tab_id"}
    for name, value in (("groups", [1]), ("marks", ["keep"]), ("labels", [{"key": "burst"}]),
                        ("reasons", [{"key": "best"}]), ("kinds", ["burst"])):
        with pytest.raises(ValueError):
            UiShowPhotos(paths=["a"], **{name: value})


def test_ui_show_photos_schema_is_a_plain_paths_array():
    from api.agent.ui_tools import input_schema
    schema = input_schema(next(t for t in UI_TOOLS if t.name == "ui_show_photos"))
    text = json.dumps(schema)
    assert "$ref" not in text and "anyOf" not in text
    assert schema["additionalProperties"] is False
    assert list(schema["properties"]) == ["paths"]
    description = next(t for t in UI_TOOLS if t.name == "ui_show_photos").description
    assert "keep/remove" not in description and "section" not in description


def test_ui_get_context_takes_an_optional_activity_since():
    from api.agent.ui_tools import UiGetContext, input_schema
    assert UiGetContext().forward() == {}
    assert UiGetContext(activity_since=7).forward() == {"activity_since": 7}
    with pytest.raises(ValueError):
        UiGetContext(activity_since=-1)
    schema = input_schema(next(t for t in UI_TOOLS if t.name == "ui_get_context"))
    assert schema["properties"]["activity_since"]["type"] == "integer"
    text = next(t.description for t in UI_TOOLS if t.name == "ui_get_context")
    assert "activity_since" in text and "user_activity" in text


def test_ui_suggest_culling_bounds():
    from api.agent.ui_tools import UiSuggestCulling
    photo = {"path": "/a.jpg", "action": "reject", "reason": "blink"}
    assert UiSuggestCulling(photos=[photo], groups=[{"path": "/a.jpg", "note": "close call"}]).forward() == {
        "photos": [photo], "groups": [{"path": "/a.jpg", "note": "close call"}], "replace": False}
    assert UiSuggestCulling(replace=True).forward() == {"replace": True, "photos": [], "groups": []}
    for bad in ({}, {"photos": [dict(photo)] * 101}, {"groups": [{"path": "/a", "note": "n"}] * 51},
                {"photos": [{**photo, "reason": "x" * 201}]}, {"groups": [{"path": "/a", "note": "x" * 201}]},
                {"photos": [{**photo, "action": "maybe"}]}, {"photos": [{**photo, "why": "x"}]},
                {"groups": [{"path": "/a", "note": "n", "why": "x"}]}, {"photos": [{**photo, "reason": ""}]},
                {"photos": [{**photo, "path": ""}]}, {"photos": [photo], "extra": 1}):
        with pytest.raises(ValueError):
            UiSuggestCulling(**bad)


def test_ui_suggest_culling_is_an_edition_tool_not_read_only():
    tool = next(t for t in UI_TOOLS if t.name == "ui_suggest_culling")
    assert tool.read_only is False
    names = [t.name for t in UI_TOOLS]
    assert names.index("ui_suggest_culling") == names.index("ui_show_culling_plan") + 1
    for term in ("no_plan", "too_large", "replace", "tab_id", "plan_digest", "forbidden_level"):
        assert term in tool.description, term
    assert "no_plan" in json.loads(render_client_json())["error_codes"]
    context = next(t for t in UI_TOOLS if t.name == "ui_get_context").description
    for term in ("suggestions_open", "suggestions_accepted", "suggestions_total"):
        assert term in context, term
