"""Agent-originated writes never train the taste model; the same writes by a person still do.

[REAL] ``agent_app`` (real auth chain), real routes, seeded burst rows. The two recording sinks are
observed, not mocked away: ``comparisons`` rows are counted, and the ranker nudge
(``db_helpers.trigger_auto_retrain``) and the rating-sync scheduler (``_mint_rating_comparisons``) are
wrapped by recorders that still call through.
"""

import sqlite3

import pytest

from api import db_helpers
from api.routers import faces
from tests.conftest import _TEST_DB_FILE, AGENT_DIR

PREFIX = AGENT_DIR + "taste/"
ROWS = [{"path": PREFIX + f"t{i}.jpg", "filename": f"t{i}.jpg", "date_taken": f"1998:01:01 10:00:{i:02d}",
         "aggregate": 9.0 - 3 * i, "aesthetic": 9.0 - 3 * i, "tech_sharpness": 9.0 - 3 * i,
         "burst_group_id": 5151, "is_burst_lead": 1 if i == 0 else 0, "star_rating": 0}
        for i in range(3)]
PATHS = [row["path"] for row in ROWS]
GROUP = {"type": "burst", "group_id": 5151, "paths": PATHS, "keep_paths": PATHS[:1]}


def comparisons() -> int:
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        return conn.execute("SELECT COUNT(*) FROM comparisons WHERE photo_a_path LIKE ? OR photo_b_path LIKE ?",
                            (PREFIX + "%", PREFIX + "%")).fetchone()[0]


@pytest.fixture()
def world(agent_app, seed_photos_prefix, monkeypatch):
    seed_photos_prefix(PREFIX, ROWS)
    nudges, mints = [], []
    real_nudge, real_mint = db_helpers.trigger_auto_retrain, faces._mint_rating_comparisons
    monkeypatch.setattr(db_helpers, "trigger_auto_retrain",
                        lambda *a, **k: (nudges.append(a), real_nudge(*a, **k))[1])
    monkeypatch.setattr(faces, "_mint_rating_comparisons", lambda *a, **k: (mints.append(a), real_mint(*a, **k))[1])
    env = agent_app("legacy")
    yield env, env.token(env.login(edition=True), "edition"), nudges, mints
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.execute("DELETE FROM comparisons WHERE photo_a_path LIKE ? OR photo_b_path LIKE ?",
                     (PREFIX + "%", PREFIX + "%"))


def test_confirm_culling_groups_via_mcp_adds_zero_comparisons_and_does_not_arm_retrain(world):
    env, token, nudges, _ = world
    before = comparisons()
    result = env.call(token, "confirm_culling_groups", {"groups": [GROUP]})
    assert result["ok"] and result["data"]["rows"][0]["rejected"] == 2, result
    assert comparisons() == before and nudges == []


def test_ui_confirm_still_records_comparisons(world):
    env, _, nudges, _ = world
    before = comparisons()
    resp = env.client.post("/api/culling-groups/confirm", json=GROUP, headers=env.login(edition=True))
    assert resp.status_code == 200, resp.text
    assert comparisons() > before and nudges


def test_mcp_set_rating_set_rejected_mint_no_comparisons(world):
    env, token, nudges, mints = world
    assert env.call(token, "set_rating", {"paths": PATHS[:1], "rating": 5})["data"]["affected"] == 1
    assert env.call(token, "set_favorite", {"paths": PATHS[1:2], "value": True})["data"]["affected"] == 1
    assert env.call(token, "set_rejected", {"paths": PATHS[2:], "value": True})["data"]["affected"] == 1
    assert mints == [] and nudges == []
    resp = env.client.post("/api/photo/set_rating", json={"photo_path": PATHS[0], "rating": 4},
                           headers=env.login(edition=True))
    assert resp.status_code == 200 and len(mints) == 1


def test_auto_cull_apply_via_mcp_records_nothing(world):
    env, token, nudges, _ = world
    scope = {"group_by": "burst", "date_from": "1998:01:01 00:00:00", "date_to": "1998:01:01 23:59:59",
             "strictness": 0}
    preview = env.call(token, "auto_cull", scope)
    assert preview["ok"] and preview["data"]["rejected"], preview
    before = comparisons()
    done = env.call(token, "auto_cull", {**scope, "dry_run": False, "confirm": preview["confirm"]})
    assert done["ok"], done
    assert comparisons() == before and nudges == []
