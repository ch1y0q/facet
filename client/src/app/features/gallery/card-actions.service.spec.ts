import { TestBed } from '@angular/core/testing';
import { CardActionsService } from './card-actions.service';
import { CARD_ACTION_IDS, DEFAULT_CARD_ACTIONS } from '../../shared/components/photo-card/card-actions';

describe('CardActionsService', () => {
  beforeEach(() => {
    localStorage.removeItem('facet_card_actions');
    TestBed.configureTestingModule({});
  });

  it('starts on the default layout: the four original buttons, duplicate group in', () => {
    const service = TestBed.inject(CardActionsService);
    expect(service.config()).toEqual(DEFAULT_CARD_ACTIONS);
    expect(service.config().hidden).toEqual(['burst_set', 'sequence_set', 'open_detail']);
  });

  it('persists a new layout and restores it in a fresh instance', () => {
    TestBed.inject(CardActionsService).set({
      order: ['open_detail', 'similar'],
      hidden: ['similar'],
    });
    expect(JSON.parse(localStorage.getItem('facet_card_actions')!)).toEqual({
      order: ['open_detail', 'similar'],
      hidden: ['similar'],
    });

    const restored = TestBed.inject(CardActionsService);
    expect(restored.config().order).toEqual(['open_detail', 'similar']);
    expect(restored.config().hidden).toEqual(['similar']);
  });

  it('appends actions a newer build added to a saved order, in default visibility', () => {
    localStorage.setItem('facet_card_actions', JSON.stringify({
      order: ['similar', 'critique'],
      hidden: [],
    }));
    const service = TestBed.inject(CardActionsService);
    expect(service.config().order).toEqual([
      'similar', 'critique', ...CARD_ACTION_IDS.filter(id => id !== 'similar' && id !== 'critique'),
    ]);
    expect(service.config().hidden).toEqual([]);
  });

  it('falls back to defaults on a malformed saved value', () => {
    localStorage.setItem('facet_card_actions', '{not json');
    expect(TestBed.inject(CardActionsService).config()).toEqual(DEFAULT_CARD_ACTIONS);
  });

  it('reset() returns to the default layout and persists it', () => {
    const service = TestBed.inject(CardActionsService);
    service.set({ order: ['open_detail'], hidden: [] });
    service.reset();
    expect(service.config()).toEqual(DEFAULT_CARD_ACTIONS);
    expect(JSON.parse(localStorage.getItem('facet_card_actions')!)).toEqual(DEFAULT_CARD_ACTIONS);
  });
});
