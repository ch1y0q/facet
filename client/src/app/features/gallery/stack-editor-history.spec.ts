import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { readStackEditorHistory, stackEditorReturnUrl } from './stack-editor-history';

describe('manual editor history boundary', () => {
  beforeEach(() => TestBed.configureTestingModule({ providers: [provideRouter([])] }));
  afterEach(() => TestBed.resetTestingModule());
  it.each(['/', '/?search=a%20b#anchor', '/album/17?sort=date&x=%2F#last'])('preserves the exact gallery origin %s', value => {
    expect(stackEditorReturnUrl(TestBed.inject(Router), value)).toBe(value);
  });
  it.each(['https://other.example', '//other.example', '/\\other', '/%2fother', '/%5cother', '/album/a', '/album/17/more',
    '/album/17;other=x', '/(aux:album/17)', '/album/17(aux:photo)', '/photo?path=x', '/album/%', '/?q=%'])('refuses unsafe or non-gallery origin %s', value => {
    expect(stackEditorReturnUrl(TestBed.inject(Router), value)).toBe('/');
  });
  it.each([0, 1, 1001])('refuses %i input paths', count => {
    const paths = Array.from({ length: count }, (_, i) => `/p${i}`);
    expect(readStackEditorHistory({ version: 1, identity: 'alice', paths, returnUrl: '/' }, 'alice', TestBed.inject(Router))).toBeNull();
  });
  it.each([2, 1000])('admits exactly %i unique nonempty paths without copying private snapshots', count => {
    const paths = Array.from({ length: count }, (_, i) => `/p${i}`);
    const state = { version: 1, identity: 'alice', paths, returnUrl: '/' };
    expect(readStackEditorHistory(state, 'alice', TestBed.inject(Router))?.paths).toEqual(paths);
    expect(readStackEditorHistory({ ...state, preview: {} }, 'alice', TestBed.inject(Router))).toBeNull();
  });
});
