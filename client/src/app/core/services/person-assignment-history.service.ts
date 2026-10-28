import { Injectable, inject } from '@angular/core';
import { AuthService } from './auth.service';
import { PERSON_ASSIGNMENT_HISTORY_KEY } from './person-assignment-history.storage';

// Mirrors MAX_RECENT_IDS in api/routers/persons.py (the server 422s beyond it).
const RECENT_LIMIT = 12;
const OWNER_LIMIT = 20;
const IDENTITY_LENGTH_LIMIT = 256;
const STORAGE_LENGTH_LIMIT = 16000;
interface History {
  identity: string;
  ids: number[];
}

/** Browser-local IDs only. Every candidate is revalidated by the persons API. */
@Injectable({ providedIn: 'root' })
export class PersonAssignmentHistoryService {
  private readonly auth = inject(AuthService);

  recentIds(): number[] {
    return this.read().find((entry) => entry.identity === this.auth.identity())?.ids.slice() ?? [];
  }

  record(personId: number, owner: string): void {
    if (!this.auth.isEdition()) return;
    if (owner !== this.auth.identity() || owner.length > IDENTITY_LENGTH_LIMIT) return;
    if (!Number.isSafeInteger(personId) || personId <= 0) return;
    const entries = this.read();
    const previous = entries.find((entry) => entry.identity === owner)?.ids ?? [];
    const ids = [personId, ...previous.filter((id) => id !== personId)].slice(0, RECENT_LIMIT);
    try {
      localStorage.setItem(PERSON_ASSIGNMENT_HISTORY_KEY, JSON.stringify([
        { identity: owner, ids }, ...entries.filter((entry) => entry.identity !== owner),
      ].slice(0, OWNER_LIMIT)));
    } catch { /* Storage is optional; assignments must still succeed. */ }
  }

  private read(): History[] {
    try {
      const raw = localStorage.getItem(PERSON_ASSIGNMENT_HISTORY_KEY);
      if (!raw || raw.length > STORAGE_LENGTH_LIMIT) return [];
      const value: unknown = JSON.parse(raw);
      if (!Array.isArray(value)) return [];
      return value.slice(0, OWNER_LIMIT).flatMap((entry: unknown) => {
        if (!entry || typeof entry !== 'object') return [];
        if (!('identity' in entry) || typeof entry.identity !== 'string') return [];
        if (entry.identity.length > IDENTITY_LENGTH_LIMIT) return [];
        if (!('ids' in entry) || !Array.isArray(entry.ids)) return [];
        const ids = [...new Set(entry.ids.filter((id: unknown): id is number =>
          typeof id === 'number' && Number.isSafeInteger(id) && id > 0))].slice(0, RECENT_LIMIT);
        return [{ identity: entry.identity, ids }];
      });
    } catch { return []; }
  }
}
