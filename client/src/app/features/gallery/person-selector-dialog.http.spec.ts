import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { MatDialogRef } from '@angular/material/dialog';
import { AuthService } from '../../core/services/auth.service';
import { PersonAssignmentHistoryService } from '../../core/services/person-assignment-history.service';
import { PersonSelectorDialogComponent } from './person-selector-dialog.component';

describe('person picker HTTP ordering contract', () => {
  it('sends one bounded recent snapshot to server ranking on every page', async () => {
    const recentIds = vi.fn(() => [90, 2]);
    TestBed.configureTestingModule({ providers: [
      provideHttpClient(), provideHttpClientTesting(), PersonSelectorDialogComponent,
      { provide: AuthService, useValue: { identity: () => '1|alice' } },
      { provide: PersonAssignmentHistoryService, useValue: { recentIds } },
      { provide: MatDialogRef, useValue: { close: vi.fn() } },
    ] });
    const component = TestBed.inject(PersonSelectorDialogComponent);
    const http = TestBed.inject(HttpTestingController);
    const first = http.expectOne((req) => req.url === '/api/persons');
    expect(first.request.params.get('sort')).toBe('assignment');
    expect(first.request.params.get('recent_ids')).toBe('90,2');
    first.flush({ persons: [{ id: 90, name: 'Recent', face_count: 1 }], total: 49, sort: 'assignment' });
    await Promise.resolve();
    recentIds.mockReturnValue([5]);
    const next = component.loadMore();
    const second = http.expectOne((req) => req.url === '/api/persons');
    expect(second.request.params.get('page')).toBe('2');
    expect(second.request.params.get('recent_ids')).toBe('90,2');
    second.flush({ persons: [{ id: 5, name: 'Zed', face_count: 1 }], total: 49, sort: 'assignment' });
    await next;
    expect(component.filtered().map((person) => person.id)).toEqual([90, 5]);
    http.verify();
  });
});
