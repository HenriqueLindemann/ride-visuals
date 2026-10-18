import {registerHooks} from 'node:module';
import {existsSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {test} from 'node:test';
import assert from 'node:assert/strict';

registerHooks({
  resolve(specifier, context, nextResolve) {
    if ((specifier.startsWith('./') || specifier.startsWith('../')) && !/\.[a-z0-9]+$/i.test(specifier) && context.parentURL) {
      for (const ext of ['.ts', '.tsx', '/index.ts']) {
        const candidate = new URL(specifier + ext, context.parentURL);
        if (existsSync(fileURLToPath(candidate))) {
          return nextResolve(specifier + ext, context);
        }
      }
    }
    return nextResolve(specifier, context);
  },
  load(url, context, nextLoad) {
    if (url.endsWith('/Typography.tsx')) {
      return {
        format: 'module',
        shortCircuit: true,
        source: `export const INK = {
          ink: '#0A0A09',
          paper: '#F3EFE8',
          paper2: 'rgba(243, 239, 232, 0.62)',
          paper3: 'rgba(243, 239, 232, 0.38)',
          hairline: 'rgba(243, 239, 232, 0.22)',
          accent: '#FF5A1F',
          accentRGB: [255, 90, 31],
          warmRGB: [222, 176, 146],
          paperRGB: [243, 239, 232],
        };
        export const FONT_STACK = "'Geist', sans-serif";`,
      };
    }
    return nextLoad(url, context);
  },
});

const {clamp01, envelope, glide, span, travel} = await import('../src/scene3d/core/ease.ts');
const {destination, greatCircle, mercX, mercY, unmercX, unmercY} = await import('../src/scene3d/core/geo.ts');
const {decodeTrack, indexAtDistance, lodFor, pointAtDistance} = await import('../src/scene3d/core/track.ts');
const {sceneSpecSchema} = await import('../src/scene3d/schema.ts');
const {scores} = await import('../src/scene3d/scores/index.ts');

test('ease curves preserve endpoints and monotonicity', () => {
  assert.equal(clamp01(-2), 0);
  assert.equal(clamp01(2), 1);
  assert.equal(span(5, 0, 10), 0.5);
  assert.ok(Math.abs(glide(0)) < 1e-6);
  assert.ok(Math.abs(glide(1) - 1) < 1e-6);
  assert.ok(Math.abs(travel(0.5) - 0.5) < 1e-3);
  assert.equal(envelope(0, 2, 8, 1), 0);
  assert.equal(envelope(5, 2, 8, 1), 1);
});

test('web mercator and great-circle helpers round-trip cleanly', () => {
  const lon = 7.769;
  const lat = 49.444;
  assert.ok(Math.abs(unmercX(mercX(lon)) - lon) < 1e-9);
  assert.ok(Math.abs(unmercY(mercY(lat)) - lat) < 1e-9);
  const mid = greatCircle([0, 0], [10, 0], 0.5);
  assert.ok(Math.abs(mid[0] - 5) < 1e-3);
  const east = destination([0, 0], 90, 111_320);
  assert.ok(Math.abs(east[0] - 1) < 0.02);
});

test('decodeTrack reconstructs delta-encoded tracks and interpolates by distance', () => {
  const enc = {
    x: [7_770_000, 10_000, 10_000],
    y: [49_440_000, 5_000, 5_000],
    d: [0, 5_000, 5_000],
    a: [2_000, 500, 500],
  };
  const track = decodeTrack(enc);
  assert.equal(track.n, 3);
  assert.ok(Math.abs(track.length - 1000) < 1e-6);
  assert.equal(indexAtDistance(track, 500), 1);
  const mid = pointAtDistance(track, 500);
  assert.ok(Math.abs(mid.alt - 250) < 1e-6);
  assert.ok(lodFor(track, 10).length >= 2);
});

test('flyover, stretch, and strata scores produce valid ops and non-overlapping texts', () => {
  const track = decodeTrack({
    x: [7_770_000, 10_000, 10_000],
    y: [49_440_000, 5_000, 5_000],
    d: [0, 10_000, 10_000],
    a: [2_000, 1_200, 800],
  });
  const projector = {
    frame: 0,
    camera: {
      center: [7.77, 49.44],
      zoom: 12,
      pitch: 50,
      bearing: 0,
      elevation: 200,
      terrain: 1.3,
      globe: false,
      mapOpacity: 1,
      contours: 1,
      satellite: 0,
      shade: 1,
    },
    width: 1920,
    height: 1080,
    globe: false,
    exaggeration: 1.3,
    resolution: 10,
    centerDepth: 1,
    // A local projection around the test area: ~0.75 px per metre.
    merc: (mx, my, lift, out) => {
      const mx0 = (7.77 + 180) / 360;
      const my0 = (180 - (180 / Math.PI) * Math.log(Math.tan(Math.PI / 4 + (49.44 * Math.PI) / 360))) / 360;
      out[0] = 960 + (mx - mx0) * 3e7;
      out[1] = 540 + (my - my0) * 3e7 - lift * 0.5;
      out[2] = 1;
      return true;
    },
    lngLat: (lon, lat, lift = 0) => [960 + (lon - 7.77) * 5000, 540 - (lat - 49.44) * 5000 - lift * 0.02, true],
  };

  const flySpec = sceneSpecSchema.parse({
    schemaVersion: '1.0',
    kind: 'flyover',
    locale: 'en',
    look: 'carbon',
    profile: {width: 1920, height: 1080, fps: 30, durationInFrames: 1},
    tiles: {dem: '/d', vector: '/v', satellite: null, demMaxZoom: 15, vectorMaxZoom: 14, satelliteMaxZoom: 17},
    credits: null,
    camera: {lon: [0], lat: [0], zoom: [12], pitch: [0], bearing: [0], elevation: [0], terrain: [0], globe: [0], mapOpacity: [0], contours: [0], satellite: [0]},
    channels: {
      head: [1500],
      headDot: [1],
      title: [0],
      counters: [1],
      km: [1.5],
      ascent: [120],
      beat: [1],
      climb0: [1],
      unfold: [1],
      chart: [1],
      stats: [1],
      black: [0],
    },
    tracks: [],
    story: {
      title: {label: 'Aug 29, 2026', text: 'Kaiserslautern'},
      labels: {distance: 'Distance', ascent: 'Elevation gain', kmUnit: 'km', mUnit: 'm', zeroKm: '0 km', totalKm: '2.0 km', peakAlt: '400 m'},
      unfold: {center: [7.77, 49.44], right: [1, 0], lineM: 2000, baseZ: 100, vertical: 1, minAlt: 80, altRange: 320},
      totalM: 2000,
      profile: [0, 0.5, 1, 0.8],
      peakFraction: 0.66,
      climbs: [{lon: 7.78, lat: 49.45, alt: 400, startAlt: 200, startM: 200, endM: 1400, gainText: '+200 m', subText: '1.2 km · 6%', hero: true}],
      stats: [{label: 'Distance', value: '2.0', unit: 'km'}],
    },
  });

  const flyOut = scores.flyover({
    spec: flySpec,
    tracks: [track],
    frame: 0,
    channel: (name) => flySpec.channels[name][0],
    projector,
    width: 1920,
    height: 1080,
    scale: 1,
  });
  assert.ok(flyOut.ops.length > 0);
  assert.ok(flyOut.texts.length > 0);

  // Before the ride sets off, no route is drawn at all: only the start marker.
  const flyOpening = scores.flyover({
    spec: flySpec,
    tracks: [track],
    frame: 0,
    channel: (name) => (name === 'head' || name === 'unfold' ? 0 : flySpec.channels[name][0]),
    projector,
    width: 1920,
    height: 1080,
    scale: 1,
  });
  assert.equal(flyOpening.ops.filter((op) => op.kind === 'track').length, 0);
  assert.equal(flyOpening.ops.filter((op) => op.kind === 'dot').length, 1);

  const strataSpec = sceneSpecSchema.parse({
    ...flySpec,
    kind: 'strata',
    channels: {
      final: [1],
      opening: [0],
      stats: [1],
      fade: [1],
      black: [0],
      floor0: [1],
      floor1: [1],
      label0: [1],
      label1: [1],
      draw0: [1],
      draw1: [0.5],
      focus0: [0],
      focus1: [1],
    },
    story: {
      corners: [
        [7.7, 49.4],
        [7.85, 49.4],
        [7.85, 49.5],
        [7.7, 49.5],
      ],
      floors: [
        {id: '2026-07', label: 'July', subLabel: '400 km · 8', targetLift: 0, trackIndices: [0]},
        {id: '2026-08', label: 'August', subLabel: '620 km · 12', targetLift: 5000, trackIndices: [0]},
      ],
      opening: {label: '20 rides', text: 'Kaiserslautern'},
      stats: [{label: 'Rides', value: '20'}],
    },
  });
  const strataOut = scores.strata({
    spec: strataSpec,
    tracks: [track],
    frame: 0,
    channel: (name) => strataSpec.channels[name][0],
    projector,
    width: 1920,
    height: 1080,
    scale: 1,
  });
  const floorTags = strataOut.texts.filter((t) => t.id.startsWith('floor-label-'));
  assert.equal(floorTags.length, 2);
  assert.ok(Math.abs(floorTags[0].y - floorTags[1].y) >= 34);
});
