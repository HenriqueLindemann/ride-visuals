import type {CSSProperties, Ref} from 'react';
import {LABEL_GAP, LABEL_LINE, TYPE} from './layout';

/** One warm accent on carbon black; everything else is paper at three strengths. */
export const INK = {
  ink: '#0A0A09',
  paper: '#F3EFE8',
  paper2: 'rgba(243, 239, 232, 0.62)',
  paper3: 'rgba(243, 239, 232, 0.38)',
  hairline: 'rgba(243, 239, 232, 0.22)',
  accent: '#FF5A1F',
  accentRGB: [255, 90, 31] as const,
  warmRGB: [222, 176, 146] as const,
  paperRGB: [243, 239, 232] as const,
};

export const FONT_STACK = "'Geist', ui-sans-serif, system-ui, sans-serif";

const mix = (a: readonly number[], b: readonly number[], t: number) =>
  `rgb(${a.map((v, i) => Math.round(v + (b[i] - v) * Math.min(1, Math.max(0, t)))).join(',')})`;

const NUMERIC: CSSProperties = {fontVariantNumeric: 'tabular-nums', fontFeatureSettings: "'tnum' 1"};

/** Shared entrance: fade in while settling up a few pixels (opacity drives both). */
const entrance = (opacity: number, scale: number): CSSProperties => ({
  opacity,
  transform: `translateY(${(1 - opacity) * 10 * scale}px)`,
});

/** A sentence with an optional small label above it (either may be empty); one word may take the accent. */
export type CaptionItem = {
  kind: 'caption';
  id: string;
  x: number;
  y: number;
  label?: string;
  text: string;
  accent?: string;
  align?: 'left' | 'center' | 'right';
  size?: number;
  maxWidth?: number;
  opacity: number;
};

/** A number with a unit and a small label, counting is done by the score. */
export type MetricItem = {
  kind: 'metric';
  id: string;
  x: number;
  y: number;
  label: string;
  value: string;
  unit?: string;
  align?: 'left' | 'center' | 'right';
  size?: number;
  /** 0..1: the value turns to the accent (the figure a highlight is about). */
  accent?: number;
  opacity: number;
};

/** A label pinned to a point on screen by a hairline leader. */
export type TagItem = {
  kind: 'tag';
  id: string;
  /** Anchor point (px). */
  x: number;
  y: number;
  /** Leader length (px); the text sits at its far end. */
  leader: number;
  /** Omit the straight DOM leader when the score draws an angled leader on canvas. */
  customLeader?: boolean;
  direction: 'up' | 'down' | 'left' | 'right';
  text: string;
  sub?: string;
  /** Font size of `text` (px at scale 1); defaults to `TYPE.tag`. */
  size?: number;
  /** 0..1: the sub line comes in on its own (e.g. a figure once it is final). */
  subOpacity?: number;
  /** Wrap the name (balanced) to stay this wide (px), e.g. inside the frame's margin. */
  maxWidth?: number;
  opacity: number;
};

export type TextItem = CaptionItem | MetricItem | TagItem;

const Label = ({children, scale}: {children: string; scale: number}) => (
  <div
    style={{
      fontSize: TYPE.label * scale,
      lineHeight: `${LABEL_LINE * scale}px`,
      fontWeight: 500,
      letterSpacing: '0.14em',
      textTransform: 'uppercase',
      color: INK.paper2,
      marginBottom: LABEL_GAP * scale,
      whiteSpace: 'nowrap',
    }}
  >
    {children}
  </div>
);

function Caption({item, scale}: {item: CaptionItem; scale: number}) {
  const size = (item.size ?? 40) * scale;
  const parts = item.accent ? item.text.split(item.accent) : [item.text];
  const centered = item.align === 'center';
  return (
    <div
      data-text-id={item.id}
      style={{
        position: 'absolute',
        left: item.x,
        top: item.y,
        transform: centered ? 'translateX(-50%)' : item.align === 'right' ? 'translateX(-100%)' : undefined,
        textAlign: item.align ?? 'left',
      }}
    >
      <div style={entrance(item.opacity, scale)}>
        {item.label ? <Label scale={scale}>{item.label}</Label> : null}
        {item.text ? (
          <div
            style={{
              ...NUMERIC,
              fontSize: size,
              fontWeight: 400,
              letterSpacing: '-0.015em',
              lineHeight: 1.1,
              color: INK.paper,
              whiteSpace: item.maxWidth ? 'normal' : 'nowrap',
              maxWidth: item.maxWidth,
              textWrap: item.maxWidth ? 'balance' : undefined,
            }}
          >
            {parts.map((part, i) => (
              <span key={i}>
                {part}
                {i < parts.length - 1 ? <span style={{color: INK.accent}}>{item.accent}</span> : null}
              </span>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function Metric({item, scale}: {item: MetricItem; scale: number}) {
  const size = (item.size ?? 72) * scale;
  const align = item.align ?? 'left';
  return (
    <div
      data-text-id={item.id}
      style={{
        position: 'absolute',
        // x is the metric's left edge, centre or right edge, as aligned.
        left: item.x,
        top: item.y,
        transform: align === 'right' ? 'translateX(-100%)' : align === 'center' ? 'translateX(-50%)' : undefined,
        textAlign: align,
      }}
    >
      <div style={entrance(item.opacity, scale)}>
        <Label scale={scale}>{item.label}</Label>
        <div style={{whiteSpace: 'nowrap', color: INK.paper, lineHeight: 1}}>
          <span style={{...NUMERIC, fontSize: size, fontWeight: 300, letterSpacing: '-0.03em', color: item.accent ? mix(INK.paperRGB, INK.accentRGB, item.accent) : undefined}}>
            {item.value}
          </span>
          {item.unit ? (
            <span style={{fontSize: Math.max(TYPE.label * scale, size * 0.28), fontWeight: 400, color: INK.paper2, marginLeft: 6 * scale}}>{item.unit}</span>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function Tag({item, scale}: {item: TagItem; scale: number}) {
  const leader = item.leader * item.opacity;
  const textStyle: CSSProperties = {
    position: 'absolute',
    whiteSpace: item.maxWidth ? 'normal' : 'nowrap',
    maxWidth: item.maxWidth,
    textWrap: item.maxWidth ? 'balance' : undefined,
    opacity: item.opacity,
    textAlign: item.direction === 'left' ? 'right' : item.direction === 'right' ? 'left' : 'center',
  };
  let line: CSSProperties;
  if (item.direction === 'up') {
    line = {left: item.x - 0.5, top: item.y - leader, width: 1, height: leader};
    Object.assign(textStyle, {left: item.x, top: item.y - leader - 8 * scale, transform: 'translate(-50%, -100%)'});
  } else if (item.direction === 'down') {
    line = {left: item.x - 0.5, top: item.y, width: 1, height: leader};
    Object.assign(textStyle, {left: item.x, top: item.y + leader + 6 * scale, transform: 'translate(-50%, 0)'});
  } else {
    const sign = item.direction === 'left' ? -1 : 1;
    line = {left: sign < 0 ? item.x - leader : item.x, top: item.y - 0.5, width: leader, height: 1};
    Object.assign(textStyle, {
      left: item.x + sign * (leader + 10 * scale),
      top: item.y,
      transform: sign < 0 ? 'translate(-100%, -50%)' : 'translate(0, -50%)',
    });
  }
  const tagSize = item.size ?? TYPE.tag;
  return (
    <>
      {!item.customLeader && leader > 0 ? <div style={{position: 'absolute', background: INK.hairline, ...line}} /> : null}
      <div data-text-id={item.id} style={textStyle}>
        <div style={{...NUMERIC, fontSize: tagSize * scale, fontWeight: 400, color: INK.paper, lineHeight: 1.15}}>{item.text}</div>
        {item.sub ? (
          <div style={{...NUMERIC, fontSize: TYPE.label * scale, fontWeight: 500, letterSpacing: '0.08em', color: INK.paper2, marginTop: 4 * (tagSize / TYPE.tag) * scale, opacity: item.subOpacity ?? 1}}>
            {item.sub}
          </div>
        ) : null}
      </div>
    </>
  );
}

/** Each item's root carries `data-text-id`, so knockouts can find its laid-out glyphs. */
export const Typography = ({items, scale, ref}: {items: TextItem[]; scale: number; ref?: Ref<HTMLDivElement>}) => (
  <div ref={ref} style={{position: 'absolute', inset: 0, fontFamily: FONT_STACK, pointerEvents: 'none'}}>
    {items
      .filter((item) => item.opacity > 0.004)
      .map((item) =>
        item.kind === 'caption' ? (
          <Caption key={item.id} item={item} scale={scale} />
        ) : item.kind === 'metric' ? (
          <Metric key={item.id} item={item} scale={scale} />
        ) : (
          <Tag key={item.id} item={item} scale={scale} />
        ),
      )}
  </div>
);
