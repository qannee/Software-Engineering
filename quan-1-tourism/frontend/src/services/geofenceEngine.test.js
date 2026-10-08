import assert from 'node:assert/strict';
import test from 'node:test';
import { GeofenceEngine } from './geofenceEngine.js';

const poi = { id: 'market', title: 'Market', location: { coordinates: [106.698, 10.772] }, geofence_radius: 80 };
const inside = { longitude: 106.698, latitude: 10.772 };
const outside = { longitude: 106.71, latitude: 10.772 };

test('enters a geofence only after a stable three second presence', () => {
  const originalNow = Date.now;
  let now = 1_000_000;
  Date.now = () => now;
  try {
    const entered = [];
    const engine = new GeofenceEngine([poi], (item) => entered.push(item.id));
    engine.checkPosition(inside);
    now += 1_000;
    engine.checkPosition(inside);
    assert.deepEqual(entered, []);
    now += 2_100;
    engine.checkPosition(inside);
    assert.deepEqual(entered, ['market']);
  } finally {
    Date.now = originalNow;
  }
});

test('fires an exit event when leaving the nearest zone', () => {
  const originalNow = Date.now;
  let now = 2_000_000;
  Date.now = () => now;
  try {
    const exited = [];
    const engine = new GeofenceEngine([poi], () => {}, (item) => exited.push(item.id));
    engine.activeZones.add(poi.id);
    engine.checkPosition(outside);
    assert.deepEqual(exited, ['market']);
  } finally {
    Date.now = originalNow;
  }
});
