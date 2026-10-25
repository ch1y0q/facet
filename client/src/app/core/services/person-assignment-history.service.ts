import { Injectable, inject } from '@angular/core';
import { AuthService } from './auth.service';

const STORAGE_KEY = 'facet_person_assignments_v1';
const RECENT_LIMIT = 12;
interface History { identity: string; ids: number[] }

/** Browser-local IDs only. Every candidate is revalidated by the persons API. */
@Injectable({ providedIn: 'root' })
export class PersonAssignmentHistoryService {
  private readonly auth = inject(AuthService);

  recentIds(): number[] {
    return this.read().find((entry) => entry.identity === this.auth.identity())?.ids.slice() ?? [];
  }

  record(personId: number, owner: string): void {
    if (owner !== this.auth.identity() || owner.length > 256 || !Number.isSafeInteger(personId) || personId <= 0) return;
    const entries = this.read();
    const previous = entries.find((entry) => entry.identity === owner)?.ids ?? [];
    const ids = [personId, ...previous.filter((id) => id !== personId)].slice(0, RECENT_LIMIT);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify([
        { identity: owner, ids }, ...entries.filter((entry) => entry.identity !== owner),
      ].slice(0, 20)));
    } catch { /* Storage is optional; assignments must still succeed. */ }
  }

  private read(): History[] {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw || raw.length > 16000) return [];
      const value: unknown = JSON.parse(raw);
      if (!Array.isArray(value)) return [];
      return value.slice(0, 20).flatMap((entry: unknown) => {
        if (!entry || typeof entry !== 'object' || !('identity' in entry) ||
            typeof entry.identity !== 'string' || entry.identity.length > 256 || !('ids' in entry) || !Array.isArray(entry.ids)) return [];
        const ids = [...new Set(entry.ids.filter((id: unknown): id is number =>
          typeof id === 'number' && Number.isSafeInteger(id) && id > 0))].slice(0, RECENT_LIMIT);
        return [{ identity: entry.identity, ids }];
      });
    } catch { return []; }
  }
}
