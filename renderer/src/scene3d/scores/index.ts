import type {RouteDrape} from '../core/drape';
import type {DrawOp, Knockout} from '../core/draw';
import type {Projector} from '../core/projector';
import type {Track} from '../core/track';
import type {TextItem} from '../core/Typography';
import type {SceneKind, SceneSpecOf} from '../schema';
import {ascentScore} from './ascent';
import {flyoverDrape, flyoverScore} from './flyover';
import {strataScore} from './strata';
import {stretchScore} from './stretch';
import {territoryScore} from './territory';

/** What a scene knows before the map paints: its spec and this frame's channels. */
export type DrapeContext<K extends SceneKind = SceneKind> = {
  spec: SceneSpecOf<K>;
  tracks: Track[];
  frame: number;
  channel: (name: string) => number;
  /** Frame size over a 1080 px short side: margins, strokes, marks. */
  scale: number;
};

export type ScoreContext<K extends SceneKind = SceneKind> = DrapeContext<K> & {
  projector: Projector;
  width: number;
  height: number;
  /** The same as `scale` for text and what is sized by it, larger in portrait (see textScaleFor). */
  textScale: number;
};

export type ScoreOutput = {
  ops: DrawOp[];
  texts: TextItem[];
  black: number;
  /** Fixed text the drawn lines give way to (legibility). */
  knockouts?: Knockout[];
  /** 0..1: the land darkens towards the top / bottom edge, under the lines, so text there reads. */
  scrim?: {top?: number; bottom?: number; strength?: number; far?: number};
};

export type Score<K extends SceneKind> = (ctx: ScoreContext<K>) => ScoreOutput;

export const scores: {[K in SceneKind]: Score<K>} = {
  flyover: flyoverScore,
  stretch: stretchScore,
  strata: strataScore,
  territory: territoryScore,
  ascent: ascentScore,
};

/** Run the score of the spec's own kind (TS cannot correlate the lookup with the union). */
export function runScore(ctx: ScoreContext): ScoreOutput {
  return (scores[ctx.spec.kind] as Score<SceneKind>)(ctx);
}

/** A route the map draws itself, draped on the relief, per scene kind (see drape.ts). */
const drapes: {[K in SceneKind]?: (ctx: DrapeContext<K>) => RouteDrape | null} = {
  flyover: flyoverDrape,
};

/** The route the map drapes this frame, if the spec's scene has one. */
export function runDrape(ctx: DrapeContext): RouteDrape | null {
  const drape = drapes[ctx.spec.kind] as ((ctx: DrapeContext) => RouteDrape | null) | undefined;
  return drape ? drape(ctx) : null;
}
