"""The pure helpers behind explain_score / category_weights / preview_weights, and the shared normaliser.

[REAL] no I/O: plain functions over dicts.
"""

import math

import pytest

from api.agent import weights
from config.scoring_config import ScoringConfig, normalise_percent_weights

CURRENT = {"aesthetic_percent": 40, "composition_percent": 30, "exposure_percent": 30}


class TestNormalisePercentWeights:
    def test_get_weights_is_the_helper_plus_modifiers(self):
        cfg = ScoringConfig.__new__(ScoringConfig)
        raw = {"aesthetic_percent": 50, "composition_percent": 25, "exposure_percent": 15}
        cfg.config = {"categories": [{"name": "x", "weights": raw, "modifiers": {"bonus": 0.5}}]}
        assert cfg.get_weights("x") == {**normalise_percent_weights(raw), "bonus": 0.5}

    def test_a_sum_other_than_one_is_divided_out(self):
        out = normalise_percent_weights({"aesthetic_percent": 80, "composition_percent": 40})
        assert out == {"aesthetic": pytest.approx(2 / 3), "composition": pytest.approx(1 / 3)}

    def test_a_sum_within_a_thousandth_of_one_is_left_alone(self):
        out = normalise_percent_weights({"aesthetic_percent": 60.04, "composition_percent": 40})
        assert out == {"aesthetic": pytest.approx(0.6004), "composition": pytest.approx(0.4)}

    def test_an_all_zero_vector_stays_zero(self):
        assert normalise_percent_weights({"aesthetic_percent": 0}) == {"aesthetic": 0}


class TestResultingVector:
    def test_partial_weights_merge_over_the_current_vector(self):
        issues, vector = weights.resulting_vector(CURRENT, {"aesthetic": 50}, None)
        assert not issues
        assert vector == {"aesthetic_percent": 50, "composition_percent": 30, "exposure_percent": 30}

    def test_percent_suffix_and_bare_key_are_the_same_key(self):
        _, a = weights.resulting_vector(CURRENT, {"aesthetic_percent": 55}, None)
        _, b = weights.resulting_vector(CURRENT, {"aesthetic": 55}, None)
        assert a == b

    def test_deltas_are_added_to_the_current_value(self):
        _, vector = weights.resulting_vector(CURRENT, None, {"aesthetic": 5, "composition_percent": -10})
        assert vector["aesthetic_percent"] == 45 and vector["composition_percent"] == 20

    def test_deltas_on_an_unset_key_start_from_zero(self):
        _, vector = weights.resulting_vector(CURRENT, None, {"liqe": 5})
        assert vector["liqe_percent"] == 5

    def test_both_or_neither_is_refused(self):
        assert weights.resulting_vector(CURRENT, {"aesthetic": 1}, {"aesthetic": 1})[0]
        assert weights.resulting_vector(CURRENT, None, None)[0]
        assert weights.resulting_vector(CURRENT, {}, None)[0]

    @pytest.mark.parametrize("proposal", [{"aesthetic": -1}, {"aesthetic": 101}, {"aesthetic": "x"},
                                          {"aesthetic": math.nan}])
    def test_the_servers_rule_numeric_0_to_100(self, proposal):
        assert weights.resulting_vector(CURRENT, proposal, None)[0]

    def test_a_delta_pushing_a_key_below_zero_is_refused(self):
        issues, _ = weights.resulting_vector(CURRENT, None, {"aesthetic": -41})
        assert issues and "aesthetic" in issues[0]

    def test_bonus_and_modifier_keys_are_refused(self):
        for key in ("bonus", "bonus_percent", "noise_tolerance_multiplier"):
            issues, _ = weights.resulting_vector(CURRENT, {key: 1}, None)
            assert issues and "not editable" in issues[0], key

    def test_every_issue_is_listed(self):
        issues, _ = weights.resulting_vector(CURRENT, {"aesthetic": -1, "composition": 500, "bonus": 1}, None)
        assert len(issues) == 3

    def test_no_change_is_refused(self):
        issues, _ = weights.resulting_vector(CURRENT, {"aesthetic": 40}, None)
        assert issues == ["no change: the proposal equals the current weights"]


class TestWarnings:
    def test_a_sum_of_99_or_101_is_accepted_without_a_warning(self):
        for total in (95, 99, 101, 105):
            assert not weights.warnings_for({"aesthetic_percent": total})

    def test_a_sum_outside_95_105_warns(self):
        assert [w["code"] for w in weights.warnings_for({"aesthetic_percent": 80})] == ["sum_outside_95_105"]

    def test_an_unknown_key_warns_and_is_not_refused(self):
        issues, vector = weights.resulting_vector(CURRENT, {"aestethic": 5}, None)
        assert not issues and vector["aestethic_percent"] == 5
        assert [w["code"] for w in weights.warnings_for(vector)] == ["unknown_key"]


class TestRouteVectors:
    def test_the_route_vector_is_the_normalised_percent_of_every_key(self):
        sent = weights.route_vector({"aesthetic_percent": 80, "composition_percent": 40})
        assert sent == {"aesthetic": pytest.approx(200 / 3), "composition": pytest.approx(100 / 3)}

    def test_a_key_absent_from_the_other_vector_is_sent_as_zero(self):
        first, second = weights.route_vectors({"aesthetic_percent": 100}, {"composition_percent": 100})
        assert first == {"aesthetic": 100, "composition": 0} and second == {"aesthetic": 0, "composition": 100}


class TestRankChanges:
    def test_ranks_are_by_score_desc_with_ties_in_path_order(self):
        before = {"a": 5.0, "b": 7.0, "c": 7.0}
        after = {"a": 9.0, "b": 7.0, "c": 6.0}
        out = weights.rank_changes(before, after)
        assert out["moved_up"] == 1 and out["moved_down"] == 2 and out["unchanged"] == 0
        assert out["biggest"][0] == {"path": "a", "from_rank": 3, "to_rank": 1, "delta": 2}

    def test_biggest_is_capped_at_five(self):
        before = {str(i): float(i) for i in range(20)}
        after = {str(i): float(-i) for i in range(20)}
        assert len(weights.rank_changes(before, after)["biggest"]) == 5

    def test_evenly_spaced_covers_the_whole_range(self):
        assert weights.evenly_spaced(list(range(100)), 5) == [0, 20, 40, 60, 80]
        assert weights.evenly_spaced(list(range(3)), 30) == [0, 1, 2]
