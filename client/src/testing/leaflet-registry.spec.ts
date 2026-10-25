import { leafletMock, leafletMockTileLayer, resetLeafletMock } from './leaflet-mock';
import { createLeafletMap } from '../app/shared/leaflet';

// Static imports run before a spec can call doMock. The setup must register
// Leaflet before any indirect component import caches the real module.

describe('Leaflet helper loaded before bundled specs', () => {
  beforeEach(() => resetLeafletMock());
  it('uses the same map and tile objects and forwards tile failure', () => {
    const failure = vi.fn();
    const container = document.createElement('div');
    createLeafletMap(container, undefined, failure);
    expect(leafletMock.map).toHaveBeenCalledWith(container, undefined);
    expect(leafletMockTileLayer.addTo).toHaveBeenCalledWith(leafletMock.map.mock.results[0].value);
    expect(leafletMockTileLayer.on).toHaveBeenCalledWith('tileerror', failure);
    const [, callback] = leafletMockTileLayer.on.mock.calls[0];
    callback();
    expect(failure).toHaveBeenCalledOnce();
  });
});
