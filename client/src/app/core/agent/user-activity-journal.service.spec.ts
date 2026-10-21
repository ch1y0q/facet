import { TestBed } from '@angular/core/testing';
import { Router, NavigationEnd } from '@angular/router';
import { computed, signal } from '@angular/core';
import { Subject } from 'rxjs';
import { describe, it, expect, beforeEach } from 'vitest';
import { AuthService } from '../services/auth.service';
import { UserActivityJournal } from './user-activity-journal.service';

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
});
