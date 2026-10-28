-- Actual released v1.23.1 schema, initialized from v1.23.1:db/schema.py.
-- sqlite-vec disabled (optional extension); FTS shadow tables omitted.
CREATE TABLE album_client_picks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    album_id INTEGER NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
                    photo_path TEXT NOT NULL,
                    picked INTEGER DEFAULT 1,
                    comment TEXT,
                    client_name TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(album_id, photo_path)
                );

CREATE TABLE album_photos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    album_id INTEGER NOT NULL,
                    photo_path TEXT NOT NULL,
                    position INTEGER DEFAULT 0,
                    added_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(album_id, photo_path)
                );

CREATE TABLE albums (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    name TEXT NOT NULL,
                    description TEXT,
                    cover_photo_path TEXT,
                    is_smart INTEGER DEFAULT 0,
                    smart_filter_json TEXT,
                    share_token TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    scoring_context TEXT
                );

CREATE TABLE comparisons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    photo_a_path TEXT NOT NULL REFERENCES photos(path) ON DELETE CASCADE,
                    photo_b_path TEXT NOT NULL REFERENCES photos(path) ON DELETE CASCADE,
                    winner TEXT NOT NULL CHECK (winner IN ('a', 'b', 'tie', 'skip')),
                    category TEXT,
                    timestamp TEXT DEFAULT (datetime('now')),
                    session_id TEXT,
                    user_id TEXT,
                    source TEXT NOT NULL DEFAULT 'vote',
                    UNIQUE(photo_a_path, photo_b_path, user_id)
                );

CREATE TABLE face_reextract_snapshot (
                    photo_path TEXT NOT NULL,
                    bbox_x1 REAL,
                    bbox_y1 REAL,
                    bbox_x2 REAL,
                    bbox_y2 REAL,
                    person_id INTEGER NOT NULL
                );

CREATE TABLE faces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    photo_path TEXT NOT NULL REFERENCES photos(path) ON DELETE CASCADE,
                    face_index INTEGER NOT NULL,
                    embedding BLOB NOT NULL,
                    bbox_x1 INTEGER,
                    bbox_y1 INTEGER,
                    bbox_x2 INTEGER,
                    bbox_y2 INTEGER,
                    confidence REAL,
                    person_id INTEGER,
                    face_thumbnail BLOB,
                    landmark_2d_106 BLOB,
                    eyes_open_score REAL,
                    smile_score REAL,
                    embedding_model TEXT DEFAULT 'arcface_buffalo_l',
                    is_manual INTEGER NOT NULL DEFAULT 0,
                    manual_key TEXT,
                    manual_source TEXT,
                    manual_width INTEGER,
                    manual_height INTEGER,
                    UNIQUE(photo_path, face_index)
                );

CREATE TABLE iqa_declined (
                    photo_path TEXT NOT NULL REFERENCES photos(path) ON DELETE CASCADE,
                    model TEXT NOT NULL,
                    scan_fingerprint TEXT,
                    PRIMARY KEY (photo_path, model)
                );

CREATE TABLE learned_scores (
                    photo_path TEXT PRIMARY KEY REFERENCES photos(path) ON DELETE CASCADE,
                    learned_score REAL NOT NULL,
                    comparison_count INTEGER DEFAULT 0,
                    category TEXT,
                    updated_at TEXT DEFAULT (datetime('now')),
                    user_id TEXT
                );

CREATE TABLE location_names (
                    lat_grid REAL NOT NULL,
                    lon_grid REAL NOT NULL,
                    city TEXT,
                    region TEXT,
                    country TEXT,
                    display_name TEXT,
                    PRIMARY KEY (lat_grid, lon_grid)
                );

CREATE TABLE manual_face_deletions (
                    manual_key TEXT PRIMARY KEY NOT NULL
                );

CREATE TABLE mcp_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    token_prefix TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    level TEXT NOT NULL CHECK(level IN ('readonly','user','edition')),
                    user_gen TEXT NOT NULL,
                    edition_gen TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    last_used_at TEXT,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    revoked_at TEXT,
                    minted_level TEXT
                );

CREATE TABLE panorama_run_cache (
                    signature TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    segments TEXT NOT NULL,
                    measured_at REAL
                );

CREATE TABLE persons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    representative_face_id INTEGER,
                    face_count INTEGER DEFAULT 0,
                    centroid BLOB,
                    auto_clustered INTEGER DEFAULT 1,
                    face_thumbnail BLOB,
                    is_hidden INTEGER DEFAULT 0,
                    centroid_model TEXT,
                    person_key TEXT
                );

CREATE TABLE photo_manual_tags (
                    photo_path TEXT NOT NULL REFERENCES photos(path) ON DELETE CASCADE,
                    tag TEXT NOT NULL,
                    source TEXT NOT NULL CHECK(source IN ('user','xmp')),
                    created_by TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (photo_path, tag)
                );

CREATE TABLE photo_scoring_overrides (
                    photo_path TEXT PRIMARY KEY REFERENCES photos(path) ON DELETE CASCADE,
                    scoring_context TEXT,
                    category_override TEXT,
                    source TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    created_by TEXT
                );

CREATE TABLE photo_sequence_overrides (
                    photo_path TEXT PRIMARY KEY REFERENCES photos(path) ON DELETE CASCADE,
                    sequence_kind TEXT,
                    override_group_key TEXT,
                    source TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    created_by TEXT,
                    applied_at TEXT
                );

CREATE TABLE photo_tags (
                    photo_path TEXT NOT NULL REFERENCES photos(path) ON DELETE CASCADE,
                    tag TEXT NOT NULL,
                    PRIMARY KEY (photo_path, tag)
                );

CREATE TABLE photos (
                    path TEXT PRIMARY KEY,
                    filename TEXT,
                    date_taken TEXT,
                    camera_model TEXT,
                    lens_model TEXT,
                    iso INTEGER,
                    f_stop REAL,
                    shutter_speed TEXT,
                    focal_length REAL,
                    focal_length_35mm REAL,
                    image_width INTEGER,
                    image_height INTEGER,
                    image_aspect REAL,
                    aesthetic REAL,
                    face_count INTEGER DEFAULT 0 CHECK (face_count >= 0),
                    face_quality REAL,
                    eye_sharpness REAL,
                    face_sharpness REAL,
                    eyes_open_score REAL,
                    expression_score REAL,
                    face_ratio REAL CHECK (face_ratio IS NULL OR (face_ratio >= 0 AND face_ratio <= 1)),
                    tech_sharpness REAL,
                    color_score REAL,
                    exposure_score REAL,
                    comp_score REAL,
                    isolation_bonus REAL,
                    aggregate REAL CHECK (aggregate IS NULL OR (aggregate >= 0 AND aggregate <= 10)),
                    is_blink INTEGER CHECK (is_blink IS NULL OR is_blink IN (0, 1)),
                    is_burst_lead INTEGER DEFAULT 0 CHECK (is_burst_lead IN (0, 1)),
                    burst_group_id INTEGER,
                    burst_reviewed INTEGER NOT NULL DEFAULT 0 CHECK (burst_reviewed IN (0, 1)),
                    similarity_reviewed INTEGER NOT NULL DEFAULT 0 CHECK (similarity_reviewed IN (0, 1)),
                    is_monochrome INTEGER DEFAULT 0 CHECK (is_monochrome IN (0, 1)),
                    is_silhouette INTEGER,
                    is_group_portrait INTEGER,
                    duplicate_group_id INTEGER,
                    is_duplicate_lead INTEGER DEFAULT 0 CHECK (is_duplicate_lead IN (0, 1)),
                    sequence_group_id INTEGER,
                    sequence_kind TEXT,
                    sequence_ev_offset REAL,
                    is_sequence_lead INTEGER DEFAULT 0,
                    clip_embedding BLOB,
                    raw_sharpness_variance REAL,
                    histogram_data BLOB,
                    histogram_spread REAL,
                    mean_luminance REAL,
                    histogram_bimodality REAL,
                    power_point_score REAL,
                    raw_color_entropy REAL,
                    raw_eye_sharpness REAL,
                    shadow_clipped INTEGER,
                    highlight_clipped INTEGER,
                    channel_clip_shadow_pct REAL,
                    channel_clip_highlight_pct REAL,
                    dynamic_range_stops REAL,
                    noise_sigma REAL,
                    contrast_score REAL,
                    mean_saturation REAL,
                    leading_lines_score REAL,
                    face_confidence REAL,
                    thumbnail BLOB,
                    phash TEXT,
                    config_version TEXT,
                    tags TEXT,
                    quality_score REAL,
                    topiq_score REAL,
                    composition_explanation TEXT,
                    scoring_model TEXT,
                    composition_pattern TEXT,
                    category TEXT,
                    aesthetic_iaa REAL,
                    face_quality_iqa REAL,
                    liqe_score REAL,
                    aesthetic_clip REAL,
                    qrealign_score REAL,
                    aesthetic_v25 REAL,
                    deqa_score REAL,
                    subject_sharpness REAL,
                    subject_prominence REAL,
                    subject_placement REAL,
                    bg_separation REAL,
                    subject_bbox TEXT,
                    star_rating INTEGER DEFAULT 0 CHECK (star_rating >= 0 AND star_rating <= 5),
                    is_favorite INTEGER DEFAULT 0 CHECK (is_favorite IN (0, 1)),
                    is_rejected INTEGER DEFAULT 0 CHECK (is_rejected IN (0, 1)),
                    caption TEXT,
                    caption_translated TEXT,
                    vlm_critique TEXT,
                    vlm_critique_translated TEXT,
                    ocr_text TEXT,
                    dominant_hue REAL,
                    color_temp TEXT,
                    form_symmetry REAL,
                    form_balance REAL,
                    form_edge_entropy REAL,
                    form_fractal REAL,
                    color_harmony REAL,
                    gps_latitude REAL,
                    gps_longitude REAL,
                    scanned_at TEXT,
                    narrative_moment TEXT,
                    narrative_moment_confidence REAL,
                    junk_kind TEXT,
                    caption_embedding BLOB,
                    learned_score REAL,
                    distortion_attributes TEXT,
                    skin_tone_delta REAL,
                    skin_tone_cast TEXT,
                    render_version INTEGER,
                    gps_manually_set INTEGER NOT NULL DEFAULT 0
                );

CREATE VIRTUAL TABLE photos_fts USING fts5(
    path UNINDEXED,
    filename,
    caption,
    caption_translated,
    tags,
    camera_model,
    lens_model,
    category,
    ocr_text,
    content='photos',
    content_rowid='rowid'
);

CREATE TABLE rating_provenance (
                    user_id TEXT NOT NULL DEFAULT '',
                    photo_path TEXT NOT NULL,
                    star_rating INTEGER NOT NULL DEFAULT 0,
                    is_favorite INTEGER NOT NULL DEFAULT 0,
                    is_rejected INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_id, photo_path)
                );

CREATE TABLE recent_places (
                    owner TEXT NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    last_used_at TEXT NOT NULL,
                    PRIMARY KEY(owner, latitude, longitude)
                );

CREATE TABLE recommendation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_timestamp TEXT DEFAULT (datetime('now')),
                    config_version_hash TEXT,
                    issue_type TEXT NOT NULL,
                    target_category TEXT,
                    target_key TEXT,
                    old_value REAL,
                    proposed_value REAL,
                    was_applied INTEGER DEFAULT 0
                );

CREATE TABLE rejected_merge_suggestions (
                    person_a_id INTEGER NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
                    person_b_id INTEGER NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
                    rejected_at TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (person_a_id, person_b_id)
                );

CREATE TABLE saved_places (
                    id INTEGER PRIMARY KEY,
                    owner TEXT NOT NULL,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    last_used_at TEXT,
                    use_count INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(owner, normalized_name)
                );

CREATE TABLE scan_failures (
                    scan_run_id INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
                    path TEXT NOT NULL,
                    stage TEXT,
                    error TEXT,
                    timestamp TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (scan_run_id, path)
                );

CREATE TABLE scan_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT DEFAULT (datetime('now')),
                    finished_at TEXT,
                    status TEXT NOT NULL DEFAULT 'running',
                    mode TEXT,
                    args_json TEXT,
                    total_files INTEGER,
                    processed_files INTEGER DEFAULT 0,
                    failed_files INTEGER DEFAULT 0,
                    heartbeat_at TEXT
                );

CREATE TABLE stats_cache (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at REAL
                );

CREATE TABLE user_preferences (
                    user_id TEXT NOT NULL,
                    photo_path TEXT NOT NULL REFERENCES photos(path) ON DELETE CASCADE,
                    star_rating INTEGER DEFAULT 0 CHECK (star_rating >= 0 AND star_rating <= 5),
                    is_favorite INTEGER DEFAULT 0 CHECK (is_favorite IN (0, 1)),
                    is_rejected INTEGER DEFAULT 0 CHECK (is_rejected IN (0, 1)),
                    PRIMARY KEY (user_id, photo_path)
                );

CREATE TABLE weight_config_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT DEFAULT (datetime('now')),
                    category TEXT,
                    weights TEXT NOT NULL,
                    description TEXT,
                    accuracy_before REAL,
                    accuracy_after REAL,
                    comparisons_used INTEGER,
                    created_by TEXT,
                    category_bonus REAL
                );

CREATE TABLE weight_optimization_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT DEFAULT (datetime('now')),
                    category TEXT,
                    comparisons_used INTEGER,
                    old_weights TEXT,
                    new_weights TEXT,
                    mse_before REAL,
                    mse_after REAL
                );

CREATE INDEX idx_aesthetic_aggregate ON photos(aesthetic DESC, aggregate DESC);

CREATE INDEX idx_aesthetic_iaa ON photos(aesthetic_iaa);

CREATE INDEX idx_aesthetic_v25_sort ON photos(aesthetic_v25 DESC, path);

CREATE INDEX idx_aggregate ON photos(aggregate DESC);

CREATE INDEX idx_aggregate_date ON photos(aggregate DESC, date_taken DESC);

CREATE INDEX idx_album_client_picks_album ON album_client_picks(album_id);

CREATE INDEX idx_album_photos_album ON album_photos(album_id);

CREATE INDEX idx_album_photos_path ON album_photos(photo_path);

CREATE INDEX idx_album_photos_position ON album_photos(album_id, position);

CREATE INDEX idx_albums_share_token ON albums(share_token);

CREATE INDEX idx_albums_user ON albums(user_id);

CREATE INDEX idx_bg_separation ON photos(bg_separation);

CREATE INDEX idx_blink_burst ON photos(is_blink, is_burst_lead);

CREATE INDEX idx_burst_aggregate ON photos(is_burst_lead, aggregate DESC);

CREATE INDEX idx_burst_group ON photos(burst_group_id);

CREATE INDEX idx_burst_reviewed ON photos(burst_reviewed, burst_group_id);

CREATE INDEX idx_camera_lens ON photos(camera_model, lens_model);

CREATE INDEX idx_camera_model ON photos(camera_model);

CREATE INDEX idx_category ON photos(category);

CREATE INDEX idx_category_aggregate ON photos(category, aggregate DESC);

CREATE INDEX idx_channel_clip_highlight ON photos(channel_clip_highlight_pct);

CREATE INDEX idx_channel_clip_shadow ON photos(channel_clip_shadow_pct);

CREATE INDEX idx_color_score ON photos(color_score);

CREATE INDEX idx_color_temp ON photos(color_temp);

CREATE INDEX idx_comp_score ON photos(comp_score);

CREATE INDEX idx_comparisons_category ON comparisons(category);

CREATE INDEX idx_comparisons_photo_a ON comparisons(photo_a_path);

CREATE INDEX idx_comparisons_photo_b ON comparisons(photo_b_path);

CREATE INDEX idx_comparisons_source ON comparisons(source);

CREATE INDEX idx_comparisons_timestamp ON comparisons(timestamp DESC);

CREATE INDEX idx_composition_pattern ON photos(composition_pattern);

CREATE INDEX idx_contrast_score ON photos(contrast_score);

CREATE INDEX idx_date_asc_cover ON photos(date_taken ASC, path, is_blink, is_burst_lead, burst_group_id, is_sequence_lead, is_duplicate_lead, duplicate_group_id, sequence_kind, sequence_ev_offset, is_rejected, junk_kind, camera_model, focal_length, f_stop, shutter_speed, iso, phash, shadow_clipped, highlight_clipped, scanned_at, render_version, length(thumbnail));

CREATE INDEX idx_date_taken ON photos(date_taken);

CREATE INDEX idx_date_taken_desc ON photos(date_taken DESC);

CREATE INDEX idx_deqa_sort ON photos(deqa_score DESC, path);

CREATE INDEX idx_dominant_hue ON photos(dominant_hue);

CREATE INDEX idx_duplicate_group ON photos(duplicate_group_id);

CREATE INDEX idx_duplicate_lead ON photos(is_duplicate_lead);

CREATE INDEX idx_dynamic_range_stops ON photos(dynamic_range_stops);

CREATE INDEX idx_exposure_score ON photos(exposure_score);

CREATE INDEX idx_eye_sharpness ON photos(eye_sharpness);

CREATE INDEX idx_f_stop ON photos(f_stop);

CREATE INDEX idx_face_confidence ON photos(face_confidence);

CREATE INDEX idx_face_count ON photos(face_count);

CREATE INDEX idx_face_detection ON photos(face_count, face_ratio);

CREATE INDEX idx_face_quality_iqa ON photos(face_quality_iqa);

CREATE INDEX idx_face_quality_sort ON photos(face_quality DESC, eye_sharpness DESC);

CREATE INDEX idx_face_ratio ON photos(face_ratio);

CREATE INDEX idx_face_sharpness ON photos(face_sharpness);

CREATE INDEX idx_faces_person ON faces(person_id);

CREATE INDEX idx_faces_person_photo ON faces(person_id, photo_path);

CREATE INDEX idx_faces_photo ON faces(photo_path);

CREATE INDEX idx_favorite_aggregate ON photos(is_favorite, aggregate DESC);

CREATE INDEX idx_filename ON photos(filename);

CREATE INDEX idx_focal_length ON photos(focal_length);

CREATE INDEX idx_gallery_aggregate ON photos(aggregate DESC, path, is_blink, is_burst_lead, burst_group_id, is_sequence_lead, is_duplicate_lead, duplicate_group_id, sequence_kind, sequence_ev_offset, is_rejected, junk_kind, category, camera_model, lens_model, face_ratio, aesthetic, comp_score, face_quality);

CREATE INDEX idx_gallery_camera ON photos(camera_model, aggregate DESC, path, is_blink, is_burst_lead, burst_group_id, is_sequence_lead, is_duplicate_lead, duplicate_group_id, sequence_kind, sequence_ev_offset, is_rejected, junk_kind, lens_model);

CREATE INDEX idx_gallery_category ON photos(category, aggregate DESC, path, is_blink, is_burst_lead, burst_group_id, is_sequence_lead, is_duplicate_lead, duplicate_group_id, sequence_kind, sequence_ev_offset, is_rejected, junk_kind);

CREATE INDEX idx_gallery_date_desc ON photos(date_taken DESC, path, is_blink, is_burst_lead, burst_group_id, is_sequence_lead, is_duplicate_lead, duplicate_group_id, sequence_kind, sequence_ev_offset, is_rejected, junk_kind);

CREATE INDEX idx_gallery_iaa_asc ON photos((aesthetic_iaa IS NULL), aesthetic_iaa, path, is_blink, is_burst_lead, burst_group_id, is_sequence_lead, is_duplicate_lead, duplicate_group_id, sequence_kind, sequence_ev_offset, is_rejected, junk_kind);

CREATE INDEX idx_gps ON photos(gps_latitude, gps_longitude);

CREATE INDEX idx_histogram_spread ON photos(histogram_spread);

CREATE INDEX idx_is_burst_lead ON photos(is_burst_lead);

CREATE INDEX idx_is_favorite ON photos(is_favorite);

CREATE INDEX idx_is_monochrome ON photos(is_monochrome);

CREATE INDEX idx_is_rejected ON photos(is_rejected);

CREATE INDEX idx_is_sequence_lead ON photos(is_sequence_lead);

CREATE INDEX idx_iso ON photos(iso);

CREATE INDEX idx_isolation_bonus ON photos(isolation_bonus);

CREATE INDEX idx_junk_kind ON photos(junk_kind);

CREATE INDEX idx_leading_lines_score ON photos(leading_lines_score);

CREATE INDEX idx_learned_score ON photos(learned_score DESC, path);

CREATE INDEX idx_learned_scores_category ON learned_scores(category);

CREATE INDEX idx_learned_scores_score ON learned_scores(learned_score DESC);

CREATE INDEX idx_lens_model ON photos(lens_model);

CREATE INDEX idx_liqe_score ON photos(liqe_score);

CREATE UNIQUE INDEX idx_manual_face_key ON faces(manual_key) WHERE is_manual=1;

CREATE INDEX idx_mcp_tokens_user ON mcp_tokens(user_id);

CREATE INDEX idx_mean_luminance ON photos(mean_luminance);

CREATE INDEX idx_mean_saturation ON photos(mean_saturation);

CREATE INDEX idx_moment_confidence ON photos(narrative_moment_confidence DESC, path);

CREATE INDEX idx_narrative_moment ON photos(narrative_moment);

CREATE INDEX idx_noise_sigma ON photos(noise_sigma);

CREATE INDEX idx_optimization_category ON weight_optimization_runs(category);

CREATE INDEX idx_optimization_timestamp ON weight_optimization_runs(timestamp DESC);

CREATE UNIQUE INDEX idx_person_key ON persons(person_key);

CREATE INDEX idx_photo_manual_tags_tag ON photo_manual_tags(tag);

CREATE INDEX idx_photo_tags_path ON photo_tags(photo_path);

CREATE INDEX idx_photo_tags_tag ON photo_tags(tag);

CREATE INDEX idx_post_scan ON photos(phash, date_taken, aggregate, face_count, eyes_open_score, expression_score, tech_sharpness, is_burst_lead, burst_group_id, duplicate_group_id, is_duplicate_lead, path);

CREATE INDEX idx_power_point_score ON photos(power_point_score);

CREATE INDEX idx_qrealign_sort ON photos(qrealign_score DESC, path);

CREATE INDEX idx_quality_score ON photos(quality_score);

CREATE INDEX idx_rec_history_target ON recommendation_history(target_category, target_key);

CREATE INDEX idx_rec_history_timestamp ON recommendation_history(run_timestamp DESC);

CREATE INDEX idx_rejected_aggregate ON photos(is_rejected, aggregate DESC);

CREATE INDEX idx_scan_failures_run ON scan_failures(scan_run_id);

CREATE INDEX idx_scan_runs_status ON scan_runs(status);

CREATE INDEX idx_scanned_at ON photos(scanned_at);

CREATE INDEX idx_sequence_group ON photos(sequence_group_id);

CREATE INDEX idx_sequence_kind ON photos(sequence_kind, sequence_group_id);

CREATE INDEX idx_shoot_type_evidence ON photos(category, narrative_moment, face_count, date_taken);

CREATE INDEX idx_similarity_reviewed ON photos(similarity_reviewed);

CREATE INDEX idx_snapshots_category ON weight_config_snapshots(category);

CREATE INDEX idx_snapshots_timestamp ON weight_config_snapshots(timestamp DESC);

CREATE INDEX idx_star_rating ON photos(star_rating);

CREATE INDEX idx_star_rating_path ON photos(star_rating DESC, path);

CREATE INDEX idx_stats_categories ON photos(category, aggregate, aesthetic, comp_score, tech_sharpness, color_score, exposure_score, iso, f_stop, focal_length_35mm, focal_length, face_quality, contrast_score, camera_model, lens_model);

CREATE INDEX idx_subject_placement ON photos(subject_placement);

CREATE INDEX idx_subject_prominence ON photos(subject_prominence);

CREATE INDEX idx_subject_sharpness ON photos(subject_sharpness);

CREATE INDEX idx_tags ON photos(tags);

CREATE INDEX idx_tech_sharpness_sort ON photos(tech_sharpness DESC, aesthetic DESC);

CREATE INDEX idx_topiq_score ON photos(topiq_score);

CREATE INDEX idx_user_prefs_fav ON user_preferences(user_id, is_favorite);

CREATE INDEX idx_user_prefs_path ON user_preferences(photo_path);

CREATE INDEX idx_user_prefs_rating ON user_preferences(user_id, star_rating);

CREATE INDEX idx_user_prefs_user ON user_preferences(user_id);

CREATE TRIGGER persons_assign_key AFTER INSERT ON persons
            WHEN NEW.person_key IS NULL BEGIN
              UPDATE persons SET person_key=lower(hex(randomblob(16))) WHERE id=NEW.id;
            END;
