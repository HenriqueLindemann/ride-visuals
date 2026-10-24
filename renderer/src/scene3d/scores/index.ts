import type {DrawOp, Knockout} from '../core/draw';
import type {Projector} from '../core/projector';
import type {Track} from '../core/track';
import type {TextItem} from '../core/Typography';
import type {SceneKind, SceneSpecOf} from '../schema';
import {flyoverScore} from './flyover';
import {strataScore} from './strata';
import {stretchScore} from './stretch';

export type ScoreContext<K extends SceneKind = SceneKind> = {
  spec: SceneSpecOf<K>;
  tracks: Track[];
  frame: number;
  channel: (name: string) => number;
  projector: Projector;
  width: number;
  height: number;
  /** Frame size over a 1080 px short side: margins, strokes, marks. */
  scale: number;
  /** The same for text and what is sized by it, larger in portrait (see textScaleFor). */
  textScale: number;
};

export type ScoreOutput = {
  ops: DrawOp[];
  texts: TextItem[];
  black: number;
  /** Fixed text the drawn lines give way to (legibility). */
  knockouts?: Knockout[];
};

export type Score<K extends SceneKind> = (ctx: ScoreContext<K>) => ScoreOutput;

export const scores: {[K in SceneKind]: Score<K>} = {
  flyover: flyoverScore,
  stretch: stretchScore,
  strata: strataScore,
};

/** Run the score of the spec's own kind (TS cannot correlate the lookup with the union). */
export function runScore(ctx: ScoreContext): ScoreOutput {
  return (scores[ctx.spec.kind] as Score<SceneKind>)(ctx);
}
