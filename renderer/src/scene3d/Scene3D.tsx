import {useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react';
import {AbsoluteFill, cancelRender, continueRender, delayRender, staticFile, useCurrentFrame} from 'remotion';
import {drawKnockouts, drawOps} from './core/draw';
import {Scrim} from './core/Scrim';
import {textScaleFor} from './core/layout';
import {MapStage} from './core/MapStage';
import type {Camera, Projector} from './core/projector';
import {decodeTrack, type Track} from './core/track';
import {FONT_STACK, INK, Typography} from './core/Typography';
import {type SceneInput, type SceneSpec, sceneSpecSchema} from './schema';
import {runScore, type ScoreOutput} from './scores';

const LOAD_TIMEOUT_MS = 120_000;

type Loaded = {spec: SceneSpec; tracks: Track[]};

// One fetch and one decode per browser tab, shared by every frame it renders.
const loads = new Map<string, Promise<Loaded>>();
function loadScene(url: string): Promise<Loaded> {
  let pending = loads.get(url);
  if (!pending) {
    const origin = new URL(url).origin;
    const resolveTile = (path: string) => (path.startsWith('/') ? `${origin}${path}` : path);
    pending = fetch(url)
      .then((response) => {
        if (!response.ok) throw new Error(`Scene spec ${url}: HTTP ${response.status}`);
        return response.json();
      })
      .then((json) => {
        const spec = sceneSpecSchema.parse(json);
        spec.tiles.dem = resolveTile(spec.tiles.dem);
        spec.tiles.vector = resolveTile(spec.tiles.vector);
        if (spec.tiles.satellite) spec.tiles.satellite = resolveTile(spec.tiles.satellite);
        return {spec, tracks: spec.tracks.map(decodeTrack)};
      })
      .catch((error) => {
        loads.delete(url);
        throw error;
      });
    loads.set(url, pending);
  }
  return pending;
}

let fontReady: Promise<void> | null = null;
function loadFont(): Promise<void> {
  fontReady ??= new FontFace('Geist', `url(${staticFile('scene3d/Geist-Variable.woff2')})`, {weight: '100 900'})
    .load()
    .then((face) => {
      document.fonts.add(face);
    });
  return fontReady;
}

function cameraAt(spec: SceneSpec, frame: number): Camera {
  const c = spec.camera;
  const i = Math.max(0, Math.min(c.zoom.length - 1, frame));
  return {
    center: [c.lon[i], c.lat[i]],
    zoom: c.zoom[i],
    pitch: c.pitch[i],
    bearing: c.bearing[i],
    elevation: c.elevation[i],
    terrain: c.terrain[i],
    globe: c.globe[i] >= 0.5,
    mapOpacity: c.mapOpacity[i],
    contours: c.contours[i],
    satellite: c.satellite[i],
    shade: c.shade?.[i] ?? 1,
  };
}

export const Scene3D = ({specUrl, width, height}: SceneInput) => {
  const frame = useCurrentFrame();
  const [scene, setScene] = useState<Loaded | null>(null);
  const [loadHandle] = useState(() => delayRender('scene spec and font', {timeoutInMilliseconds: LOAD_TIMEOUT_MS}));
  const [projector, setProjector] = useState<Projector | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const textRef = useRef<HTMLDivElement>(null);
  const pending = useRef<{frame: number; handle: number} | null>(null);

  useEffect(() => {
    Promise.all([loadScene(specUrl), loadFont()])
      .then(([loaded]) => {
        setScene(loaded);
        continueRender(loadHandle);
      })
      .catch((error) => {
        console.error(error);
        cancelRender(error);
      });
  }, [specUrl, loadHandle]);

  // Hold each frame until the overlay is drawn with that frame's projector.
  useLayoutEffect(() => {
    if (pending.current && pending.current.frame !== frame) continueRender(pending.current.handle);
    pending.current = {frame, handle: delayRender(`overlay ${frame}`, {timeoutInMilliseconds: LOAD_TIMEOUT_MS})};
  }, [frame]);

  useEffect(
    () => () => {
      if (pending.current) {
        continueRender(pending.current.handle);
        pending.current = null;
      }
    },
    [],
  );

  const camera = useMemo(() => (scene ? cameraAt(scene.spec, frame) : null), [scene, frame]);
  const scale = Math.min(width, height) / 1080;
  const textScale = textScaleFor(width, height);

  const output: ScoreOutput | null = useMemo(() => {
    if (!scene || !projector || projector.frame !== frame) return null;
    const channels = scene.spec.channels;
    return runScore({
      spec: scene.spec,
      tracks: scene.tracks,
      frame,
      channel: (name) => {
        const values = channels[name];
        if (!values) throw new Error(`Missing channel: ${name}`);
        return values[Math.max(0, Math.min(values.length - 1, frame))];
      },
      projector,
      width,
      height,
      scale,
      textScale,
    });
  }, [scene, projector, frame, width, height, scale, textScale]);

  useLayoutEffect(() => {
    if (!output || !projector) return;
    const canvas = canvasRef.current!;
    const dpr = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(width * dpr)) {
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
    }
    const ctx = canvas.getContext('2d')!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    drawOps(ctx, projector, output.ops);
    drawKnockouts(ctx, output.knockouts ?? [], textRef.current, width);
  }, [output, projector, width, height]);

  useEffect(() => {
    if (output && pending.current?.frame === frame) {
      continueRender(pending.current.handle);
      pending.current = null;
    }
  }, [output, frame]);

  return (
    <AbsoluteFill style={{background: INK.ink, overflow: 'hidden', fontFamily: FONT_STACK}}>
      {scene && camera ? (
        <MapStage spec={scene.spec} frame={frame} camera={camera} width={width} height={height} onProjector={setProjector} />
      ) : null}
      {output?.scrim ? <Scrim {...output.scrim} /> : null}
      <canvas ref={canvasRef} style={{position: 'absolute', left: 0, top: 0, width, height}} />
      {output ? <Typography ref={textRef} items={output.texts} scale={textScale} /> : null}
      {/* Cinematic vignette: draws the eye to the centre and keeps edges quiet. */}
      <AbsoluteFill
        style={{background: 'radial-gradient(ellipse 85% 80% at 50% 48%, rgba(0,0,0,0) 58%, rgba(0,0,0,0.5) 100%)'}}
      />
      {scene?.spec.credits ? (
        <div
          style={{
            position: 'absolute',
            right: 16 * scale,
            bottom: 12 * scale,
            fontSize: 11 * scale,
            color: INK.paper3,
            letterSpacing: '0.02em',
          }}
        >
          {scene.spec.credits}
        </div>
      ) : null}
      <AbsoluteFill style={{background: '#000', opacity: output?.black ?? 1}} />
    </AbsoluteFill>
  );
};
