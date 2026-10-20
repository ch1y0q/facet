"""Sequence-set and category correction tools over /mcp, over the real routes.

[REAL] ``agent_app`` (real auth chain), the real routes and side tables, rows seeded into the shared
session DB. Nothing on the auth path is mocked.
"""


import pytest

from tests.conftest import AGENT_DIR, agent_db as db

PREFIX = AGENT_DIR + "fix/"
SEQ = [PREFIX + f"s{i}.jpg" for i in range(3)]
SAME_EXPOSURE = [PREFIX + f"e{i}.jpg" for i in range(2)]
SOLO = PREFIX + "solo.jpg"


def frame(path, second, f_stop=4.0, shutter="0.01", iso=100, **extra):
    return {"path": path, "filename": path.rsplit("/", 1)[1], "date_taken": f"1997:03:03 12:00:{second:02d}",
            "aggregate": 6.0, "aesthetic": 6.0, "category": "default", "f_stop": f_stop, "shutter_speed": shutter,
            "iso": iso, **extra}


ROWS = (
    [frame(p, i, shutter=str(0.01 * 2 ** i)) for i, p in enumerate(SEQ)]
    + [frame(p, 10 + i) for i, p in enumerate(SAME_EXPOSURE)] + [frame(SOLO, 20)]
)


def override_row(path):
    rows = db("SELECT sequence_kind, applied_at FROM photo_sequence_overrides WHERE photo_path = ?", path)
    return rows[0] if rows else None


@pytest.fixture()
def world(agent_app, seed_photos_prefix):
    seed_photos_prefix(PREFIX, ROWS)
    env = agent_app("legacy")
    yield env, env.token(env.login(edition=True), "edition")
    db("DELETE FROM photo_sequence_overrides WHERE photo_path LIKE ?", PREFIX + "%")
    db("DELETE FROM photo_scoring_overrides WHERE photo_path LIKE ?", PREFIX + "%")


class TestSequenceOverride:
    def test_override_requires_edition(self, agent_app, seed_photos_prefix):
        seed_photos_prefix(PREFIX, ROWS)
        env = agent_app("multi")
        for level, owner in (("readonly", "root"), ("user", "alice")):
            token = env.token(env.login(owner), level)
            for tool, args in (("override_sequence", {"paths": SEQ, "kind": "panorama"}),
                               ("clear_sequence_override", {"paths": SEQ})):
                assert env.call(token, tool, args)["error"] == "forbidden_level"
            assert not {"override_sequence", "clear_sequence_override"} & env.tool_names(token)
        assert override_row(SEQ[0]) is None
        edition = env.token(env.login("root"), "edition")
        assert {"override_sequence", "clear_sequence_override"} <= env.tool_names(edition)

    def test_override_reports_pending_and_does_not_change_sequence_kind(self, world):
        env, token = world
        result = env.call(token, "override_sequence", {"paths": SEQ, "kind": "panorama"})
        assert result["ok"], result
        data = result["data"]
        assert data["pending"] is True and data["overridden"] == 3 and data["kind"] == "panorama"
        assert "next detection pass" in data["next"]
        assert {s["sequence_override"] for s in data["state"]} == {"panorama"}
        assert {s["sequence_override_pending"] for s in data["state"]} == {1}
        assert db("SELECT sequence_kind FROM photos WHERE path = ?", SEQ[0]) == [(None,)]
        assert override_row(SEQ[0]) == ("panorama", None)

    def test_forced_kinds_need_two_frames_but_suppress_takes_one(self, world):
        env, token = world
        refused = env.call(token, "override_sequence", {"paths": [SOLO], "kind": "bracket"})
        assert refused["error"] == "invalid_input" and "at least 2" in refused["message"]
        assert override_row(SOLO) is None
        assert env.call(token, "override_sequence", {"paths": [SOLO], "kind": "suppress"})["ok"]

    def test_bracket_ladder_gate_error_is_invalid_input_with_message(self, world):
        env, token = world
        result = env.call(token, "override_sequence", {"paths": SAME_EXPOSURE, "kind": "bracket"})
        assert result["error"] == "invalid_input" and result["message"]
        assert override_row(SAME_EXPOSURE[0]) is None

    def test_suppress_maps_to_null_kind(self, world):
        env, token = world
        result = env.call(token, "override_sequence", {"paths": [SOLO], "kind": "suppress"})
        assert result["data"]["state"][0]["sequence_override"] == "suppressed"
        assert override_row(SOLO) == (None, None)

    def test_a_one_frame_forced_kind_is_invalid_input_and_leaves_no_row(self, world):
        env, token = world
        result = env.call(token, "override_sequence", {"paths": [SOLO], "kind": "panorama"})
        assert result["error"] == "invalid_input"
        assert override_row(SOLO) is None

class TestCategoryOverride:
    def test_override_category_requires_edition(self, agent_app, seed_photos_prefix):
        seed_photos_prefix(PREFIX, ROWS)
        env = agent_app("multi")
        token = env.token(env.login("alice"), "user")
        assert env.call(token, "override_category", {"path": SOLO, "category": "portrait"})["error"] == "forbidden_level"
        assert db("SELECT 1 FROM photo_scoring_overrides WHERE photo_path = ?", SOLO) == []

    def test_override_writes_side_table_row(self, world):
        env, token = world
        result = env.call(token, "override_category", {"path": SOLO, "category": "portrait"})
        assert result["ok"], result
        assert result["data"]["new_category"] == "portrait" and "Sticky" in result["data"]["note"]
        assert db("SELECT category_override, source FROM photo_scoring_overrides WHERE photo_path = ?",
                  SOLO) == [("portrait", "manual")]
        assert db("SELECT category FROM photos WHERE path = ?", SOLO) == [("portrait",)]

    def test_unknown_category_is_invalid_input(self, world):
        env, token = world
        result = env.call(token, "override_category", {"path": SOLO, "category": "no_such_category"})
        assert result["error"] == "invalid_input" and "Unknown category" in result["message"]
        assert db("SELECT 1 FROM photo_scoring_overrides WHERE photo_path = ?", SOLO) == []

    def test_clear_preserves_scoring_context(self, world):
        env, token = world
        env.call(token, "override_category", {"path": SOLO, "category": "portrait"})
        db("UPDATE photo_scoring_overrides SET scoring_context = 'travel' WHERE photo_path = ?", SOLO)
        result = env.call(token, "clear_category_override", {"path": SOLO})
        assert result["ok"], result
        assert "Sticky" not in result["data"]["note"] and "decide the category again" in result["data"]["note"]
        assert db("SELECT category_override, scoring_context FROM photo_scoring_overrides WHERE photo_path = ?",
                  SOLO) == [(None, "travel")]

    def test_clearing_without_an_override_is_already(self, world):
        env, token = world
        result = env.call(token, "clear_category_override", {"path": SOLO})
        assert result["data"] == {"path": SOLO, "already": True}

    def test_get_photo_exposes_the_override(self, world):
        env, token = world
        assert env.call(token, "get_photo", {"path": SOLO})["data"].get("category_override") is None
        env.call(token, "override_category", {"path": SOLO, "category": "portrait"})
        assert env.call(token, "get_photo", {"path": SOLO})["data"]["category_override"] == "portrait"
