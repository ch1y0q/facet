"""Read tools: date forms and the ``basis`` of ``library_stats`` (over /mcp, real routes)."""

import pytest


def stats(env, token, **args):
    return env.call(token, "library_stats", args)


def test_overview_basis_sits_inside_overview_and_top_level_keys_are_unchanged(agent_app):
    env = agent_app("open")
    data = stats(env, env.token(env.login()))["data"]
    assert set(data) == {"type_counts", "overview"}
    basis = data["overview"]["basis"]
    assert "hide toggles ignored" in basis["total_photos"] and "rejected" in basis["total_photos"]
    assert "hide toggles applied" in basis["type_counts"] and "ignored" in basis["type_counts"]


@pytest.mark.parametrize("kind", ["overview", "timeline_years", "top_cameras"])
def test_iso_and_exif_days_are_accepted_by_stats(agent_app, kind):
    env = agent_app("open")
    token = env.token(env.login())
    for given in ("2020-01-01", "2020:01:01"):
        assert stats(env, token, kind=kind, date_from=given, date_to=given)["ok"] is True


@pytest.mark.parametrize("kind", ["overview", "timeline_years"])
def test_stats_refuse_a_time_of_day_naming_the_form(agent_app, kind):
    env = agent_app("open")
    result = stats(env, env.token(env.login()), kind=kind, date_from="2020-01-01 10:00:00")
    assert result["ok"] is False and result["error"] == "invalid_input"
    assert "YYYY-MM-DD" in result["message"]


def test_possible_faces_refuses_a_time_and_a_non_date(agent_app):
    env = agent_app("open")
    token = env.token(env.login())
    for bad in ("2020-01-01T10:00:00", "soon"):
        result = env.call(token, "possible_faces", {"person_id": 1, "date_from": bad, "show": False})
        assert result["error"] == "invalid_input" and "YYYY-MM-DD" in result["message"], result
