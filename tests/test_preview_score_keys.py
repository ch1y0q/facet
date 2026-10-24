"""``POST /api/comparison/preview_score`` must react to EVERY valid weight key, not only 19 of the 31.

[REAL] real route over the shared session DB; only the auth dependency of the client fixture is overridden.
"""

import pytest

from config.category_filter import VALID_WEIGHT_COLUMNS

PATH = "/preview-score-keys/p.jpg"
# Each valid weight key -> the stored column the scorer reads for it (processing.scorer.build_metric_vector).
COLUMN = {
    "aesthetic": "aesthetic", "face_quality": "face_quality", "face_sharpness": "face_sharpness",
    "eye_sharpness": "eye_sharpness", "tech_sharpness": "tech_sharpness", "composition": "comp_score",
    "power_point": "power_point_score", "leading_lines": "leading_lines_score", "exposure": "exposure_score",
    "color": "color_score", "contrast": "contrast_score", "quality": "quality_score",
    "dynamic_range": "histogram_spread", "saturation": "mean_saturation", "noise": "noise_sigma",
    "isolation": "isolation_bonus", "aesthetic_iaa": "aesthetic_iaa", "face_quality_iqa": "face_quality_iqa",
    "liqe": "liqe_score", "qrealign": "qrealign_score", "aesthetic_v25": "aesthetic_v25", "deqa": "deqa_score",
    "subject_sharpness": "subject_sharpness", "subject_prominence": "subject_prominence",
    "subject_placement": "subject_placement", "bg_separation": "bg_separation", "symmetry": "form_symmetry",
    "balance": "form_balance", "edge_entropy": "form_edge_entropy", "fractal": "form_fractal",
    "color_harmony": "color_harmony",
}
# Seeded stored values; every other column holds 6.0.
VALUE = {"mean_saturation": 0.6, "noise_sigma": 2.0, "isolation_bonus": 2.0, "histogram_spread": 30.0}
# What one key alone scores at weight 100, worked out by hand from build_metric_vector (not by calling it):
#   saturation 0.6 * 10 = 6.0; noise 10 - 2.0 * 0.7 = 8.6; isolation (2.0 - 1) * 5 = 5.0;
#   dynamic range 30 / 6 = 5.0 (histogram_spread, NOT dynamic_range_stops, which is seeded 6.0 and would give 10);
#   composition 6.0 + blend 0.30 * min(10, leading_lines_score 6.0 * 1.77) = 9.0; leading_lines min(10, 10.62) = 10;
#   quality is folded into aesthetic (6.0); an extended-IQA key is 6.0 only while the install enables it.
EXPECTED = {key: 6.0 for key in COLUMN}
EXPECTED.update({"saturation": 6.0, "noise": 8.6, "isolation": 5.0, "dynamic_range": 5.0,
                 "composition": 9.0, "leading_lines": 10.0})
EXTENDED = ("qrealign", "aesthetic_v25", "deqa")
# A row with no stored metric at all: the scorer substitutes its own defaults, not 0.
MISSING_EXPECTED = {
    "aesthetic": 5.0, "face_quality": 5.0, "subject_sharpness": 5.0, "subject_prominence": 5.0,
    "bg_separation": 5.0, "composition": 5.0, "saturation": 5.0, "noise": 10.0, "dynamic_range": 0.0,
    "isolation": 0.0, "leading_lines": 0.0, "quality": 5.0,
}
MISSING_PATH = "/preview-score-keys/missing.jpg"


def test_the_column_table_covers_every_valid_weight_key():
    assert set(COLUMN) == set(VALID_WEIGHT_COLUMNS)


@pytest.fixture()
def photo(seed_photos_prefix):
    row = {"path": PATH, "filename": "p.jpg", "category": "default", "aggregate": 5.0}
    row.update({column: VALUE.get(column, 6.0) for column in COLUMN.values()})
    seed_photos_prefix("/preview-score-keys/", [row])
    return PATH


def preview(client, path, weights):
    resp = client.post("/api/comparison/preview_score", json={"path": path, "weights": weights})
    assert resp.status_code == 200, resp.text
    return resp.json()["preview_score"]


def alone(client, path, key):
    weights = {other: 0 for other in VALID_WEIGHT_COLUMNS}
    weights.update({"bonus": 0, key: 100})
    return preview(client, path, weights)


def extended_enabled():
    from api.config import server_scoring_config
    return server_scoring_config().get_extended_iqa_settings()


@pytest.mark.parametrize("key", sorted(VALID_WEIGHT_COLUMNS))
def test_every_valid_weight_key_scores_the_scorers_value(edition_client, photo, key):
    expected = EXPECTED[key]
    if key in EXTENDED and not extended_enabled().get(key):
        expected = 0.0
    assert alone(edition_client, photo, key) == pytest.approx(expected, abs=0.01), key


@pytest.mark.parametrize("key", sorted(MISSING_EXPECTED))
def test_a_row_missing_the_metric_scores_the_scorers_default(edition_client, seed_photos_prefix, key):
    seed_photos_prefix("/preview-score-keys/", [{"path": MISSING_PATH, "filename": "missing.jpg",
                                                 "category": "default", "aggregate": 5.0}])
    assert alone(edition_client, MISSING_PATH, key) == pytest.approx(MISSING_EXPECTED[key], abs=0.01), key
