import {z} from 'zod';
import {ascentStorySchema, flyoverStorySchema, strataStorySchema, stretchStorySchema, territoryStorySchema} from './stories';

/**
 * Contract for the 3D scenes, written by
 * `src/ride_visuals/scene3d/spec.py`. The Python "director" owns the timing:
 * it sends the camera and every animated scalar ("channel") as one value per
 * frame, so the renderer is a deterministic player and the choreography can be
 * tested without a browser.
 */

const series = z.array(z.number());

export const encodedTrackSchema = z.object({
  x: z.array(z.number()),
  y: z.array(z.number()),
  d: z.array(z.number()),
  a: z.array(z.number()).nullable().optional(),
});

const sceneBaseSchema = z.object({
  schemaVersion: z.literal('1.0'),
  locale: z.enum(['en', 'pt-BR']),
  look: z.enum(['carbon', 'satellite']),
  profile: z.object({
    width: z.number().int().positive(),
    height: z.number().int().positive(),
    fps: z.number().int().positive(),
    durationInFrames: z.number().int().positive(),
  }),
  tiles: z.object({
    dem: z.string(),
    vector: z.string(),
    satellite: z.string().nullable(),
    demMaxZoom: z.number().int(),
    vectorMaxZoom: z.number().int(),
    satelliteMaxZoom: z.number().int(),
  }),
  /** Short data credit drawn on screen; null keeps the frame clean. */
  credits: z.string().nullable(),
  camera: z.object({
    lon: series,
    lat: series,
    zoom: series,
    pitch: series,
    bearing: series,
    /** Height of the camera's centre point, exaggerated metres. */
    elevation: series,
    /** Terrain exaggeration (0 = flat map). */
    terrain: series,
    /** 1 renders the globe, 0 Web Mercator. */
    globe: series,
    mapOpacity: series,
    contours: series,
    /** Satellite imagery mix over the carbon map (satellite look only). */
    satellite: series,
    /** Hillshade contrast multiplier; older specs omit it (1). */
    shade: series.optional(),
  }),
  channels: z.record(z.string(), series),
  tracks: z.array(encodedTrackSchema),
});

/** `story` holds the kind-specific facts (labels, stats, plates...), see stories.ts. */
export const sceneSpecSchema = z.discriminatedUnion('kind', [
  sceneBaseSchema.extend({kind: z.literal('flyover'), story: flyoverStorySchema}),
  sceneBaseSchema.extend({kind: z.literal('stretch'), story: stretchStorySchema}),
  sceneBaseSchema.extend({kind: z.literal('strata'), story: strataStorySchema}),
  sceneBaseSchema.extend({kind: z.literal('territory'), story: territoryStorySchema}),
  sceneBaseSchema.extend({kind: z.literal('ascent'), story: ascentStorySchema}),
]);

export type SceneSpec = z.infer<typeof sceneSpecSchema>;
export type SceneKind = SceneSpec['kind'];
export type SceneSpecOf<K extends SceneKind> = Extract<SceneSpec, {kind: K}>;

/** Composition props: the (large) spec is fetched once per tab, not serialised per frame. */
export const sceneInputSchema = z.object({
  specUrl: z.string(),
  width: z.number().int().positive(),
  height: z.number().int().positive(),
  fps: z.number().int().positive(),
  durationInFrames: z.number().int().positive(),
});

export type SceneInput = z.infer<typeof sceneInputSchema>;
