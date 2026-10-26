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
const {decodeTrack, extentUpTo, indexAtDistance, lodFor, pointAtDistance} = await import('../src/scene3d/core/track.ts');
const {PORTRAIT_TEXT, spread} = await import('../src/scene3d/core/layout.ts');
const {sceneSpecSchema} = await import('../src/scene3d/schema.ts');
const {scores} = await import('../src/scene3d/scores/index.ts');
const {plateAt, ridesAt} = await import('../src/scene3d/scores/strata.ts');

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
      layout: {marginX: 112, topY: 88, countersY: 88, routeLift: 4, trace: [1448, 213, 1808, 293]},
      totalM: 2000,
      profile: [0, 0.5, 1, 0.8],
      peakFraction: 0.66,
      climbs: [{lon: 7.78, lat: 49.45, alt: 400, startAlt: 200, startM: 200, endM: 1400, hero: true}],
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
    textScale: 1,
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
    textScale: 1,
  });
  assert.equal(flyOpening.ops.filter((op) => op.kind === 'track').length, 0);
  assert.equal(flyOpening.ops.filter((op) => op.kind === 'dot').length, 1);

  const plateCorners = [
    [7.7, 49.4],
    [7.85, 49.4],
    [7.85, 49.5],
    [7.7, 49.5],
  ];
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
      home: [7.76, 49.44],
      floors: [
        {id: '2026-07', label: 'July', value: '400', unit: 'km', targetLift: 0, corners: plateCorners, trackIndices: [0]},
        {id: '2026-08', label: 'August', value: '620', unit: 'km', targetLift: 5000, corners: plateCorners, trackIndices: [0]},
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
    textScale: 1,
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
      layout: {marginX: 112, topY: 88, countersY: 88, routeLift: 4, trace: [1448, 213, 1808, 293]},
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
    textScale: 1,
  });
  assert.equal(flatOut.texts.filter((t) => t.id.startsWith('trace-')).length, 0);
  assert.equal(flatOut.ops.filter((op) => op.kind === 'stem').length, 0);
  assert.ok(flatOut.texts.some((t) => t.id === 'peak-alt'));

  // 2. 12-month strata in 9:16 portrait with opening and footer stats active
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const floors = months.map((label, k) => ({
    id: `2026-${String(k + 1).padStart(2, '0')}`,
    label,
    value: `${(k + 1) * 120}`,
    unit: 'km',
    targetLift: k * 1200,
    step: 1200,
    corners: [
      [7.75, 49.4],
      [7.85, 49.4],
      [7.85, 49.5],
      [7.75, 49.5],
    ],
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
      home: [7.76, 49.44],
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
    textScale: PORTRAIT_TEXT,
  });
  // A metric block: label line (17) + gap (10) + its value line, at the portrait text scale.
  const blockBottom = (t) => t.y + (27 + t.size) * PORTRAIT_TEXT;
  const floors12 = strata12Out.texts.filter((t) => t.id.startsWith('floor-label-')).sort((a, b) => a.y - b.y);
  assert.equal(floors12.length, 12);
  // Twelve floors still read as figures (never below the tag size) and never touch.
  for (let i = 0; i < floors12.length; i++) {
    assert.ok(floors12[i].size >= 22);
    if (i > 0) assert.ok(floors12[i].y >= blockBottom(floors12[i - 1]), `floor ${i} touches the one above`);
  }
  // Instagram Story: the top and bottom 220 px of a 1080x1920 frame are covered.
  assert.ok(floors12[0].y >= 220);
  // In the stack's order (newest on top), each leader leaves its label level, and
  // the leaders keep that order all the way to their plates: none cross.
  assert.deepEqual(floors12.map((t) => t.id), months.map((_, k) => `floor-label-${11 - k}`));
  const leaders = strata12Out.ops.filter((op) => op.kind === 'screen-path').sort((a, b) => a.xy[1] - b.xy[1]);
  assert.ok(leaders.length > 0);
  for (const [i, {xy}] of leaders.entries()) {
    assert.equal(xy[1], xy[3]);
    if (i > 0) assert.ok(xy.at(-1) >= leaders[i - 1].xy.at(-1), `leader ${i} crosses the one above`);
  }

  // The 2x2 totals rest on the safe area and the floor column stops above them.
  const statTexts = strata12Out.texts.filter((t) => t.id.startsWith('strata-stat-'));
  assert.equal(statTexts.length, 4);
  for (const t of statTexts) {
    assert.ok(blockBottom(t) <= 1920 - 220 + 1e-6, `stat ${t.id} reaches into the reply bar`);
  }
  assert.ok(blockBottom(floors12.at(-1)) <= Math.min(...statTexts.map((t) => t.y)), 'floors overlap the totals');

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
    textScale: 1,
  });
  assert.ok(stretchOut.ops.some((op) => op.kind === 'pulse'));
  assert.ok(stretchOut.texts.some((t) => t.id === 'stretch-ending'));
  assert.ok(stretchOut.texts.some((t) => t.id === 'dest-tag'));

  // 4. 12-month ascent with extreme low-gain months (+6 m, +28 m, +303 m) in 16:9 and 9:16
  assert.deepEqual(spread([100, 102, 104], 20, 50, 300), [82, 102, 122]);
  const monthGains = [4660, 303, 2800, 5449, 28, 6, 4208, 6616, 7126, 3724, 2418, 1900];
  let zAcc = 0;
  let xAcc = 0;
  const profX = [0];
  const profZ = [0];
  const ascentPeriods = monthGains.map((g, k) => {
    const x0 = xAcc;
    const x1 = xAcc + (g < 100 ? 120 : 3000);
    const z0 = zAcc;
    const z1 = zAcc + g;
    xAcc = x1;
    zAcc = z1;
    profX.push(Math.round((x1 - x0) * 10));
    profZ.push(Math.round((z1 - z0) * 10));
    return {
      label: months[k].toUpperCase(),
      x: [x0, x1],
      z: [z0, z1],
      value: `+${g} m`,
      t: 4 + k * 2,
    };
  });
  for (const [w, h, tScale] of [
    [1920, 1080, 1],
    [1080, 1920, PORTRAIT_TEXT],
  ]) {
    const ascentSpec = sceneSpecSchema.parse({
      ...flatFlySpec,
      kind: 'ascent',
      profile: {width: w, height: h, fps: 30, durationInFrames: 1200},
      channels: {
        opening: [0],
        counter: [1],
        climbed: [zAcc],
        head: [xAcc],
        tail: [xAcc],
        live: [0],
        fold: [0],
        ruler: [1],
        stats: [1],
        fade: [1],
        black: [0],
      },
      story: {
        home: [7.77, 49.44],
        axis: 90,
        scale: 0.1,
        profile: {x: profX, z: profZ},
        rides: [{x0: 0, track: 0, period: 'December'}],
        periods: ascentPeriods,
        groups: [{label: '2026', x: [0, xAcc], z: [0, zAcc], value: `+${zAcc} m`, t: 28}],
        heights: [],
        ruler: {at: 8849, count: 4},
        opening: {label: '2026', text: 'Kaiserslautern'},
        counter: {label: 'Ascent', unit: 'm'},
        stats: [{label: 'Ascent', value: `+${zAcc}`, unit: 'm'}],
      },
    });
    const climbOut = scores.ascent({
      spec: ascentSpec,
      tracks: [track],
      frame: 900,
      channel: (name) => (name === 'fold' ? 0 : ascentSpec.channels[name][0]),
      projector: makeProjector(w, h),
      width: w,
      height: h,
      scale: 1,
      textScale: tScale,
    });
    const baseTags = climbOut.texts.filter((t) => /^ascent-period-\d+$/.test(t.id));
    assert.equal(baseTags.length, 12, `all 12 months must appear on base (${w}x${h})`);
    for (let i = 0; i < baseTags.length; i++) {
      assert.equal(baseTags[i].opacity, 1, `month ${i} on base must have full uniform opacity`);
      if (i > 0) assert.ok(baseTags[i].x - baseTags[i - 1].x >= 35 * tScale, `month ${i} overlaps month ${i - 1} on base`);
    }

    const foldOut = scores.ascent({
      spec: ascentSpec,
      tracks: [track],
      frame: 1100,
      channel: (name) => (name === 'fold' ? 1 : ascentSpec.channels[name][0]),
      projector: makeProjector(w, h),
      width: w,
      height: h,
      scale: 1,
      textScale: tScale,
    });
    const lineTags = foldOut.texts.filter((t) => t.id.startsWith('ascent-period-line-')).sort((a, b) => a.y - b.y);
    assert.equal(lineTags.length, 12, `all 12 months must appear on folded line (${w}x${h})`);
    for (let i = 0; i < lineTags.length; i++) {
      assert.equal(lineTags[i].opacity, 1, `month ${i} on folded line must have full uniform opacity`);
      if (i > 0) assert.ok(lineTags[i].y - lineTags[i - 1].y >= 38 * tScale, `month ${i} overlaps on folded line`);
    }

    // A done month is marked by a post from the ground up to where it ends.
    const [first] = ascentPeriods;
    const isPost = (op) => op.kind === 'plane' && op.strokes[0].length === 4 && op.strokes[0][0] === first.x[1] && op.strokes[0][2] === first.x[1];
    assert.deepEqual([...climbOut.ops.find(isPost).strokes[0]], [first.x[1], 0, first.x[1], first.z[1]]);

    // A level is drawn to its name and goes with it; the last one stays.
    const level = (key, at, t) => ({key, at, shape: 'level', strokes: [[[-0.15 * at, at], [xAcc, at]]], t0: t, t, named: t + 0.6, glyph: null, name: key, value: `${at} m`});
    const levelSpec = sceneSpecSchema.parse({...ascentSpec, story: {...ascentSpec.story, heights: [level('airliner', 11000, 5), level('concorde', 18300, 12)]}});
    const levelsAt = (seconds) => {
      const out = scores.ascent({spec: levelSpec, tracks: [track], frame: seconds * 30, channel: (name) => (name === 'fold' ? 0 : levelSpec.channels[name][0]), projector: makeProjector(w, h), width: w, height: h, scale: 1, textScale: tScale});
      return [11000, 18300].filter((z) => out.ops.some((op) => op.kind === 'plane' && op.strokes[0].length === 4 && op.strokes[0][1] === z && op.strokes[0][3] === z));
    };
    assert.deepEqual(levelsAt(8), [11000]);
    assert.deepEqual(levelsAt(20), [18300]);
  }
});

test('strata plates follow their rides, never shrink, never cut a line, and reach out to a far start', () => {
  // A ride out east from home, then one starting at the far east end riding back.
  const line = (x0, dx) => decodeTrack({x: [x0, ...Array(40).fill(dx)], y: [49_440_000, ...Array(40).fill(0)], d: [0, ...Array(40).fill(9_000)]});
  const tracks = [line(7_700_000, 3_000), line(7_900_000, -3_000)];
  const corners = [
    [7.68, 49.43],
    [7.92, 49.43],
    [7.92, 49.45],
    [7.68, 49.45],
  ];
  const fps = 30;
  const draws = Array.from({length: 4 * fps}, (_, f) => span(f, 0.5 * fps, 3 * fps));
  let prev = null;
  let prevSpeed = 0;
  for (let f = 0; f < draws.length; f++) {
    const [[w, s], , [e, n]] = plateAt(tracks, draws, f, fps, corners);
    // Before the first line, just the margin around its start.
    if (draws[f] === 0) assert.ok(Math.abs(w - 7.68) < 1e-9 && Math.abs(e - 7.72) < 1e-9, `frame ${f}: plate moves ahead of its rides`);
    // The first ride's line, which starts on the plate, is never cut.
    const [ride] = ridesAt(tracks, draws[f]);
    if (ride.head > 0) {
      const [w1, s1, e1, n1] = extentUpTo(ride.track, ride.head * ride.track.length);
      assert.ok(w <= w1 && s <= s1 && e >= e1 && n >= n1, `frame ${f}: the line pokes out of its plate`);
    }
    if (prev) {
      assert.ok(w <= prev[0] + 1e-12 && s <= prev[1] + 1e-12 && e >= prev[2] - 1e-12 && n >= prev[3] - 1e-12, `frame ${f}: plate shrinks`);
      // Edges change speed gently.
      const speed = Math.max(prev[0] - w, e - prev[2]) * fps;
      assert.ok(Math.abs(speed - prevSpeed) * fps < 40, `frame ${f}: edge jerks`);
      prevSpeed = speed;
    }
    prev = [w, s, e, n];
  }
  // Finished, the plate is exactly the floor's: it has reached the far start.
  assert.deepEqual(plateAt(tracks, draws, draws.length - 1, fps, corners), corners);
});
