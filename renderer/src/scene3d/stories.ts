import {z} from 'zod';

/**
 * Per-kind `story` contracts, written by the Python directors (flyover.py,
 * stretch.py, strata.py). The scene loader parses the story of its kind, so a
 * renamed or missing field fails on load with its path instead of drawing
 * `undefined` somewhere in the middle of a render. Optional facts arrive as
 * `null` from Python and are read as `undefined`.
 */

const lngLat = z.tuple([z.number(), z.number()]);

/** An optional fact: Python sends `null`, the scores read `undefined`. */
const optional = <T extends z.ZodType>(schema: T) => schema.nullish().transform((value) => value ?? undefined);

const heading = z.object({
  label: optional(z.string()),
  text: z.string(),
  accent: optional(z.string()),
});

const stat = z.object({
  label: z.string(),
  value: z.string(),
  unit: optional(z.string()),
  /** The figure a closing highlight is about: its value takes the accent. */
  accent: optional(z.boolean()),
});

export const flyoverClimbSchema = z.object({
  lon: z.number(),
  lat: z.number(),
  alt: z.number(),
  startAlt: z.number(),
  startM: z.number(),
  endM: z.number(),
  hero: z.boolean(),
  /** Long enough for a trace under the ascent counter (channel `trace<k>`). */
  trace: optional(z.boolean()),
  /** Metres above the climb's foot, evenly spaced along it. */
  rise: optional(z.array(z.number())),
  /** Length and average grade, shown under the trace once the summit is reached. */
  summary: optional(z.string()),
});

/** The vertical plane (facing the level side camera) the route straightens into. */
export const flyoverUnfoldSchema = z.object({
  center: lngLat,
  /** Screen-right unit vector (east, north). */
  right: lngLat,
  lineM: z.number(),
  /** Plane baseline height and vertical scale (exaggerated metres per metre). */
  baseZ: z.number(),
  vertical: z.number(),
  minAlt: z.number(),
  altRange: z.number(),
});

/** Screen furniture placement (px), decided by the director (`_Layout` in flyover.py). */
export const flyoverLayoutSchema = z.object({
  marginX: z.number(),
  topY: z.number(),
  /** Top of the live counters, in the top corners. */
  countersY: z.number(),
  /** Height (m) the route is drawn above the relief, so slopes do not shadow their own road. */
  routeLift: z.number(),
  /** The climb trace's box, centred under the counters. */
  trace: z.tuple([z.number(), z.number(), z.number(), z.number()]),
});

export const flyoverStorySchema = z.object({
  title: heading,
  labels: z.object({
    distance: z.string(),
    ascent: z.string(),
    kmUnit: z.string(),
    mUnit: z.string(),
    peakAlt: z.string(),
  }),
  unfold: flyoverUnfoldSchema,
  layout: flyoverLayoutSchema,
  totalM: z.number(),
  profile: z.array(z.number()),
  peakFraction: z.number(),
  climbs: z.array(flyoverClimbSchema),
  stats: z.array(stat),
  /** One closing line on where the ride stands among the others (opt-in, often absent). */
  highlight: optional(z.string()),
});

export const stretchStorySchema = z.object({
  home: lngLat,
  pullBearing: z.number(),
  totalM: z.number(),
  totalKm: z.number(),
  rides: z.array(
    z.object({
      trackIndex: z.number().int(),
      lengthM: z.number(),
      beforeM: z.number(),
      restAlpha: z.number(),
      restWidth: z.number(),
    }),
  ),
  opening: heading.extend({label: z.string()}),
  counter: z.object({label: z.string(), unit: z.string()}),
  ending: heading,
  destination: optional(
    z.object({
      name: z.string(),
      at: lngLat,
      distanceM: z.number(),
    }),
  ),
});

export const strataStorySchema = z.object({
  corners: z.tuple([lngLat, lngLat, lngLat, lngLat]),
  floors: z.array(
    z.object({
      id: z.string(),
      /** The period (month or year), set small above its distance. */
      label: z.string(),
      /** Distance ridden in the period, formatted, and its unit. */
      value: z.string(),
      unit: z.string(),
      targetLift: z.number(),
      /** Vertical distance between floors (m); a landing plate starts this far above. */
      step: optional(z.number()),
      trackIndices: z.array(z.number().int()),
    }),
  ),
  opening: heading.extend({label: z.string()}),
  stats: z.array(stat),
});

export const territoryStorySchema = z.object({
  home: lngLat,
  rides: z.array(
    z.object({
      trackIndex: z.number().int(),
      /** When the ride starts drawing, and for how long (s). */
      t0: z.number(),
      dur: z.number(),
      /** Stretches (m along the ride) on roads never ridden before. */
      fresh: z.array(z.tuple([z.number(), z.number()])),
      /** Its month, shown while it is drawn. */
      period: z.string(),
      /** Per new stretch, per equal piece of it: when the piece reaches each next wear level (s). */
      wear: z.array(z.array(z.array(z.number()))).default([]),
    }),
  ),
  /** Rides over a piece at each wear level (the first is 1). */
  wearCounts: z.array(z.number()).default([1]),
  opening: heading.extend({label: z.string()}),
  counter: z.object({label: z.string(), unit: z.string()}),
  stats: z.array(stat),
});

export const ascentStorySchema = z.object({
  home: lngLat,
  rides: z.array(
    z.object({
      /** tracks[k] is rides[k]. Drawn from t0 for dur (s), while the counter takes its climbing. */
      t0: z.number(),
      dur: z.number(),
      /** Ridden away from home: moved to start there, kept off the map. */
      away: z.boolean(),
      period: z.string(),
    }),
  ),
  /** Each year's stretch of the line ends at `to` (m), complete at `t` (s); multi-year only. */
  years: z.array(z.object({to: z.number(), t: z.number(), label: z.string()})),
  /**
   * Known heights the line passes: drawn from t0, reached at t. With an outline (strokes of [right of home, up] m,
   * facing the camera) a thing standing beside the line; without, a level round it.
   */
  heights: z.array(
    z.object({at: z.number(), outline: z.array(z.array(z.tuple([z.number(), z.number()]))), t0: z.number(), t: z.number(), name: z.string(), value: z.string()}),
  ),
  opening: heading.extend({label: z.string()}),
  counter: z.object({label: z.string(), unit: z.string()}),
  stats: z.array(stat),
});

export const storySchemas = {
  flyover: flyoverStorySchema,
  stretch: stretchStorySchema,
  strata: strataStorySchema,
  territory: territoryStorySchema,
  ascent: ascentStorySchema,
} as const;

export type FlyoverClimb = z.infer<typeof flyoverClimbSchema>;
export type FlyoverUnfold = z.infer<typeof flyoverUnfoldSchema>;
export type FlyoverLayout = z.infer<typeof flyoverLayoutSchema>;
export type FlyoverStory = z.infer<typeof flyoverStorySchema>;
export type StretchStory = z.infer<typeof stretchStorySchema>;
export type StretchRideMeta = StretchStory['rides'][number];
export type StrataStory = z.infer<typeof strataStorySchema>;
export type StrataFloor = StrataStory['floors'][number];
export type TerritoryStory = z.infer<typeof territoryStorySchema>;
export type AscentStory = z.infer<typeof ascentStorySchema>;
