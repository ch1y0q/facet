"""Every assistant tool that writes, and every non-read ui_* tool, has an activity-panel label in every bundle."""
import asyncio
import json
from pathlib import Path

import pytest

from api.agent.internal_client import InternalClient
from api.agent.server import MCPServer, _preserve_root_logging, register_all_tools
from api.agent.bridge import TabRegistry
from api.agent.ui_tools import UI_TOOLS

# Reads client, i18n or docs files: runs on every pull request (see ci.yml).
pytestmark = pytest.mark.cross_file

TRANSLATIONS = Path(__file__).resolve().parent.parent / "i18n" / "translations"
LANGS = ("en", "fr", "de", "it", "es", "pt", "zh")


def _bundle(lang):
    return json.loads((TRANSLATIONS / f"{lang}.json").read_text(encoding="utf-8"))["assistant_activity"]


def _write_tool_names():
    """Registered tools whose MCP annotations say read_only_hint is False (the server's own registry)."""
    with _preserve_root_logging():
        scratch = MCPServer("facet-label-keys")
    register_all_tools(scratch, None, InternalClient(None), lambda resolved: {}, TabRegistry())
    tools = asyncio.run(scratch.list_tools())
    return sorted(t.name for t in tools
                  if t.annotations is not None and t.annotations.read_only_hint is False)


def test_write_tool_list_is_derived_and_includes_delete_photos():
    names = _write_tool_names()
    assert "delete_photos" in names and "set_rejected" in names


def test_every_write_tool_has_a_label_in_english():
    tools = _bundle("en")["tools"]
    assert [n for n in _write_tool_names() if n not in tools and not n.startswith("ui_")] == []


def test_every_non_read_ui_tool_has_a_label_in_english():
    ui = _bundle("en")["ui"]
    assert [t.name for t in UI_TOOLS if not t.name.startswith("ui_get_") and t.name not in ui] == []


@pytest.mark.parametrize("lang", LANGS)
def test_no_ui_label_reuses_the_show_photos_button_text(lang):
    bundle = _bundle(lang)
    assert [k for k, v in bundle.get("ui", {}).items() if v == bundle["show_photos"]] == []


@pytest.mark.parametrize("lang", LANGS)
def test_every_bundle_has_the_same_label_keys_as_english(lang):
    en, other = _bundle("en"), _bundle(lang)
    assert set(other.get("tools", {})) == set(en["tools"])
    assert set(other.get("ui", {})) == set(en["ui"])
