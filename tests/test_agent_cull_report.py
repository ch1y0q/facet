"""``cull_report``: one bounded summary of a scope, built from the existing count/search routes.

[REAL] ``agent_app`` (real auth chain), real routes, rows seeded into the shared session DB under a
unique path prefix so every number is exact.
"""

import json

import pytest

from tests.conftest import AGENT_DIR

PREFIX = AGENT_DIR + "report/"
SCOPE = {"path_prefix": PREFIX}


def row(name, **cols):
    return {"path": PREFIX + name, "filename": name, "date_taken": "1996:06:06 10:00:00", "aggregate": 6.0,
            "aesthetic": 6.0, "star_rating": 0, **cols}


ROWS = [
    row("a.jpg", aggregate=9.0, star_rating=5),
    row("b.jpg", aggregate=8.0, is_favorite=1),
    row("c.jpg", aggregate=7.0),
    row("d.jpg", is_rejected=1),
    row("e.jpg", is_blink=1),
    row("f.jpg", burst_group_id=7001, is_burst_lead=1),
    row("g.jpg", burst_group_id=7001, is_burst_lead=0),
    row("h.jpg", aggregate=2.0, junk_kind="screenshot"),
]


@pytest.fixture()
def world(agent_app, seed_photos_prefix):
    seed_photos_prefix(PREFIX, ROWS)
    env = agent_app("legacy")
    yield env, env.token(env.login(), "readonly"), env.token(env.login(edition=True), "edition")


def report(env, token, **args):
    return env.call(token, "cull_report", {"filters": SCOPE, **args})


def test_counts_match_the_search_totals(world):
    env, token, _ = world
    data = report(env, token)["data"]
    assert data["total"] == 8 and data["rejected"] == 1 and data["kept"] == 7 and data["favorites"] == 1
    assert data["rated"] == 1
    unhidden = env.call(token, "search_photos", {"filters": {**SCOPE, "hide_bursts": False, "hide_blinks": False,
                                                              "hide_duplicates": False, "hide_rejected": False},
                                                 "show": False})
    assert unhidden["data"]["total"] == data["total"]
    default = env.call(token, "search_photos", {"filters": SCOPE, "show": False})
    reasons = data["reasons"]
    assert default["data"]["total"] == data["kept"] - reasons["blinks"] - reasons["burst_non_best"] == 5


def test_hidden_members_are_counted_per_reason(world):
    env, token, _ = world
    reasons = report(env, token)["data"]["reasons"]
    assert reasons["blinks"] == 1 and reasons["burst_non_best"] == 1
    assert reasons["junk"] == 1 and reasons["low_score"] == 1
    assert reasons["duplicates_hidden"] == 0 and reasons["brackets_hidden"] == 0


def test_unreviewed_is_kept_without_rating_or_favorite(world):
    env, token, _ = world
    data = report(env, token)["data"]
    assert data["unreviewed"] == 5


def test_top_keepers_are_best_first_and_trimmed_to_four_keys(world):
    env, token, _ = world
    data = report(env, token, top_n=2)["data"]
    assert [k["filename"] for k in data["top_keepers"]] == ["a.jpg", "b.jpg"]
    assert set(data["top_keepers"][0]) == {"path", "filename", "aggregate", "star_rating"}


def test_hide_toggles_in_the_filters_are_ignored(world):
    env, token, _ = world
    first = report(env, token)["data"]["total"]
    forced = env.call(token, "cull_report", {"filters": {**SCOPE, "hide_bursts": 1, "hide_rejected": 1}})
    assert forced["data"]["total"] == first == 8


def test_sets_are_edition_only(world):
    env, readonly, edition = world
    low = report(env, readonly)["data"]
    assert low["sets"] is None and low["sets_note"] == "needs an edition token"
    high = report(env, edition)["data"]
    assert isinstance(high["sets"], list) and "sets_note" not in high


def test_selection_target_is_refused_with_invalid_input(world):
    env, token, _ = world
    refused = report(env, token, target="selection")
    assert refused["error"] == "invalid_input" and "filters" in refused["message"]


def test_report_stays_under_the_byte_bound(world):
    env, token, _ = world
    assert len(json.dumps(report(env, token, top_n=10)["data"]).encode()) < 6000


def test_a_failed_count_is_null_and_listed_as_unavailable(world, monkeypatch):
    env, token, _ = world
    from api.agent import tools_report
    real = tools_report._count

    async def flaky(client, grant, timeout, gate, query):
        return None if query.get("junk_kind") else await real(client, grant, timeout, gate, query)

    monkeypatch.setattr(tools_report, "_count", flaky)
    data = report(env, token)["data"]
    assert data["unavailable"] == ["junk"] and data["reasons"]["junk"] is None and data["total"] == 8


def test_multi_user_counts_only_the_owners_library(agent_app, seed_photos_prefix):
    seed_photos_prefix(PREFIX, ROWS)
    env = agent_app("multi")
    alice = env.token(env.login("alice"), "readonly")
    bob = env.token(env.login("bob"), "readonly")
    assert report(env, alice)["data"]["total"] == 8
    assert report(env, bob)["data"]["total"] == 0


def test_readonly_token_sees_the_tool(world):
    env, token, _ = world
    assert "cull_report" in env.tool_names(token)
