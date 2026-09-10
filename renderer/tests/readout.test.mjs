import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readoutFrame} from '../src/lib/readout.ts';

test('readouts hold for 300 ms at 30 and 60 fps, including the fastest part of the route', () => {
  for (const fps of [30, 60]) {
    const interval = Math.round(0.3 * fps);
    for (let frame = 0; frame < 13 * fps; frame++) {
      const sampled = readoutFrame(frame, fps, 13 * fps);
      assert.ok(sampled <= frame, 'never read ahead of the route');
      assert.ok(frame - sampled < interval, 'lag stays below one update interval');
      if (frame % interval !== 0) {
        assert.equal(sampled, readoutFrame(frame - 1, fps, 13 * fps));
      }
    }
  }
});

test('completion snaps to the endpoint and remains stable throughout the hold', () => {
  for (let frame = 390; frame < 450; frame++) {
    assert.equal(readoutFrame(frame, 30, 390), 390);
  }
  assert.equal(readoutFrame(0, 30, 390), 0);
  assert.equal(readoutFrame(-1, 30, 390), 0);
});

test('low frame rates cannot create a zero-length sampling interval', () => {
  assert.equal(readoutFrame(2, 1, 13), 2);
});
