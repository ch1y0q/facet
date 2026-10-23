import { TestBed } from '@angular/core/testing';
import { Router, NavigationEnd } from '@angular/router';
import { computed, signal } from '@angular/core';
import { Subject } from 'rxjs';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { AuthService } from '../services/auth.service';
import { FILTER_FLUSH_MS, UserActivityJournal } from './user-activity-journal.service';

describe('UserActivityJournal', () => {
  let events: Subject<unknown>;
  let journal: UserActivityJournal;
  let authStatus: ReturnType<typeof signal<{ authenticated: boolean; user_id: string | null } | null>>;

  beforeEach(() => {
    events = new Subject();
    authStatus = signal({ authenticated: true, user_id: 'alice' });
    TestBed.configureTestingModule({
      providers: [
        { provide: Router, useValue: { events } },
        { provide: AuthService, useValue: { identity: computed(() => `${authStatus()?.authenticated ? 1 : 0}|${authStatus()?.user_id ?? ''}`) } },
      ],
    });
    journal = TestBed.inject(UserActivityJournal);
    TestBed.tick();
  });

  it('assigns monotonic seqs and is stateless on read', () => {
    journal.record('rating', ['a'], 3);
    journal.record('favorite', ['b'], true);
    const first = journal.since();
    expect(first.items.map(i => i.seq)).toEqual([1, 2]);
    expect(first.until).toBe(2);
    expect(journal.since()).toEqual(first);
    expect(journal.since(2).items).toEqual([]);
    expect(journal.since(1).items.map(i => i.kind)).toEqual(['favorite']);
  });

  it('caps paths at 20 with a truncated flag', () => {
    journal.record('reject', Array.from({ length: 25 }, (_, i) => `p${i}`), true);
    const [item] = journal.since().items;
    expect(item.paths).toHaveLength(20);
    expect(item.truncated).toBe(true);
  });

  it('keeps the newest 50 and flags truncation', () => {
    for (let i = 0; i < 60; i++) journal.record('rating', ['a'], i);
    const report = journal.since();
    expect(report.items).toHaveLength(50);
    expect(report.items[0].seq).toBe(11);
    expect(report.truncated).toBe(true);
    expect(report.until).toBe(60);
  });

  it('records a navigate entry on NavigationEnd', () => {
    events.next(new NavigationEnd(1, '/a', '/b'));
    const [item] = journal.since().items;
    expect(item.kind).toBe('navigate');
    expect(item.value).toBe('/b');
  });

  it('records nothing inside a suppression scope, and resumes after it', async () => {
    await journal.suppress(async () => {
      journal.record('rating', ['a'], 1);
      events.next(new NavigationEnd(1, '/a', '/b'));
    });
    expect(journal.since().items).toEqual([]);
    journal.record('rating', ['a'], 1);
    expect(journal.since().items).toHaveLength(1);
  });

  it.each([
    ['another user', { authenticated: true, user_id: 'bob' }],
    ['logout', null],
  ])('drops the entries on %s but keeps seq monotonic', (_label, next) => {
    journal.record('rating', ['a'], 1);
    journal.record('rating', ['b'], 2);
    authStatus.set(next);
    TestBed.tick();
    expect(journal.since(0).items).toEqual([]);
    journal.record('rating', ['c'], 3);
    const [item] = journal.since(0).items;
    expect(item.seq).toBeGreaterThan(2);
    expect(journal.since(2).items).toHaveLength(1);
  });

  describe('filters', () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it('merges edits inside the window into one entry, last value winning', () => {
      for (let i = 1; i <= 5; i++) journal.recordFilters({ changed: { min_score: String(i), ...(i === 1 ? { tag: 'x' } : {}) } });
      vi.advanceTimersByTime(FILTER_FLUSH_MS);
      const items = journal.since().items;
      expect(items).toHaveLength(1);
      expect(items[0].kind).toBe('filters');
      expect(items[0].value).toEqual({ changed: { min_score: '5', tag: 'x' } });
    });

    it('does not buffer a change made inside a suppression scope, even if the timer fires later', async () => {
      let release!: () => void;
      const scope = journal.suppress(() => new Promise<void>(resolve => { release = resolve; }));
      journal.recordFilters({ changed: { search: 'agent' } });
      release();
      await scope;
      vi.advanceTimersByTime(FILTER_FLUSH_MS * 3);
      expect(journal.since().items).toEqual([]);
    });

    it('writes a user edit made before a suppression scope even when the timer fires inside it', async () => {
      journal.recordFilters({ changed: { search: 'mine' } });
      let release!: () => void;
      const scope = journal.suppress(() => new Promise<void>(resolve => { release = resolve; }));
      vi.advanceTimersByTime(FILTER_FLUSH_MS);
      release();
      await scope;
      expect(journal.since().items.map(i => i.value)).toEqual([{ changed: { search: 'mine' } }]);
    });

    it('records nothing for an empty diff', () => {
      journal.recordFilters({ changed: {} });
      vi.advanceTimersByTime(FILTER_FLUSH_MS);
      expect(journal.since().items).toEqual([]);
    });

    it('keeps scalars only, caps strings and keys', () => {
      const changed: Record<string, unknown> = { nested: { a: 1 }, list: [1], long: 'x'.repeat(200) };
      for (let i = 0; i < 20; i++) changed[`k${i}`] = i;
      journal.recordFilters({ changed });
      const value = journal.since().items[0].value as { changed: Record<string, unknown> };
      expect(Object.keys(value.changed)).toHaveLength(12);
      expect(value.changed['nested']).toBeUndefined();
      expect((value.changed['long'] as string).length).toBe(80);
    });

    it('flushes on read, so a read right after an edit sees it', () => {
      journal.recordFilters({ changed: { search: 'a' } });
      expect(journal.since().items).toHaveLength(1);
      vi.advanceTimersByTime(FILTER_FLUSH_MS * 2);
      expect(journal.since().items).toHaveLength(1);
    });

    it('orders a later rating after the pending filter entry', () => {
      journal.recordFilters({ changed: { search: 'a' } });
      journal.record('rating', ['p'], 4);
      const [filters, rating] = journal.since().items;
      expect(filters.kind).toBe('filters');
      expect(rating.kind).toBe('rating');
      expect(rating.seq).toBeGreaterThan(filters.seq);
    });

    it('records a chip removal as a filters entry only, not as the query-only navigation it causes', () => {
      events.next(new NavigationEnd(1, '/', '/'));
      const base = journal.since().until;
      journal.recordFilters({ changed: { min_aesthetic: '' } });
      events.next(new NavigationEnd(2, '/?x=1', '/?min_aesthetic='));
      expect(journal.since(base).items.map(i => i.kind)).toEqual(['filters']);
    });

    it('adds no navigate entry per slider tick', () => {
      events.next(new NavigationEnd(1, '/', '/'));
      const base = journal.since().until;
      for (let i = 1; i <= 5; i++) {
        journal.recordFilters({ changed: { min_score: String(i) } });
        events.next(new NavigationEnd(i + 1, '/', `/?min_score=${i}`));
      }
      vi.advanceTimersByTime(FILTER_FLUSH_MS);
      expect(journal.since(base).items.map(i => i.kind)).toEqual(['filters']);
    });

    it('flushes a pending filter entry before a path change, so the order is chronological', () => {
      events.next(new NavigationEnd(1, '/', '/'));
      const base = journal.since().until;
      journal.recordFilters({ changed: { search: 'a' } });
      events.next(new NavigationEnd(2, '/persons', '/persons'));
      const items = journal.since(base).items;
      expect(items.map(i => i.kind)).toEqual(['filters', 'navigate']);
      expect(items[1].value).toBe('/persons');
    });

    it('records a reset as {reset: true} and lets it absorb earlier edits', () => {
      journal.recordFilters({ changed: { search: 'a' } });
      journal.recordFilters({ reset: true });
      expect(journal.since().items.map(i => i.value)).toEqual([{ reset: true }]);
    });

    it('drops the pending buffer on identity change', () => {
      journal.recordFilters({ changed: { search: 'a' } });
      authStatus.set({ authenticated: true, user_id: 'bob' });
      TestBed.tick();
      vi.advanceTimersByTime(FILTER_FLUSH_MS * 2);
      expect(journal.since().items).toEqual([]);
    });
  });
});
