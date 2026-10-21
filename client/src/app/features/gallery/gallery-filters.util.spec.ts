import { describe, it, expect, beforeEach } from 'vitest';
import {
  DEFAULT_FILTERS,
  type GalleryFilters,
  type ViewFilterParams,
  anyHideToggleActive,
  applyQueryParams,
  buildApiParams,
  buildByPathsFilters,
  BY_PATHS_MAX,
  buildSyncParams,
  seededSearchThreshold,
  countActiveFilters,
  loadDisplayOptionsFromStorage,
  saveDisplayOptionsToStorage,
  DISPLAY_OPTIONS_KEY,
  TOOLTIP_MODES,
  PANEL_ACTIVATIONS,
} from './gallery-filters.util';

function filters(overrides: Partial<GalleryFilters> = {}): GalleryFilters {
  return { ...DEFAULT_FILTERS, ...overrides };
}

describe('countActiveFilters', () => {
  it('returns 0 for defaults', () => {
    expect(countActiveFilters(DEFAULT_FILTERS)).toBe(0);
  });
  it('counts non-empty string filters', () => {
    expect(countActiveFilters(filters({ camera: 'Canon', tag: 'beach' }))).toBe(2);
  });
  it('counts favorites_only and is_monochrome', () => {
    expect(countActiveFilters(filters({ favorites_only: true, is_monochrome: true }))).toBe(2);
  });
  it('counts similar_to and semanticQuery', () => {
    expect(countActiveFilters(filters({ similar_to: '/p.jpg', semanticQuery: 'dog' }))).toBe(2);
  });
  it('never counts the ephemeral set-scope fields', () => {
    // They deliberately escape RANGE_AND_SELECT_KEYS so a set-scoped gallery
    // needs its own dismissible chip -- the badge must stay silent about it.
    expect(countActiveFilters(filters({
      sequence_kind: 'bracket', sequence_group_id: '1', burst_group_id: '5', duplicate_group_id: '9',
    }))).toBe(0);
  });
});

describe('buildApiParams', () => {
  it('always includes pagination + sort', () => {
    expect(buildApiParams(DEFAULT_FILTERS, false)).toMatchObject({
      page: 1, per_page: 64, sort: 'aggregate', sort_direction: 'DESC',
    });
  });
  it('omits empty string filters but includes non-empty ones', () => {
    const p = buildApiParams(filters({ camera: 'Canon' }), false);
    expect(p['camera']).toBe('Canon');
    expect(p['lens']).toBeUndefined();
  });
  it('encodes hide_* booleans only when true', () => {
    const p = buildApiParams(filters({ hide_blinks: true, hide_bursts: false }), false);
    expect(p['hide_blinks']).toBe(true);
    expect(p['hide_bursts']).toBeUndefined();
  });
  it('drops album_id for smart albums but keeps it otherwise', () => {
    expect(buildApiParams(filters({ album_id: '7' }), true)['album_id']).toBeUndefined();
    expect(buildApiParams(filters({ album_id: '7' }), false)['album_id']).toBe('7');
  });
  it('sends the set-scope fields to the API when set', () => {
    const p = buildApiParams(filters({ sequence_kind: 'bracket', sequence_group_id: '1' }), false);
    expect(p['sequence_kind']).toBe('bracket');
    expect(p['sequence_group_id']).toBe('1');
  });
});

describe('buildSyncParams', () => {
  it('is empty when filters equal defaults', () => {
    expect(buildSyncParams(DEFAULT_FILTERS, undefined)).toEqual({});
  });
  it('includes sort only when it differs from the effective default', () => {
    expect(buildSyncParams(filters({ sort: 'date_taken' }), undefined)['sort']).toBe('date_taken');
    expect(buildSyncParams(filters({ sort: 'date_taken' }), { sort: 'date_taken' })['sort']).toBeUndefined();
  });
  it('includes similarity_mode only when non-visual and similar_to is set', () => {
    expect(
      buildSyncParams(filters({ similar_to: '/p.jpg', similarity_mode: 'color' }), undefined)['similarity_mode'],
    ).toBe('color');
  });
  it('emits hide_blinks=false when it differs from the true default', () => {
    expect(buildSyncParams(filters({ hide_blinks: false }), undefined)['hide_blinks']).toBe('false');
  });
  it('emits search_threshold only when semanticQuery is set', () => {
    expect(
      buildSyncParams(filters({ semanticQuery: 'dog', search_threshold: '12' }), undefined)['search_threshold'],
    ).toBe('12');
    expect(
      buildSyncParams(filters({ search_threshold: '12' }), undefined)['search_threshold'],
    ).toBeUndefined();
  });
  it('omits a search_threshold still sitting on the server seed, emits a changed one', () => {
    // 0.05 seeds '5'. Emitting the seed froze it into every shared link, so a
    // later server-side recalibration could never reach an existing bookmark.
    expect(
      buildSyncParams(filters({ semanticQuery: 'dog', search_threshold: '5' }), undefined, 0.05)['search_threshold'],
    ).toBeUndefined();
    expect(
      buildSyncParams(filters({ semanticQuery: 'dog', search_threshold: '12' }), undefined, 0.05)['search_threshold'],
    ).toBe('12');
  });
  it('never writes the set-scope fields to the URL', () => {
    // sequence_group_id is renumbered from 1 on every detection pass, so a
    // bookmarked/shared URL carrying it would silently resolve to a
    // different set later -- it must stay in-memory only.
    const p = buildSyncParams(filters({
      sequence_kind: 'bracket', sequence_group_id: '1', burst_group_id: '5', duplicate_group_id: '9',
    }), undefined);
    expect(p['sequence_kind']).toBeUndefined();
    expect(p['sequence_group_id']).toBeUndefined();
    expect(p['burst_group_id']).toBeUndefined();
    expect(p['duplicate_group_id']).toBeUndefined();
  });
});

describe('applyQueryParams', () => {
  it('overlays string params', () => {
    const r = applyQueryParams(DEFAULT_FILTERS, { camera: 'Nikon', tag: 'sky' });
    expect(r.camera).toBe('Nikon');
    expect(r.tag).toBe('sky');
  });
  it('parses boolean params', () => {
    const r = applyQueryParams(DEFAULT_FILTERS, { hide_blinks: 'false', favorites_only: 'true' });
    expect(r.hide_blinks).toBe(false);
    expect(r.favorites_only).toBe(true);
  });
  it('validates similarity_mode against the allowlist', () => {
    expect(applyQueryParams(DEFAULT_FILTERS, { similarity_mode: 'bogus' }).similarity_mode).toBe('visual');
    expect(applyQueryParams(DEFAULT_FILTERS, { similarity_mode: 'color' }).similarity_mode).toBe('color');
  });
  it('accepts every tooltip mode and ignores anything else', () => {
    // The parser silently drops unknown values, so a mode missing from the
    // allowlist is un-shareable via URL rather than visibly broken.
    for (const mode of TOOLTIP_MODES) {
      expect(applyQueryParams(DEFAULT_FILTERS, { tooltip_mode: mode }).tooltip_mode).toBe(mode);
    }
    expect(applyQueryParams(DEFAULT_FILTERS, { tooltip_mode: 'sidebar' }).tooltip_mode)
      .toBe(DEFAULT_FILTERS.tooltip_mode);
  });
  it('accepts every panel activation and ignores anything else', () => {
    for (const activation of PANEL_ACTIVATIONS) {
      expect(applyQueryParams(DEFAULT_FILTERS, { panel_activation: activation }).panel_activation)
        .toBe(activation);
    }
    expect(applyQueryParams(DEFAULT_FILTERS, { panel_activation: 'bogus' }).panel_activation)
      .toBe(DEFAULT_FILTERS.panel_activation);
  });
  it('parses page as int with fallback to 1', () => {
    expect(applyQueryParams(DEFAULT_FILTERS, { page: '3' }).page).toBe(3);
    expect(applyQueryParams(DEFAULT_FILTERS, { page: 'x' }).page).toBe(1);
  });
  it('ignores the set-scope fields even if present in the URL', () => {
    // A crafted or stale URL must not resurrect a scope the server would
    // resolve against a since-renumbered group id.
    const r = applyQueryParams(DEFAULT_FILTERS, {
      sequence_kind: 'bracket', sequence_group_id: '1', burst_group_id: '5', duplicate_group_id: '9',
    });
    expect(r.sequence_kind).toBe('');
    expect(r.sequence_group_id).toBe('');
    expect(r.burst_group_id).toBe('');
    expect(r.duplicate_group_id).toBe('');
  });
  it('round-trips through buildSyncParams', () => {
    const original = filters({ camera: 'Canon', min_score: '7', hide_blinks: false, favorites_only: true });
    const restored = applyQueryParams(DEFAULT_FILTERS, buildSyncParams(original, undefined));
    expect(restored.camera).toBe('Canon');
    expect(restored.min_score).toBe('7');
    expect(restored.hide_blinks).toBe(false);
    expect(restored.favorites_only).toBe(true);
  });
  it('round-trips search_threshold only when emitted alongside semanticQuery', () => {
    const original = filters({ semanticQuery: 'dog', search_threshold: '12' });
    const restored = applyQueryParams(DEFAULT_FILTERS, buildSyncParams(original, undefined));
    expect(restored.search_threshold).toBe('12');
  });
  it('drops a non-numeric search_threshold rather than forwarding threshold=NaN', () => {
    // `+'abc' / 100` is NaN, which the API rejects with a 422 the gallery shows
    // only as a bare load error. '' is the meaningful value: the server then
    // resolves its own per-model default.
    expect(applyQueryParams(DEFAULT_FILTERS, { search_threshold: 'abc' }).search_threshold).toBe('');
  });
  it('clamps an out-of-range search_threshold to the slider span', () => {
    expect(applyQueryParams(DEFAULT_FILTERS, { search_threshold: '900' }).search_threshold).toBe('50');
    expect(applyQueryParams(DEFAULT_FILTERS, { search_threshold: '-3' }).search_threshold).toBe('0');
    expect(applyQueryParams(DEFAULT_FILTERS, { search_threshold: '7.6' }).search_threshold).toBe('8');
  });
});

describe('seededSearchThreshold', () => {
  it('renders a 0-1 fraction as a whole percent string', () => {
    expect(seededSearchThreshold(0.05)).toBe('5');
    expect(seededSearchThreshold(0.15)).toBe('15');
  });
  it('returns "" for anything not a finite number, so /search omits threshold', () => {
    expect(seededSearchThreshold(undefined)).toBe('');
    expect(seededSearchThreshold(null)).toBe('');
    expect(seededSearchThreshold(NaN)).toBe('');
  });
});

describe('display options storage', () => {
  beforeEach(() => localStorage.clear());
  it('saves and loads the display subset', () => {
    saveDisplayOptionsToStorage(filters({ hide_details: false, tooltip_mode: 'click', is_monochrome: true }));
    const loaded = loadDisplayOptionsFromStorage();
    expect(loaded.hide_details).toBe(false);
    expect(loaded.tooltip_mode).toBe('click');
    expect(loaded.is_monochrome).toBe(true);
  });
  it('saves and loads panel_activation, same channel as tooltip_mode', () => {
    saveDisplayOptionsToStorage(filters({ panel_activation: 'click' }));
    expect(loadDisplayOptionsFromStorage().panel_activation).toBe('click');
  });
  it('returns {} when storage is empty', () => {
    expect(loadDisplayOptionsFromStorage()).toEqual({});
  });
  it('returns {} on malformed JSON', () => {
    localStorage.setItem(DISPLAY_OPTIONS_KEY, '{bad');
    expect(loadDisplayOptionsFromStorage()).toEqual({});
  });
});

describe('per-channel clipping filters', () => {
  const CLIPPING = {
    min_channel_clip_highlight: '5',
    max_channel_clip_shadow: '2',
  };

  it('reaches the API', () => {
    const p = buildApiParams(filters(CLIPPING), false);
    expect(p['min_channel_clip_highlight']).toBe('5');
    expect(p['max_channel_clip_shadow']).toBe('2');
  });

  it('round-trips through the URL', () => {
    // Unlike the ephemeral set-scope fields, this is a real filter: a link to
    // "everything with blown highlights" has to survive being bookmarked.
    const synced = buildSyncParams(filters(CLIPPING), undefined);
    expect(synced['min_channel_clip_highlight']).toBe('5');
    expect(synced['max_channel_clip_shadow']).toBe('2');

    const restored = applyQueryParams(DEFAULT_FILTERS, synced);
    expect(restored.min_channel_clip_highlight).toBe('5');
    expect(restored.max_channel_clip_shadow).toBe('2');
  });

  it('counts towards the active-filter badge', () => {
    expect(countActiveFilters(filters(CLIPPING))).toBe(2);
  });

  it('is absent from the defaults, so it never filters until asked for', () => {
    expect(DEFAULT_FILTERS.min_channel_clip_highlight).toBe('');
    expect(buildApiParams(DEFAULT_FILTERS, false)['min_channel_clip_highlight']).toBeUndefined();
  });
});

describe('anyHideToggleActive', () => {
  const allOff: ViewFilterParams = {
    hide_blinks: '0',
    hide_bursts: '0',
    hide_duplicates: '0',
    hide_brackets: '0',
    hide_panoramas: '0',
  };
  const keys: (keyof ViewFilterParams)[] = [
    'hide_blinks', 'hide_bursts', 'hide_duplicates', 'hide_brackets', 'hide_panoramas',
  ];

  it('returns false when every toggle is off', () => {
    expect(anyHideToggleActive(allOff)).toBe(false);
  });

  it.each(keys)('returns true when only %s is on', key => {
    expect(anyHideToggleActive({ ...allOff, [key]: '1' })).toBe(true);
  });
});

// Snapshot of `gallery_filter_keys()` (api/models/gallery.py): the only keys POST /photos/by_paths accepts in
// `filters` (any other is a 422). Regenerate with:
//   venv/bin/python -c "from api.models.gallery import gallery_filter_keys as g; print(sorted(g()))"
const SERVER_FILTER_KEYS: ReadonlySet<string> = new Set([
  'album_id',
  'burst_group_id',
  'burst_only',
  'camera',
  'category',
  'color_temp',
  'composition_pattern',
  'date_from',
  'date_to',
  'dir',
  'duplicate_group_id',
  'exclude_art',
  'exclude_tags',
  'favorites_only',
  'gps_lat',
  'gps_lng',
  'gps_radius_km',
  'hide_blinks',
  'hide_brackets',
  'hide_bursts',
  'hide_duplicates',
  'hide_panoramas',
  'hide_rejected',
  'hue_bucket',
  'is_monochrome',
  'is_silhouette',
  'junk_kind',
  'lens',
  'max_aesthetic',
  'max_aesthetic_iaa',
  'max_aesthetic_v25',
  'max_aperture',
  'max_bg_separation',
  'max_channel_clip_highlight',
  'max_channel_clip_shadow',
  'max_color',
  'max_composition',
  'max_contrast',
  'max_deqa',
  'max_dynamic_range',
  'max_exposure',
  'max_eye_sharpness',
  'max_face_confidence',
  'max_face_count',
  'max_face_quality',
  'max_face_quality_iqa',
  'max_face_ratio',
  'max_face_sharpness',
  'max_focal_length',
  'max_histogram_spread',
  'max_iso',
  'max_isolation',
  'max_leading_lines',
  'max_liqe',
  'max_luminance',
  'max_moment_confidence',
  'max_noise',
  'max_power_point',
  'max_qrealign',
  'max_quality_score',
  'max_saturation',
  'max_score',
  'max_sharpness',
  'max_star_rating',
  'max_subject_placement',
  'max_subject_prominence',
  'max_subject_sharpness',
  'max_topiq',
  'min_aesthetic',
  'min_aesthetic_iaa',
  'min_aesthetic_v25',
  'min_aggregate',
  'min_aperture',
  'min_bg_separation',
  'min_channel_clip_highlight',
  'min_channel_clip_shadow',
  'min_color',
  'min_composition',
  'min_contrast',
  'min_deqa',
  'min_dynamic_range',
  'min_exposure',
  'min_eye_sharpness',
  'min_face_confidence',
  'min_face_count',
  'min_face_quality',
  'min_face_quality_iqa',
  'min_face_ratio',
  'min_face_sharpness',
  'min_focal_length',
  'min_histogram_spread',
  'min_iso',
  'min_isolation',
  'min_leading_lines',
  'min_liqe',
  'min_luminance',
  'min_moment_confidence',
  'min_noise',
  'min_power_point',
  'min_qrealign',
  'min_quality_score',
  'min_rating',
  'min_saturation',
  'min_score',
  'min_sharpness',
  'min_star_rating',
  'min_subject_placement',
  'min_subject_prominence',
  'min_subject_sharpness',
  'min_topiq',
  'narrative_moment',
  'no_blink',
  'page',
  'path_prefix',
  'per_page',
  'person',
  'person_id',
  'quality',
  'quality_tier',
  'require_tags',
  'search',
  'sequence_group_id',
  'sequence_kind',
  'sequence_override',
  'show_rejected',
  'sort',
  'sort_direction',
  'tag',
  'top_picks_filter',
  'type',
]);

describe('buildByPathsFilters', () => {
  it('carries the view filters but no paging or sort', () => {
    const p = buildByPathsFilters(filters({ hide_rejected: true, camera: 'Canon', album_id: '4', min_score: '7' }), false, '');
    expect(p).toMatchObject({ hide_rejected: true, camera: 'Canon', album_id: '4', min_score: '7' });
    for (const key of ['page', 'per_page', 'sort', 'sort_direction']) expect(p).not.toHaveProperty(key);
  });
  it('sends the viewer default type explicitly when the filter has none', () => {
    expect(buildByPathsFilters(filters(), false, 'top_picks')['type']).toBe('top_picks');
    expect(buildByPathsFilters(filters({ type: 'portrait' }), false, 'top_picks')['type']).toBe('portrait');
  });
  it('sends an empty type for a person view, as GET /photos resolves it', () => {
    expect(buildByPathsFilters(filters({ person_id: '3' }), false, 'top_picks')['type']).toBe('');
  });
  it('drops album_id for a smart album', () => {
    expect(buildByPathsFilters(filters({ album_id: '4' }), true, '')).not.toHaveProperty('album_id');
  });
  it('emits only keys the server accepts, so none can 422', () => {
    const every: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(DEFAULT_FILTERS)) every[key] = typeof value === 'boolean' ? true : 'x';
    const emitted = Object.keys(buildByPathsFilters(filters(every as Partial<GalleryFilters>), false, 'x'));
    expect(emitted.length).toBeGreaterThan(20);
    expect(emitted.filter(key => !SERVER_FILTER_KEYS.has(key))).toEqual([]);
  });
  it('chunks at the server cap', () => {
    expect(BY_PATHS_MAX).toBe(500);
  });
});
