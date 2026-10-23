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
const {destination, greatCircle, groundResolution, mercX, mercY, metersPerPixel, unmercX, unmercY} = await import(
  '../src/scene3d/core/geo.ts'
);
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

test('ground resolution eases with pitch instead of jumping', () => {
  const mpp = metersPerPixel(12, 49.44);
  assert.equal(groundResolution(12, 49.44, 0), mpp);
  assert.ok(Math.abs(groundResolution(12, 49.44, 60) - 0.55 * mpp) < 1e-9);
  // It used to step from 1x to 0.55x at 30 degrees: line detail popped mid-tilt.
  assert.ok(Math.abs(groundResolution(12, 49.44, 29.9) - groundResolution(12, 49.44, 30.1)) < 0.01 * mpp);
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
      labels: {distance: 'Distance', ascent: 'Elevation gain', kmUnit: 'km', mUnit: 'm', peakAlt: '400 m'},
      unfold: {center: [7.77, 49.44], right: [1, 0], lineM: 2000, baseZ: 100, vertical: 1, minAlt: 80, altRange: 320},
      layout: {marginX: 112, topY: 88, bottomY: 918, routeLift: 4, readout: {box: [1348, 88, 1808, 218], stripTop: 122, stripBottom: 178}},
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

test('edge-case scores: flat flyover, 12-month portrait strata, and multi-ride stretch with toward', () => {
  const track = decodeTrack({
    x: [7_770_000, 10_000, 10_000],
    y: [49_440_000, 5_000, 5_000],
    d: [0, 10_000, 10_000],
    a: [2_000, 0, 0],
  });
  const makeProjector = (width, height) => ({
    frame: 0,
    camera: {
      center: [7.77, 49.44],
      zoom: 12,
      pitch: 55,
      bearing: 0,
      elevation: 200,
      terrain: 1.25,
      globe: false,
      mapOpacity: 1,
      contours: 1,
      satellite: 0,
      shade: 1,
    },
    width,
    height,
    globe: false,
    exaggeration: 1.25,
    resolution: 10,
    centerDepth: 1,
    merc: (mx, my, lift, out) => {
      const mx0 = (7.77 + 180) / 360;
      const my0 = (180 - (180 / Math.PI) * Math.log(Math.tan(Math.PI / 4 + (49.44 * Math.PI) / 360))) / 360;
      out[0] = width * 0.5 + (mx - mx0) * 3e7;
      out[1] = height * 0.5 + (my - my0) * 3e7 - lift * 0.04;
      out[2] = 1;
      return true;
    },
    lngLat: (lon, lat, lift = 0) => [
      width * 0.5 + (lon - 7.77) * 5000,
      height * 0.65 - (lat - 49.44) * 5000 - lift * 0.04,
      true,
    ],
  });

  // 1. Flat flyover with zero climbs (climbs: [])
  const flatFlySpec = sceneSpecSchema.parse({
    schemaVersion: '1.0',
    kind: 'flyover',
    locale: 'en',
    look: 'carbon',
    profile: {width: 1920, height: 1080, fps: 30, durationInFrames: 1},
    tiles: {dem: '/d', vector: '/v', satellite: null, demMaxZoom: 15, vectorMaxZoom: 14, satelliteMaxZoom: 17},
    credits: null,
    camera: {lon: [7.77], lat: [49.44], zoom: [12], pitch: [50], bearing: [0], elevation: [200], terrain: [1.25], globe: [0], mapOpacity: [1], contours: [1], satellite: [0]},
    channels: {
      head: [1000],
      headDot: [1],
      title: [0],
      counters: [1],
      km: [1.0],
      ascent: [0],
      beat: [0],
      grade: [0],
      unfold: [1],
      chart: [1],
      stats: [1],
      black: [0],
    },
    tracks: [],
    story: {
      title: {label: 'Aug 29, 2026', text: 'Flat Ride'},
      labels: {distance: 'Distance', ascent: 'Elevation gain', kmUnit: 'km', mUnit: 'm', peakAlt: '200 m'},
      unfold: {center: [7.77, 49.44], right: [1, 0], lineM: 2000, baseZ: 100, vertical: 1, minAlt: 180, altRange: 60},
      layout: {marginX: 112, topY: 88, bottomY: 918, routeLift: 4, readout: {box: [1348, 88, 1808, 218], stripTop: 122, stripBottom: 178}},
      totalM: 2000,
      profile: [0, 0, 0, 0],
      peakFraction: 0,
      climbs: [],
      stats: [{label: 'Distance', value: '2.0', unit: 'km'}],
    },
  });
  const flatOut = scores.flyover({
    spec: flatFlySpec,
    tracks: [track],
    frame: 0,
    channel: (name) => flatFlySpec.channels[name]?.[0] ?? 0,
    projector: makeProjector(1920, 1080),
    width: 1920,
    height: 1080,
    scale: 1,
  });
  assert.equal(flatOut.texts.filter((t) => t.id.startsWith('climb-')).length, 0);
  assert.equal(flatOut.ops.filter((op) => op.kind === 'stem').length, 0);
  assert.ok(flatOut.texts.some((t) => t.id === 'peak-alt'));

  // 2. 12-month strata in 9:16 portrait with opening and footer stats active
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const floors = months.map((label, k) => ({
    id: `2026-${String(k + 1).padStart(2, '0')}`,
    label,
    subLabel: `${(k + 1) * 120} km · ${k + 3}`,
    targetLift: k * 1200,
    step: 1200,
    trackIndices: [0],
  }));
  const strataChannels = {
    final: [1],
    opening: [1],
    stats: [1],
    fade: [1],
    black: [0],
  };
  for (let k = 0; k < 12; k++) {
    strataChannels[`floor${k}`] = [1];
    strataChannels[`label${k}`] = [1];
    strataChannels[`draw${k}`] = [1];
    strataChannels[`focus${k}`] = [k === 11 ? 1 : 0];
  }
  const strata12Spec = sceneSpecSchema.parse({
    ...flatFlySpec,
    kind: 'strata',
    profile: {width: 1080, height: 1920, fps: 30, durationInFrames: 1},
    channels: strataChannels,
    story: {
      corners: [
        [7.7, 49.4],
        [7.85, 49.4],
        [7.85, 49.5],
        [7.7, 49.5],
      ],
      floors,
      opening: {label: '120 rides · Jan — Dec 2026', text: 'Kaiserslautern'},
      stats: [
        {label: 'Rides', value: '120'},
        {label: 'Distance', value: '9,400', unit: 'km'},
        {label: 'Elevation', value: '88,000', unit: 'm'},
        {label: 'Hours', value: '340', unit: 'h'},
      ],
    },
  });
  const strata12Out = scores.strata({
    spec: strata12Spec,
    tracks: [track],
    frame: 0,
    channel: (name) => strata12Spec.channels[name]?.[0] ?? 0,
    projector: makeProjector(1080, 1920),
    width: 1080,
    height: 1920,
    scale: 1,
  });
  const tags12 = strata12Out.texts.filter((t) => t.id.startsWith('floor-label-'));
  assert.equal(tags12.length, 12);
  // Sorted bottom-to-top: verify minimum vertical spacing, header clearance, and footer clearance
  for (let i = 1; i < tags12.length; i++) {
    assert.ok(tags12[i - 1].y - tags12[i].y >= 28 - 1e-6);
  }
  const topFloorY = Math.min(...tags12.map((t) => t.y));
  const bottomFloorY = Math.max(...tags12.map((t) => t.y));
  // Instagram Story: the top and bottom 220 px of a 1080x1920 frame are covered.
  assert.ok(topFloorY >= 220 + 110 - 1e-6);

  // The 2x2 totals rest on the safe area (a label + value block is ~77 px tall)
  // and the floor labels stop above them.
  const statTexts = strata12Out.texts.filter((t) => t.id.startsWith('strata-stat-'));
  assert.equal(statTexts.length, 4);
  for (const t of statTexts) {
    assert.ok(t.y + 77 <= 1920 - 220 + 1e-6, `stat ${t.id} reaches into the reply bar`);
  }
  assert.ok(bottomFloorY <= Math.min(...statTexts.map((t) => t.y)) - 1e-6, 'labels overlap the stats');

  // 3. Stretch with dozens of short rides + --toward destination
  const manyRides = Array.from({length: 40}, (_, k) => ({
    trackIndex: 0,
    lengthM: 2000,
    beforeM: k * 2000,
    restAlpha: 0.25,
    restWidth: 1.2,
  }));
  const stretchSpec = sceneSpecSchema.parse({
    ...flatFlySpec,
    kind: 'stretch',
    channels: {
      laid: [80_000],
      opening: [0],
      counter: [0],
      km: [80],
      landed: [0.5],
      ghost: [1],
      ending: [1],
      fade: [1],
      black: [0],
    },
    story: {
      home: [7.77, 49.44],
      pullBearing: 90,
      totalM: 80_000,
      totalKm: 80,
      rides: manyRides,
      opening: {label: '40 rides · 80 km', text: 'Kaiserslautern'},
      counter: {label: 'Combined distance', unit: 'km'},
      ending: {label: '40 rides · 80 km', text: '80 km toward Heidelberg.', accent: 'Heidelberg'},
      destination: {name: 'Heidelberg', at: [7.81, 49.44], distanceM: 120_000},
    },
  });
  const stretchOut = scores.stretch({
    spec: stretchSpec,
    tracks: [track],
    frame: 0,
    channel: (name) => stretchSpec.channels[name]?.[0] ?? 0,
    projector: makeProjector(1920, 1080),
    width: 1920,
    height: 1080,
    scale: 1,
  });
  assert.ok(stretchOut.ops.some((op) => op.kind === 'pulse'));
  assert.ok(stretchOut.texts.some((t) => t.id === 'stretch-ending'));
  assert.ok(stretchOut.texts.some((t) => t.id === 'dest-tag'));
});
