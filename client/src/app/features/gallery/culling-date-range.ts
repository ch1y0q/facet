import { I18N } from '../../core/i18n/keys';
import { toIsoDateString } from '../../shared/utils/date-format';

export type CullDatePresetId = 'last_7_days' | 'last_30_days' | 'this_year' | 'last_year';

export interface CullDatePreset {
  id: CullDatePresetId;
  labelKey: string;
  icon: string;
}

/** The toolbar's relative ranges, in menu order. */
export const CULL_DATE_PRESETS: readonly CullDatePreset[] = [
  { id: 'last_7_days', labelKey: I18N.culling.date_range.last_7_days, icon: 'today' },
  { id: 'last_30_days', labelKey: I18N.culling.date_range.last_30_days, icon: 'calendar_view_month' },
  { id: 'this_year', labelKey: I18N.culling.date_range.this_year, icon: 'event' },
  { id: 'last_year', labelKey: I18N.culling.date_range.last_year, icon: 'history' },
];

/** Local midnight `days` calendar days before `d` (calendar arithmetic, so a DST night cannot shift the day). */
function daysBefore(d: Date, days: number): Date {
  const out = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  out.setDate(out.getDate() - days);
  return out;
}

/** The window a preset covers when picked on `today`, as `YYYY-MM-DD` strings (both ends inclusive). */
export function presetRange(id: CullDatePresetId, today: Date): { from: string; to: string } {
  const year = today.getFullYear();
  switch (id) {
    case 'last_7_days':
      return { from: toIsoDateString(daysBefore(today, 6)), to: toIsoDateString(daysBefore(today, 0)) };
    case 'last_30_days':
      return { from: toIsoDateString(daysBefore(today, 29)), to: toIsoDateString(daysBefore(today, 0)) };
    case 'this_year':
      return { from: toIsoDateString(new Date(year, 0, 1)), to: toIsoDateString(new Date(year, 11, 31)) };
    case 'last_year':
      return { from: toIsoDateString(new Date(year - 1, 0, 1)), to: toIsoDateString(new Date(year - 1, 11, 31)) };
  }
}

const SCOPE_DATE = /^(\d{4})[-:](\d{2})[-:](\d{2})(?:[ T]\d{2}:\d{2}:\d{2})?$/;

/** Local-midnight Date of a scope date (`YYYY-MM-DD` or the EXIF `YYYY:MM:DD[ HH:MM:SS]`), null for anything else. */
export function parseScopeDate(value: string | null): Date | null {
  const m = value ? SCOPE_DATE.exec(value) : null;
  if (!m) return null;
  const [year, month, day] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const d = new Date(year, month - 1, day);
  return d.getFullYear() === year && d.getMonth() === month - 1 && d.getDate() === day ? d : null;
}
