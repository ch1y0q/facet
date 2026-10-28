import { Pipe, PipeTransform } from '@angular/core';

/** Decorative hints only: translated option text remains the sort's label. */
const SORT_ICONS: Readonly<Record<string, string>> = {
  relevance: 'search',
  learned_score: 'psychology',
  top_picks_score: 'recommend',
  aggregate: 'leaderboard',
  aesthetic: 'auto_awesome',
  aesthetic_iaa: 'auto_awesome',
  aesthetic_v25: 'auto_awesome',
  qrealign_score: 'auto_awesome',
  quality_score: 'high_quality',
  deqa_score: 'high_quality',
  liqe_score: 'high_quality',
  date_taken: 'event',
  star_rating: 'star',
  face_quality: 'face',
  face_quality_iqa: 'face',
  eye_sharpness: 'visibility',
  face_sharpness: 'face',
  face_ratio: 'aspect_ratio',
  face_count: 'groups',
  tech_sharpness: 'deblur',
  contrast_score: 'contrast',
  noise_sigma: 'grain',
  color_score: 'palette',
  mean_saturation: 'colorize',
  exposure_score: 'exposure',
  mean_luminance: 'brightness_6',
  histogram_spread: 'bar_chart',
  dynamic_range_stops: 'tonality',
  comp_score: 'grid_on',
  power_point_score: 'filter_center_focus',
  leading_lines_score: 'timeline',
  isolation_bonus: 'filter_center_focus',
  composition_pattern: 'grid_view',
  subject_sharpness: 'center_focus_strong',
  subject_prominence: 'person',
  subject_placement: 'control_camera',
  bg_separation: 'blur_on',
  narrative_moment_confidence: 'photo_camera',
  f_stop: 'camera',
  focal_length: 'zoom_in',
  shutter_speed: 'shutter_speed',
};

@Pipe({ name: 'sortIcon', standalone: true, pure: true })
export class SortIconPipe implements PipeTransform {
  transform(column: string): string {
    return Object.hasOwn(SORT_ICONS, column) ? SORT_ICONS[column] : 'sort';
  }
}
