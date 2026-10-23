"""Scoring tools over /mcp (phase 1: read and preview only), through the real routes.

[REAL] ``agent_app`` (real auth chain), the real critique / comparison routes, rows seeded into the shared
session DB. Nothing on the auth path is mocked.
"""

import json
import pathlib

import pytest

from tests.conftest import AGENT_DIR, agent_db as db

PREFIX = AGENT_DIR + "score/"
METRICS = {"aesthetic": 7.0, "face_quality": 6.0, "eye_sharpness": 6.0, "tech_sharpness": 6.5, "comp_score": 5.5,
           "exposure_score": 8.0, "color_score": 6.0, "contrast_score": 6.0, "quality_score": 6.0,
           "liqe_score": 6.0, "aesthetic_iaa": 6.0, "face_quality_iqa": 6.0, "isolation_bonus": 1.5,
           "face_count": 0, "face_ratio": 0.0, "category": "others", "aggregate": 6.5}


def photo(name, **extra):
    return {"path": PREFIX + name, "filename": name, **METRICS, **extra}


PHOTOS = [photo(f"p{i}.jpg", aesthetic=3.0 + i, aggregate=3.0 + i, comp_score=9.0 - 1.5 * i) for i in range(5)]


@pytest.fixture()
def world(agent_app, seed_photos_prefix):
    seed_photos_prefix(PREFIX, PHOTOS)
    env = agent_app("legacy")
    return env, env.token(env.login(edition=True), "edition"), env.token(env.login(), "readonly")


def config_bytes():
    from api import config as api_config
    path = pathlib.Path(api_config.server_config_path())
    return path.read_bytes() if path.exists() else b""


def snapshots():
    return db("SELECT COUNT(*) FROM weight_config_snapshots")[0][0]


class TestExplainScore:
    def test_breakdown_is_top_n_sorted_with_a_rest_line(self, world):
        env, edition, _ = world
        result = env.call(edition, "explain_score", {"path": PHOTOS[3]["path"], "top_n": 3})
        assert result["ok"], result
        data = result["data"]
        assert data["path"] == PHOTOS[3]["path"] and data["weights"] == "effective"
        items = data["breakdown"]
        assert 0 < len(items) <= 3
        assert all(set(i) == {"metric_key", "value", "weight_percent", "contribution"} for i in items)
        assert [i["contribution"] for i in items] == sorted((i["contribution"] for i in items), reverse=True)
        assert data["rest"]["count"] >= 0
        assert data["stored_aggregate"] == 6.0 and data["category"]

    def test_the_weights_with_the_rest_add_up_to_the_whole(self, world):
        env, edition, _ = world
        everything = env.call(edition, "explain_score", {"path": PHOTOS[1]["path"], "top_n": 12})["data"]
        short = env.call(edition, "explain_score", {"path": PHOTOS[1]["path"], "top_n": 1})["data"]
        assert len(short["breakdown"]) == 1
        assert short["rest"]["count"] == len(everything["breakdown"]) + everything["rest"]["count"] - 1
        total = sum(i["contribution"] for i in everything["breakdown"]) + everything["rest"]["contribution"]
        assert total + (everything["native_adjustment"] or 0) == pytest.approx(everything["current_formula_score"], abs=0.02)
        assert sum(i["weight_percent"] for i in everything["breakdown"]) == pytest.approx(100, abs=3)

    def test_an_unknown_path_is_not_found(self, world):
        env, edition, _ = world
        assert env.call(edition, "explain_score", {"path": PREFIX + "nope.jpg"})["error"] == "not_found"

    def test_exactly_one_of_path_and_target(self, world):
        env, edition, _ = world
        assert env.call(edition, "explain_score", {})["error"] == "invalid_input"
        both = env.call(edition, "explain_score", {"path": PHOTOS[0]["path"], "target": "selection"})
        assert both["error"] == "invalid_input"

    def test_a_readonly_key_may_explain(self, world):
        env, _, readonly = world
        assert "explain_score" in env.tool_names(readonly)
        assert env.call(readonly, "explain_score", {"path": PHOTOS[0]["path"]})["ok"]

    def test_the_route_is_called_in_rule_mode_and_nothing_is_written(self, world, monkeypatch):
        env, edition, _ = world
        seen = []
        from tests.conftest import intercept_internal_call
        intercept_internal_call(monkeypatch, lambda tool, kw: seen.append((tool, kw.get("query"))))
        before = db("SELECT vlm_critique, aggregate FROM photos WHERE path = ?", PHOTOS[0]["path"])
        assert env.call(edition, "explain_score", {"path": PHOTOS[0]["path"]})["ok"]
        assert seen == [("critique", {"path": PHOTOS[0]["path"], "mode": "rule"})]
        assert db("SELECT vlm_critique, aggregate FROM photos WHERE path = ?", PHOTOS[0]["path"]) == before
        assert before[0][0] is None

    def test_switching_the_feature_off_hides_the_tool_and_refuses_a_call(self, world):
        from api import config as api_config
        env, edition, _ = world
        features = api_config.VIEWER_CONFIG.setdefault("features", {})
        was = features.get("show_critique", "unset")
        features["show_critique"] = False
        try:
            assert "explain_score" not in env.tool_names(edition)
            refused = env.call(edition, "explain_score", {"path": PHOTOS[0]["path"]})
            assert refused["error"] == "feature_disabled"
            status = env.call(edition, "status", {})["data"]
            assert "explain_score" in [d["tool"] for d in status["hidden_tools"]["disabled"]]
        finally:
            if was == "unset":
                features.pop("show_critique")
            else:
                features["show_critique"] = was

    def test_a_selection_of_two_is_refused(self, world, fake_tab):
        env, edition, _ = world
        jwt = env.login(edition=True)["Authorization"].split(" ", 1)[1]
        fake_tab(env, jwt, reply=lambda call: {"ok": True, "data": {
            "scope": "paths", "count": 2, "paths": [PHOTOS[0]["path"], PHOTOS[1]["path"]]}})
        refused = env.call(edition, "explain_score", {"target": "selection"})
        assert refused["error"] == "invalid_input" and "exactly one photo" in refused["message"]

    def test_a_selection_of_one_is_explained(self, world, fake_tab):
        env, edition, _ = world
        jwt = env.login(edition=True)["Authorization"].split(" ", 1)[1]
        fake_tab(env, jwt, reply=lambda call: {"ok": True, "data": {
            "scope": "paths", "count": 1, "paths": [PHOTOS[2]["path"]]}})
        result = env.call(edition, "explain_score", {"target": "selection"})
        assert result["ok"] and result["data"]["path"] == PHOTOS[2]["path"]


    @staticmethod
    def view_selection(env, fake_tab, count=1, excluded=()):
        jwt = env.login(edition=True)["Authorization"].split(" ", 1)[1]
        fake_tab(env, jwt, reply=lambda call: {"ok": True, "data": {
            "scope": "view", "count": count, "filters": {"path_prefix": PREFIX},
            "excluded_paths": list(excluded), "excluded_count": len(excluded)}})

    def test_a_whole_view_selection_of_one_is_expanded_and_explained(self, world, fake_tab, monkeypatch):
        from api.agent.internal_client import ok
        from tests.conftest import intercept_internal_call
        env, edition, _ = world
        self.view_selection(env, fake_tab)
        seen = []
        intercept_internal_call(monkeypatch, lambda tool, kw: (
            seen.append((tool, kw.get("query"))), ok({"paths": [PHOTOS[2]["path"]], "total": 1}))[1]
            if tool == "photos_paths" else None)
        result = env.call(edition, "explain_score", {"target": "selection"})
        assert result["ok"] and result["data"]["path"] == PHOTOS[2]["path"], result
        assert seen and seen[0][0] == "photos_paths" and seen[0][1]["path_prefix"] == PREFIX

    def test_a_view_whose_listing_no_longer_matches_the_selection_is_refused(self, world, fake_tab, monkeypatch):
        from api.agent.internal_client import ok
        from tests.conftest import intercept_internal_call
        env, edition, _ = world
        self.view_selection(env, fake_tab)
        intercept_internal_call(monkeypatch, lambda tool, kw: ok({
            "paths": [PHOTOS[0]["path"], PHOTOS[1]["path"]], "total": 2}) if tool == "photos_paths" else None)
        refused = env.call(edition, "explain_score", {"target": "selection"})
        assert refused["error"] == "invalid_input" and "selection_changed" in refused["message"]

    def test_the_excluded_paths_are_taken_out_of_the_expanded_view(self, world, fake_tab, monkeypatch):
        from api.agent.internal_client import ok
        from tests.conftest import intercept_internal_call
        env, edition, _ = world
        self.view_selection(env, fake_tab, count=1, excluded=[PHOTOS[0]["path"]])
        intercept_internal_call(monkeypatch, lambda tool, kw: ok({
            "paths": [PHOTOS[0]["path"], PHOTOS[1]["path"]], "total": 2}) if tool == "photos_paths" else None)
        result = env.call(edition, "explain_score", {"target": "selection"})
        assert result["ok"] and result["data"]["path"] == PHOTOS[1]["path"], result

    def test_an_exclusion_that_leaves_nothing_is_a_changed_selection(self, world, fake_tab, monkeypatch):
        from api.agent.internal_client import ok
        from tests.conftest import intercept_internal_call
        env, edition, _ = world
        self.view_selection(env, fake_tab, count=1, excluded=[PHOTOS[0]["path"]])
        intercept_internal_call(monkeypatch, lambda tool, kw: ok({
            "paths": [PHOTOS[0]["path"]], "total": 2}) if tool == "photos_paths" else None)
        refused = env.call(edition, "explain_score", {"target": "selection"})
        assert refused["error"] == "invalid_input" and "selection_changed" in refused["message"]

    def test_a_failing_listing_is_passed_through(self, world, fake_tab, monkeypatch):
        from api.agent.internal_client import err
        from tests.conftest import intercept_internal_call
        env, edition, _ = world
        self.view_selection(env, fake_tab)
        intercept_internal_call(monkeypatch, lambda tool, kw: err("upstream_error", "listing down")
                                if tool == "photos_paths" else None)
        refused = env.call(edition, "explain_score", {"target": "selection"})
        assert refused["error"] == "upstream_error" and refused["message"] == "listing down"


class TestCategoryWeights:
    def test_one_category_lists_only_non_zero_weights_with_modifiers_filters_priority(self, world):
        env, edition, _ = world
        result = env.call(edition, "category_weights", {"category": "portrait"})
        assert result["ok"], result
        data = result["data"]
        assert data["category"] == "portrait" and data["weights"] and all(data["weights"].values())
        assert all(k.endswith("_percent") for k in data["weights"])
        assert data["weights_sum"] == pytest.approx(sum(data["weights"].values()))
        assert isinstance(data["modifiers"], dict) and isinstance(data["filters"], dict)
        assert isinstance(data["priority"], int) and data["zero_keys_count"] > 0
        assert "aesthetic_percent" in data["valid_keys"] and "bonus_percent" not in data["valid_keys"]
        assert data["configured_keys"] and set(data["weights"]) <= set(data["configured_keys"])
        assert all(k.endswith("_percent") for k in data["configured_keys"])
        assert data["configured_keys"] == sorted(data["configured_keys"])

    def test_configured_keys_come_from_the_resolved_config_not_the_padded_vector(self, world):
        env, edition, _ = world
        data = env.call(edition, "category_weights", {"category": "portrait"})["data"]
        from api.config import server_scoring_config
        written = next(c for c in server_scoring_config().get_categories() if c["name"] == "portrait")["weights"]
        assert data["configured_keys"] == sorted(k for k in written if k.endswith("_percent"))
        assert set(data["configured_keys"]) <= set(data["valid_keys"])

    def test_without_a_category_every_category_is_listed(self, world):
        env, edition, _ = world
        data = env.call(edition, "category_weights", {})["data"]
        names = [c["name"] for c in data["categories"]]
        assert "portrait" in names and len(names) == len(set(names))
        assert all(all(c["weights"].values()) for c in data["categories"])

    def test_an_unknown_category_is_not_found(self, world):
        env, edition, _ = world
        assert env.call(edition, "category_weights", {"category": "zzz-nope"})["error"] == "not_found"

    def test_readonly_neither_sees_nor_calls_it_and_the_status_counts_it(self, world):
        env, _, readonly = world
        assert not {"category_weights", "preview_weights"} & env.tool_names(readonly)
        assert env.call(readonly, "category_weights", {})["error"] == "forbidden_level"
        assert env.call(readonly, "preview_weights", {"category": "portrait", "weights": {"aesthetic": 1}}
                        )["error"] == "forbidden_level"
        hidden = env.call(readonly, "status", {})["data"]["hidden_tools"]
        assert hidden["needs"] == "edition" and hidden["count"] >= 2

    def test_reading_changes_nothing(self, world):
        env, edition, _ = world
        before = config_bytes(), snapshots()
        env.call(edition, "category_weights", {"category": "portrait"})
        env.call(edition, "category_weights", {})
        assert (config_bytes(), snapshots()) == before

    def test_the_resource_carries_the_same_non_zero_weights(self, world):
        env, edition, readonly = world
        listed = {r["uri"] for r in env.rpc(edition, "resources/list").json()["result"]["resources"]}
        assert "facet://scoring-weights" in listed
        assert "facet://scoring-weights" not in {
            r["uri"] for r in env.rpc(readonly, "resources/list").json()["result"]["resources"]}
        read = env.rpc(edition, "resources/read", {"uri": "facet://scoring-weights"}).json()
        data = json.loads(read["result"]["contents"][0]["text"])["data"]
        tool = env.call(edition, "category_weights", {})["data"]
        assert data == tool

    def test_a_readonly_key_that_knows_the_uri_cannot_read_it(self, world):
        env, edition, readonly = world
        refused = env.rpc(readonly, "resources/read", {"uri": "facet://scoring-weights"}).json()
        assert refused["error"]["code"] == -32602 and "result" not in refused
        assert "result" in env.rpc(edition, "resources/read", {"uri": "facet://scoring-weights"}).json()
        for uri in ("facet://categories", "facet://scoring-contexts"):
            assert "result" in env.rpc(readonly, "resources/read", {"uri": uri}).json(), uri


def native_category(env, token):
    """The category the real scorer files the seeded photos under, and the photos re-filed under it."""
    category = env.call(token, "explain_score", {"path": PHOTOS[0]["path"]})["data"]["category"]
    db("UPDATE photos SET category = ? WHERE path LIKE ?", category, PREFIX + "%")
    return category


def real_scores(category, vector):
    """The aggregates the REAL scorer (Facet.calculate_aggregate_logic) gives the seeded rows under ``vector``."""
    import sqlite3
    from api.config import server_scoring_config
    from processing.scorer import Facet, SERVED_ROW_COLUMNS
    from tests.conftest import _TEST_DB_FILE
    cfg = server_scoring_config()
    for entry in cfg.config["categories"]:
        if entry["name"] == category:
            entry["weights"] = dict(vector)
    scorer = Facet.__new__(Facet)
    scorer.config = cfg
    scores = {}
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.row_factory = sqlite3.Row
        columns = ", ".join(dict.fromkeys((*SERVED_ROW_COLUMNS, "category", "aggregate")))
        for row in conn.execute(f"SELECT {columns} FROM photos WHERE path LIKE ?", (PREFIX + "%",)):
            prepared = Facet.prepare_scoring_row(dict(row), cfg, None, category)
            scores[prepared["path"]] = scorer.calculate_aggregate_logic(prepared)[0]
    return scores


def ranks(scores):
    ordered = sorted(scores, key=lambda p: (-round(scores[p], 2), p))
    return {p: i for i, p in enumerate(ordered, start=1)}


class TestPreviewWeights:
    def test_a_proposal_with_every_weight_at_zero_is_refused(self, world):
        env, edition, _ = world
        category = native_category(env, edition)
        zero = {k: 0 for k in self.current(env, edition, category)}
        result = env.call(edition, "preview_weights", {"category": category, "weights": zero, "sample": 5})
        assert result["ok"] is False and result["error"] == "invalid_input" and "all_weights_zero" in result["message"]
        assert "preview_digest" not in str(result)

    def test_the_basis_note_says_the_preview_uses_stored_metrics_only(self, world):
        env, edition, _ = world
        category = native_category(env, edition)
        data = env.call(edition, "preview_weights", {"category": category, "deltas": {"aesthetic": -1}, "sample": 5})["data"]
        assert "stored metrics only" in data["basis_note"]

    def current(self, env, token, category):
        return env.call(token, "category_weights", {"category": category})["data"]["weights"]

    def test_the_rank_shifts_match_the_real_scorer(self, world):
        env, edition, _ = world
        category = native_category(env, edition)
        current = self.current(env, edition, category)
        assert current["aesthetic_percent"] >= 15
        result = env.call(edition, "preview_weights", {
            "category": category, "deltas": {"aesthetic": -15, "composition": 15}, "sample": 5})
        assert result["ok"], result
        data = result["data"]
        proposed = {**current, "aesthetic_percent": current["aesthetic_percent"] - 15,
                    "composition_percent": current.get("composition_percent", 0) + 15}
        before, after = real_scores(category, current), real_scores(category, proposed)
        old, new = ranks(before), ranks(after)
        moved = {p: old[p] - new[p] for p in old}
        assert data["sampled"] == 5 and data["basis"] == "approximate" and data["basis_note"]
        changes = data["rank_changes"]
        assert changes["moved_up"] == sum(1 for d in moved.values() if d > 0) > 0
        assert changes["moved_down"] == sum(1 for d in moved.values() if d < 0)
        assert all(moved[b["path"]] == b["delta"] and b["from_rank"] == old[b["path"]] for b in changes["biggest"])
        assert changes["biggest"] and len(changes["biggest"]) == min(5, sum(1 for d in moved.values() if d))
        real_mean = sum(after[p] - before[p] for p in before) / len(before)
        assert data["mean_shift"] == pytest.approx(real_mean, abs=0.35)
        assert "capped at 10" in data["clamp_note"]

    def test_a_partial_proposal_equals_the_same_full_vector(self, world):
        env, edition, _ = world
        category = native_category(env, edition)
        current = self.current(env, edition, category)
        partial = {"aesthetic": current["aesthetic_percent"] - 10, "composition": current.get("composition_percent", 0) + 10}
        full = {**current, "aesthetic_percent": partial["aesthetic"], "composition_percent": partial["composition"]}
        one = env.call(edition, "preview_weights", {"category": category, "weights": partial, "sample": 5})["data"]
        two = env.call(edition, "preview_weights", {"category": category, "weights": full, "sample": 5})["data"]
        for key in ("mean_shift", "median_shift", "max_up", "max_down", "rank_changes", "proposal"):
            assert one[key] == two[key], key
        assert one["preview_digest"] and two["preview_digest"] and one["preview_digest"] != two["preview_digest"]

    def test_a_proposal_summing_to_80_or_120_is_scored_like_its_rescaled_vector(self, world):
        env, edition, _ = world
        category = native_category(env, edition)
        current = self.current(env, edition, category)
        bumped = {**current, "aesthetic_percent": current["aesthetic_percent"] - 10,
                  "composition_percent": current.get("composition_percent", 0) + 10}
        base = env.call(edition, "preview_weights", {"category": category, "weights": bumped, "sample": 5})["data"]
        for factor in (0.8, 1.2):
            scaled = {k: v * factor for k, v in bumped.items()}
            assert all(v <= 100 for v in scaled.values()), (factor, scaled)
            data = env.call(edition, "preview_weights", {"category": category, "weights": scaled, "sample": 5})["data"]
            assert [w["code"] for w in data["warnings"]] == ["sum_outside_95_105"], factor
            for key in ("mean_shift", "median_shift", "rank_changes"):
                assert data[key] == base[key], (factor, key)

    def test_nothing_is_written_and_each_preview_gets_its_own_digest(self, world):
        env, edition, _ = world
        category = native_category(env, edition)
        before = config_bytes(), snapshots(), db("SELECT COUNT(*) FROM comparisons")
        first = env.call(edition, "preview_weights", {"category": category, "deltas": {"aesthetic": -1}})["data"]
        second = env.call(edition, "preview_weights", {"category": category, "deltas": {"aesthetic": -2}})["data"]
        assert first["preview_digest"] and second["preview_digest"] != first["preview_digest"]
        assert first["preview_digest_expires_in_s"] == 300
        assert (config_bytes(), snapshots(), db("SELECT COUNT(*) FROM comparisons")) == before
        from api.agent import nonce
        assert sum(1 for v in nonce._pending.values() if v[1] == "apply_weights") == 2

    def test_bonus_and_bad_values_are_refused_with_every_issue(self, world):
        env, edition, _ = world
        category = native_category(env, edition)
        refused = env.call(edition, "preview_weights", {
            "category": category, "weights": {"bonus": 1, "aesthetic": 500, "composition": -3}})
        assert refused["error"] == "invalid_input" and len(refused["issues"]) == 3
        assert "not editable" in refused["message"]
        assert env.call(edition, "preview_weights", {"category": category})["error"] == "invalid_input"
        both = env.call(edition, "preview_weights", {"category": category, "weights": {"aesthetic": 1},
                                                     "deltas": {"aesthetic": 1}})
        assert both["error"] == "invalid_input"

    def test_an_unknown_key_and_an_odd_sum_are_warned_not_refused(self, world):
        env, edition, _ = world
        category = native_category(env, edition)
        result = env.call(edition, "preview_weights", {
            "category": category, "weights": {"aestethic": 3, "aesthetic": 100, "composition": 100}})
        assert result["ok"], result
        codes = [w["code"] for w in result["data"]["warnings"]]
        assert codes.count("unknown_key") == 1 and codes.count("sum_outside_95_105") == 1

    def test_an_unknown_category_is_not_found(self, world):
        env, edition, _ = world
        assert env.call(edition, "preview_weights", {"category": "zzz-nope", "weights": {"aesthetic": 1}}
                        )["error"] == "not_found"

    def test_a_readonly_token_is_refused_before_any_route_call(self, world, monkeypatch):
        from tests.conftest import intercept_internal_call
        env, _, readonly = world
        calls = []
        intercept_internal_call(monkeypatch, lambda tool, kw: calls.append(tool))
        refused = env.call(readonly, "preview_weights", {"category": "portrait", "weights": {"aesthetic": 1}})
        assert refused["error"] == "forbidden_level" and calls == []

    def test_a_token_keeps_at_most_16_live_digests_the_oldest_makes_room(self, world):
        from api.agent import nonce
        env, edition, _ = world
        category = native_category(env, edition)
        answers = [env.call(edition, "preview_weights", {"category": category, "deltas": {"aesthetic": -i - 1}})
                   for i in range(17)]
        assert all(a["ok"] for a in answers)
        live = {v for v in (a["data"]["preview_digest"] for a in answers) if v in nonce._pending}
        assert len(live) == 16 and answers[0]["data"]["preview_digest"] not in live

    def test_a_full_nonce_table_answers_rate_limited_like_every_other_confirm_tool(self, world, monkeypatch):
        from api.agent import nonce
        env, edition, _ = world
        category = native_category(env, edition)
        nonce.issue("someone-else", "apply_weights", "x")
        monkeypatch.setattr(nonce, "MAX_PENDING", 1)
        full = env.call(edition, "preview_weights", {"category": category, "deltas": {"aesthetic": -1}})
        assert full["error"] == "rate_limited" and full["retry_after_s"] == int(nonce.TTL_SECONDS)


class TestDocs:
    LANGS = ["", "fr", "de", "it", "es", "pt", "zh"]
    DOCS = pathlib.Path(__file__).resolve().parent.parent / "docs"

    @pytest.mark.parametrize("lang", LANGS)
    def test_every_language_names_every_phase_one_tool_and_the_resource(self, lang):
        text = (self.DOCS / lang / "AGENTS.md").read_text(encoding="utf-8")
        for name in ("explain_score", "category_weights", "preview_weights", "facet://scoring-weights",
                     "preview_digest", "show_critique"):
            assert name in text, (lang, name)

    def test_the_seven_agents_docs_carry_the_same_number_of_table_rows(self):
        rows = {lang: sum(1 for line in (self.DOCS / lang / "AGENTS.md").read_text(encoding="utf-8").splitlines()
                          if line.startswith("|")) for lang in self.LANGS}
        assert len(set(rows.values())) == 1, rows
