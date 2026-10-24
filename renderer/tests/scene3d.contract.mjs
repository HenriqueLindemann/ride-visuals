import {execFileSync} from 'node:child_process';
import {registerHooks} from 'node:module';
import {existsSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
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

const {EARTH_CIRCUMFERENCE, metersPerPixel} = await import('../src/scene3d/core/geo.ts');
const {frameMargins, PORTRAIT_TEXT, STORY_SAFE, textScaleFor} = await import('../src/scene3d/core/layout.ts');
const {decodeTrack} = await import('../src/scene3d/core/track.ts');
const {sceneSpecSchema} = await import('../src/scene3d/schema.ts');
const {runScore} = await import('../src/scene3d/scores/index.ts');

test('Python 3D directors emit SceneSpecs that validate against sceneSpecSchema and execute in scores', () => {
  const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
  const venvPython = resolve(repoRoot, '.venv/bin/python');
  const pythonBin = existsSync(venvPython) ? venvPython : 'python3';
  const script = `
import datetime, json, numpy as np
from ride_visuals.scene3d import (
    FlyoverMetadata, RideTrack, SceneRide,
    build_flyover_spec, build_strata_spec, build_stretch_spec,
)

s = np.linspace(0.0, 20000.0, 200)
lon = 7.77 + (s / 111320.0) * 0.7
lat = 49.44 + (s / 110540.0) * 0.3
alt = 200.0 + 180.0 * np.sin(s / 3000.0)
track = RideTrack.from_arrays(lon, lat, alt, s / 8.0)

fly = build_flyover_spec(
    track,
    metadata=FlyoverMetadata(activity_id=1, name="Test", distance_m=20000.0, elevation_gain_m=360.0, moving_time_s=2500.0),
    fps=10,
    offline=True,
).to_json()

rides = [
    SceneRide(
        activity_id=i + 1,
        start_date=datetime.datetime(2026, (i % 3) + 1, 10, tzinfo=datetime.timezone.utc),
        track=track,
        distance_m=20000.0,
        elevation_gain_m=360.0,
        moving_time_s=2500.0,
    )
    for i in range(3)
]
stretch = build_stretch_spec(rides, fps=10, toward="49.50,8.40", offline=True).to_json()
strata = build_strata_spec(rides, fps=10, period="month", offline=True).spec.to_json()
print(json.dumps([fly, stretch, strata]))
`;
  const raw = execFileSync(pythonBin, ['-c', script], {
    cwd: repoRoot,
    env: {...process.env, PYTHONPATH: resolve(repoRoot, 'src')},
    encoding: 'utf-8',
    maxBuffer: 32 * 1024 * 1024,
  });
  const specs = JSON.parse(raw);
  assert.equal(specs.length, 3);

  // Every story field a score reads is part of the contract: dropping one
  // from a real director's output fails on load, naming the field.
  for (const [kind, path] of [['flyover', ['layout', 'topY']], ['stretch', ['counter', 'unit']], ['strata', ['floors', 0, 'value']]]) {
    const broken = structuredClone(specs.find((s) => s.kind === kind));
    const parent = path.slice(0, -1).reduce((node, key) => node[key], broken.story);
    delete parent[path.at(-1)];
    const result = sceneSpecSchema.safeParse(broken);
    assert.equal(result.success, false, `${kind} story without ${path.join('.')} must not validate`);
    assert.deepEqual(result.error.issues[0].path, ['story', ...path]);
  }

  for (const unparsed of specs) {
    const spec = sceneSpecSchema.parse(unparsed);
    const decodedTracks = spec.tracks.map(decodeTrack);
    const midFrame = Math.floor(spec.profile.durationInFrames / 2);
    const projector = {
      frame: midFrame,
      camera: {
        center: [spec.camera.lon[midFrame], spec.camera.lat[midFrame]],
        zoom: spec.camera.zoom[midFrame],
        pitch: spec.camera.pitch[midFrame],
        bearing: spec.camera.bearing[midFrame],
        elevation: spec.camera.elevation[midFrame],
        terrain: spec.camera.terrain[midFrame],
        globe: spec.camera.globe[midFrame] > 0.5,
        mapOpacity: spec.camera.mapOpacity[midFrame],
        contours: spec.camera.contours[midFrame],
        satellite: spec.camera.satellite[midFrame],
        shade: spec.camera.shade ? spec.camera.shade[midFrame] : 1,
      },
      width: spec.profile.width,
      height: spec.profile.height,
      globe: spec.camera.globe[midFrame] > 0.5,
      exaggeration: spec.camera.terrain[midFrame],
      resolution: 10,
      centerDepth: 1,
      merc: (mx, my, lift, out) => {
        out[0] = 960;
        out[1] = 540 - lift * 0.02;
        out[2] = 1;
        return true;
      },
      lngLat: (lon, lat, lift = 0) => [960 + (lon - 7.77) * 2000, 540 - (lat - 49.44) * 2000 - lift * 0.02, true],
    };
    const out = runScore({
      spec,
      tracks: decodedTracks,
      frame: midFrame,
      channel: (name) => spec.channels[name]?.[midFrame] ?? 0,
      projector,
      width: spec.profile.width,
      height: spec.profile.height,
      scale: 1,
      textScale: textScaleFor(spec.profile.width, spec.profile.height),
    });
    assert.ok(Array.isArray(out.ops) && out.ops.length > 0);
    assert.ok(Array.isArray(out.texts));
  }
});

test('director and player share map scale and layout, so offline framing matches the render', () => {
  const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
  const venvPython = resolve(repoRoot, '.venv/bin/python');
  const pythonBin = existsSync(venvPython) ? venvPython : 'python3';
  const raw = execFileSync(
    pythonBin,
    [
      '-c',
      `
import json
from ride_visuals.scene3d.camera import EARTH_CIRCUMFERENCE_M, meters_per_pixel
from ride_visuals.scene3d.flyover import LAYOUT_1080, PORTRAIT_TEXT
from ride_visuals.video.instagram import INSTAGRAM_STORY
print(json.dumps({
  "portraitText": PORTRAIT_TEXT,
  "storySafe": [INSTAGRAM_STORY.profile_safe_px, INSTAGRAM_STORY.reply_safe_px],
  "margins": {k: [LAYOUT_1080[k]["margin_x"], LAYOUT_1080[k]["margin_y"]] for k in ("portrait", "landscape")},
  "circumference": EARTH_CIRCUMFERENCE_M,
  "mpp": [[z, lat, float(meters_per_pixel(z, lat))] for z, lat in [(8, 60.0), (10, 49.44), (12.4, 49.44), (14, -33.9)]],
}))
      `,
    ],
    {cwd: repoRoot, env: {...process.env, PYTHONPATH: resolve(repoRoot, 'src')}, encoding: 'utf-8'},
  );
  const data = JSON.parse(raw);

  // The occlusion, framing and layout maths only agree when both sides use the
  // same Earth size and metres-per-pixel; a silent drift here is invisible
  // until the overlays stop lining up with the rendered map.
  assert.ok(
    Math.abs(data.circumference - EARTH_CIRCUMFERENCE) < 1.0,
    `Earth circumference drifted: Python ${data.circumference} vs TS ${EARTH_CIRCUMFERENCE}`,
  );
  // The flyover's layout is planned in Python and drawn in TS: same margins, safe area and text scale.
  assert.equal(data.portraitText, PORTRAIT_TEXT);
  assert.deepEqual(data.storySafe, [STORY_SAFE, STORY_SAFE]);
  for (const [key, portrait] of [['portrait', true], ['landscape', false]]) {
    const m = frameMargins(portrait);
    assert.deepEqual(data.margins[key], [m.x, m.y], `${key} margins drifted`);
  }
  for (const [zoom, lat, mpp] of data.mpp) {
    const ts = metersPerPixel(zoom, lat);
    assert.ok(
      Math.abs(mpp - ts) <= 1e-6 * Math.max(1, ts),
      `meters_per_pixel(${zoom}, ${lat}) drifted: Python ${mpp} vs TS ${ts}`,
    );
  }
});
