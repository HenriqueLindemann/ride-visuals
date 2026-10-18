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
  scale: number;
};

export type ScoreOutput = {
  ops: DrawOp[];
  texts: TextItem[];
  black: number;
  /** Screen boxes under fixed text where drawn lines fade out (legibility). */
  knockouts?: Knockout[];
  /** Screen furniture drawn after the knockouts (e.g. a chart inside a cleared box). */
  overlay?: DrawOp[];
};

export type Score = (ctx: ScoreContext) => ScoreOutput;

export const scores: Record<SceneSpec['kind'], Score> = {
  flyover: flyoverScore,
  stretch: stretchScore,
  strata: strataScore,
};
