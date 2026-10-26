import { HttpContextToken } from '@angular/common/http';

/** Only the explicit lookup dialog renders these provider refusals inline. */
export const HANDLE_PLACE_SEARCH_ERRORS_LOCALLY = new HttpContextToken<boolean>(() => false);

const EXPECTED_DETAILS: Readonly<Record<number, string>> = {
  429: 'Wait before searching again',
  502: 'Online place search is unavailable',
  503: 'Online place search is disabled',
};

export function isExpectedPlaceSearchError(error: unknown): boolean {
  const response = error as { status?: number; error?: { detail?: unknown } } | null;
  return typeof response?.status === 'number' && response.error?.detail === EXPECTED_DETAILS[response.status]
    && EXPECTED_DETAILS[response.status] !== undefined;
}
