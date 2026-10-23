/**
 * The shared frame layout and type scale of the 3D scenes. Sizes are px at a
 * 1080 px short side: scores multiply layout by `scale` and text by `textScale`.
 */
import type {MetricItem} from './Typography';

/**
 * Instagram Story safe area at 1080x1920: the profile row on top and the reply
 * bar below each cover this much, so portrait text stays inside. Mirrors
 * INSTAGRAM_STORY in ride_visuals/video/instagram.py.
 */
export const STORY_SAFE = 220;

/**
 * Frame margins: the sides, and one vertical margin shared by the top and the
 * bottom (the safe area in portrait). Mirrors LAYOUT_1080 in scene3d/flyover.py.
 */
export const frameMargins = (portrait: boolean) => ({x: portrait ? 72 : 112, y: portrait ? STORY_SAFE : 88});

/**
 * One family, five sizes (px at a 1080 px short side): small caps labels
 * (also the floor for units), names pinned to the map, figures in a list,
 * opening and closing sentences, and live counters and totals.
 */
export const TYPE = {label: 13, tag: 22, figure: 30, title: 48, number: 68} as const;
/** The label's line box and the gap under it (Typography sets both explicitly). */
export const LABEL_LINE = 17;
export const LABEL_GAP = 10;

/**
 * Text, and what is sized by it, is set this much larger in portrait: a phone
 * shows a 9:16 frame's 1080 px across a few centimetres. Mirrors
 * PORTRAIT_TEXT in scene3d/flyover.py.
 */
export const PORTRAIT_TEXT = 1.4;

/** Scale for text at this frame size (margins and strokes use the plain scale). */
export const textScaleFor = (width: number, height: number) =>
  (Math.min(width, height) / 1080) * (height > width ? PORTRAIT_TEXT : 1);

/** Height of a metric block (label line, gap, value line), px at text scale 1. */
export const metricHeight = (size: number) => LABEL_LINE + LABEL_GAP + size;

/** Vertical gap between two rows of totals, px at text scale 1. */
const TOTALS_ROW_GAP = 34;

type Total = {label: string; value: string; unit?: string};

/**
 * Closing totals, each centred in one of equal columns between x0 and x1, so
 * the block sits symmetric under what it sums up: one row, or two when four
 * share a portrait frame. Placed by its `top`, or resting on its `bottom`.
 */
export function totalsGrid(
  stats: Total[],
  {x0, x1, top, bottom, portrait, textScale, opacity, id}: {
    x0: number;
    x1: number;
    top?: number;
    bottom?: number;
    portrait: boolean;
    textScale: number;
    opacity: number;
    id: string;
  },
): {items: MetricItem[]; top: number} {
  const rows = portrait && stats.length === 4 ? 2 : 1;
  const cols = Math.ceil(stats.length / rows);
  // The number size, unless the longest value would not fit its column.
  const longest = Math.max(...stats.map((s) => s.value.length + 0.5 * (s.unit?.length ?? 0)), 1);
  const size = Math.min(TYPE.number, (0.88 * (x1 - x0)) / cols / textScale / (0.56 * longest + 0.3));
  const pitch = (metricHeight(size) + TOTALS_ROW_GAP) * textScale;
  const blockHeight = metricHeight(size) * textScale + (rows - 1) * pitch;
  const y0 = Math.round(top ?? (bottom ?? 0) - blockHeight);
  const items = stats.map((stat, idx): MetricItem => ({
    kind: 'metric',
    id: `${id}-${idx}`,
    x: x0 + ((idx % cols) + 0.5) * ((x1 - x0) / cols),
    y: Math.round(y0 + Math.floor(idx / cols) * pitch),
    label: stat.label,
    value: stat.value,
    unit: stat.unit,
    align: 'center',
    size,
    opacity,
  }));
  return {items, top: y0};
}
