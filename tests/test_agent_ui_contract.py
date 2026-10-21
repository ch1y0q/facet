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


def test_ui_show_photos_path_bound_is_in_the_contract_and_enforced():
    from api.agent.ui_tools import UiShowPhotos
    items = UiShowPhotos.model_json_schema()["properties"]["paths"]["items"]
    assert items["minLength"] == 1 and items["maxLength"] == 4096
    with pytest.raises(ValueError):
        UiShowPhotos(paths=["x" * 4097])
    with pytest.raises(ValueError):
        UiShowPhotos(paths=[""])


def test_ui_show_photos_groups_and_marks_must_match_paths_length():
    from api.agent.ui_tools import UiShowPhotos
    with pytest.raises(ValueError, match="`groups` must have exactly one entry per path"):
        UiShowPhotos(paths=["a", "b"], groups=[1])
    with pytest.raises(ValueError, match="`marks` must have exactly one entry per path"):
        UiShowPhotos(paths=["a", "b"], marks=["keep"])
    with pytest.raises(ValueError):
        UiShowPhotos(paths=["a"], marks=["maybe"])
    with pytest.raises(ValueError):
        UiShowPhotos(paths=["a"], groups=[0])
    ok = UiShowPhotos(paths=["a", "b"], groups=[1, 1], marks=["keep", "remove"])
    assert ok.forward() == {"paths": ["a", "b"], "groups": [1, 1], "marks": ["keep", "remove"]}
    assert UiShowPhotos(paths=["a"]).forward() == {"paths": ["a"]}


def test_ui_show_photos_schema_has_plain_groups_and_marks_arrays():
    from api.agent.ui_tools import UI_TOOLS, input_schema
    schema = input_schema(next(t for t in UI_TOOLS if t.name == "ui_show_photos"))
    text = json.dumps(schema)
    assert "$ref" not in text and "anyOf" not in text
    assert schema["additionalProperties"] is False
    assert schema["properties"]["groups"]["type"] == "array"
    assert schema["properties"]["marks"]["items"]["enum"] == ["keep", "remove"]


def test_show_photos_contract_describes_group_sections_not_a_pill():
    from api.agent import show
    from api.agent.ui_tools import UiShowPhotos
    descriptions = [t.description for t in UI_TOOLS] + [
        field.description or "" for field in UiShowPhotos.model_fields.values()] + [show.show_paths_in_tab.__doc__ or ""]
    assert not any("pill" in text or "Group n" in text for text in descriptions)
    show_tool = next(t for t in UI_TOOLS if t.name == "ui_show_photos").description
    assert "section" in show_tool and "keep/remove" in show_tool
    assert "section" in (UiShowPhotos.model_fields["groups"].description or "")


def test_tools_version_moved_with_the_review_rendering():
    # The version before the group pill became section headers + a per-card keep/remove strip.
    assert tools_version() != "abffbeeba56ed5b5"
