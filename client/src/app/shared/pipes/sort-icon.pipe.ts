import { Pipe, PipeTransform } from '@angular/core';

/** Decorative hints only: translated option text remains the sort's label. */
const SORT_ICONS: Readonly<Record<string, string>> = {
  relevance: 'search',
  learned_score: 'psychology',
  top_picks_score: 'recommend',
  aggregate: 'leaderboard',
  aesthetic: 'auto_awesome',
  quality_score: 'high_quality',
  date_taken: 'event',
  star_rating: 'star',
  face_quality: 'portrait',
  eye_sharpness: 'visibility',
  face_sharpness: 'face',
  face_ratio: 'crop_portrait',
  face_count: 'groups',
  tech_sharpness: 'deblur',
  contrast_score: 'contrast',
  noise_sigma: 'grain',
  color_score: 'palette',
  mean_saturation: 'gradient',
  exposure_score: 'exposure',
  mean_luminance: 'brightness_6',
  histogram_spread: 'bar_chart',
  dynamic_range_stops: 'tonality',
  comp_score: 'grid_on',
  power_point_score: 'grid_3x3',
  leading_lines_score: 'timeline',
  isolation_bonus: 'filter_tilt_shift',
  composition_pattern: 'grid_view',
  subject_sharpness: 'center_focus_strong',
  subject_prominence: 'photo_size_select_large',
  subject_placement: 'control_camera',
  bg_separation: 'blur_on',
  narrative_moment_confidence: 'auto_stories',
  f_stop: 'camera',
  focal_length: 'zoom_in',
  shutter_speed: 'shutter_speed',
};

const MODEL_LABELS: Readonly<Record<string, string>> = {
  aesthetic_iaa: 'IAA',
  aesthetic_v25: '2.5',
  qrealign_score: 'Q-R',
  deqa_score: 'DeQA',
  liqe_score: 'LIQE',
  face_quality_iqa: 'IQA',
};

export interface SortIcon {
  text: string;
  model: boolean;
}

@Pipe({ name: 'sortIcon', standalone: true, pure: true })
export class SortIconPipe implements PipeTransform {
  transform(column: string): SortIcon {
    if (Object.hasOwn(MODEL_LABELS, column)) return { text: MODEL_LABELS[column], model: true };
    return { text: Object.hasOwn(SORT_ICONS, column) ? SORT_ICONS[column] : 'sort', model: false };
  }
}
