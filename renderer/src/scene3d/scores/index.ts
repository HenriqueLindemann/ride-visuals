import type {DrawOp, Knockout} from '../core/draw';
import type {Projector} from '../core/projector';
import type {Track} from '../core/track';
import type {TextItem} from '../core/Typography';
import type {SceneSpec} from '../schema';
import {flyoverScore} from './flyover';
import {strataScore} from './strata';
import {stretchScore} from './stretch';

export type ScoreContext = {
  spec: SceneSpec;
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

export type Score = (ctx: ScoreContext) => ScoreOutput;

export const scores: Record<SceneSpec['kind'], Score> = {
  flyover: flyoverScore,
  stretch: stretchScore,
  strata: strataScore,
};
